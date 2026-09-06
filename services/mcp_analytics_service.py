"""
MCP Analytics Service
=====================
קריאת נתוני השימוש ב-MCP מ-PostHog, עבור מסך האדמין ``/admin/mcp``.

שרת ה-MCP מדווח ל-PostHog אירוע על כל קריאת כלי (``mcp_server/analytics.py``).
המודול הזה קורא את הנתונים חזרה דרך *endpoints* שמורים — שאילתות שחיות
ב-PostHog ולא בקוד, כך שאפשר לשנות אותן בלי דיפלוי.

**המפתח נשאר בצד השרת.** הוא עובר בכותרת ``Authorization`` בלבד, לעולם לא
בכתובת: ה-``limit`` נכנס לגוף ה-JSON לפי ה-OpenAPI spec של PostHog, ולכן
לבקשה אין שורת שאילתה כלל. זה חשוב מפני ש-``sentry-sdk`` רושם את שורת
השאילתה של כל בקשה יוצאת (גם מוצלחת) דרך ``StdlibIntegration``, ובקשה בלי
שאילתה לא נושאת מה לרשום.

ראו ``docs/webapp/mcp-analytics.rst``.
"""

from __future__ import annotations

import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# --- משתני סביבה (שירות ה-webapp) ---
ENV_API_KEY = "POSTHOG_PERSONAL_API_KEY"
ENV_PROJECT_ID = "POSTHOG_PROJECT_ID"
ENV_HOST = "POSTHOG_HOST"

# --- שמות האנדפוינטים ב-PostHog ---
ENDPOINT_TOOL_HEALTH = "ck_mcp_tool_health"
ENDPOINT_MISSING_CAPABILITIES = "ck_mcp_missing_capabilities"

#: הקריאות שנכשלו, שורה לכל אחת. יושב מתחת לטבלת הכלים באותו טאב ולא כטאב
#: נוסף: הוא הפירוט של עמודת השגיאות שכבר שם. בלעדיו הטבלה אומרת "20%
#: שגיאות" ולא אומרת למה — דוח מסירה בלי פתק המסירה.
ENDPOINT_TOOL_FAILURES = "ck_mcp_tool_failures"

#: **v2 ולא v1.** הגרסה השנייה מפצלת את ``file_reads`` לשתי עמודות לפי
#: ``ck_read_mode`` — אאוטליין מול קריאת תוכן — ומוסיפה את הכוונה של הסשן.
#: ``ck_mcp_navigation_cost`` (v1) נשאר חי ב-PostHog בכוונה: הוא הבסיס להשוואה
#: מול הטור המאוחד, והעמוד פשוט אינו קורא לו יותר.
ENDPOINT_NAVIGATION_COST = "ck_mcp_navigation_cost_v2"

# ``ck_mcp_navigation_cost_v2`` מחזיר שורה לכל סשן, ובלי ``limit`` הוא מחזיר
# את כולן — כמות שגדלה בלי תקרה. הספירה המלאה מגיעה בעמודה ``total_sessions``
# שנגזרת ב-``count() OVER ()`` בתוך השאילתה, ולכן התקרה כאן אינה מסתירה מידע.
NAVIGATION_COST_LIMIT = 50

#: הפאנל יושב בתוך טאב קיים ולא לבד, ולכן הוא קצר. אין לו ``total`` בשאילתה,
#: ולכן ``has_more`` הוא מה שאומר שנחתך.
TOOL_FAILURES_LIMIT = 25

TOTAL_COLUMN = "total_sessions"

#: נתיבי ה-UI של PostHog עצמו. שני דברים שהעמוד הזה **אינו יכול** להביא —
#: סיכום כוונה לסשן ואשכולות כוונות — הם כלי API של PostHog ולא שאילתות
#: HogQL, ולכן הם אינם נגישים דרך אנדפוינט שמור. במקום לחקות אותם חצי,
#: העמוד מקשר אליהם. הנתיבים נלקחו מטבלת הראוטים של PostHog.
POSTHOG_INTENT_CLUSTERS_PATH = "/mcp-analytics/intent-clustering"
POSTHOG_SESSIONS_PATH = "/mcp-analytics/sessions"

#: מה שהעמוד מריץ, ובאיזו תקרה. ``None`` פירושו בלי ``limit`` בגוף הבקשה.
#:
#: יושב ברמת המודול ולא בתוך :meth:`McpAnalyticsService.get_dashboard` כדי
#: שגם גודל ה-pool וגם הבדיקות ייגזרו מאותו מקור. הבדיקות ספרו קודם ``3``
#: כמספר קשיח, ואנדפוינט רביעי הפיל אותן על המספר במקום על ההתנהגות —
#: כלומר ההבטחה שהן שומרות (הכול רץ במקביל) הייתה נשברת בשקט ביום שמישהו
#: יוסיף חמישי ויתקן את המספר.
DASHBOARD_ENDPOINTS: tuple[tuple[str, int | None], ...] = (
    (ENDPOINT_TOOL_HEALTH, None),
    (ENDPOINT_TOOL_FAILURES, TOOL_FAILURES_LIMIT),
    (ENDPOINT_NAVIGATION_COST, NAVIGATION_COST_LIMIT),
    (ENDPOINT_MISSING_CAPABILITIES, None),
)

# --- תקציב זמן ---
# שלוש הגנות נפרדות, כי אף אחת מהן לבדה אינה מספיקה.
#
# 1. ``timeout`` חוסם בקשה בודדת שנתקעת — **והוא טאפל בכוונה.** ערך סקלרי
#    מתפרק ב-``requests`` ל-``connect`` *ו*-``read`` נפרדים
#    (``TimeoutSauce(connect=t, read=t)``), ו-urllib3 מקבל ``total=None``,
#    כלומר אין שום חסם על הסכום. ``timeout=3.0`` פירושו עד שש שניות
#    לבקשה, לא שלוש. נמדד.
# 2. ``max_attempts`` חוסם את לולאת ה-retry. **הוא לבדו אינו מספיק:**
#    ה-adapter של ``http_sync`` נושא ``urllib3.Retry`` משלו, ושתי השכבות
#    מוכפלות — ``max_attempts=2`` ייצר שש בקשות רשת. לכן מועבר גם
#    ``adapter_retries=False``, שמבטל את השכבה הפנימית לקריאה הזו.
#    שני ניסיונות נשמרים כדי לכבד את ``503 query_capacity``, שהתיעוד של
#    PostHog אומר עליו "retry shortly".
# 3. התקציב העליון חותך בוודאות, בלי תלות בשתי הראשונות ובלי תלות ב-ENV
#    שעלול לדרוס אותן.
#
# **התקציב אינו מתיימר לכסות את המקרה הגרוע, והחישוב אומר זאת במפורש:**
#
#   קריאה אחת שצורכת את מלוא הזמן : 2.0 + 4.0                = 6.0  < 7.0
#   worst case מלא עם retry        : 2 x 6.0 + backoff(<=0.75) = 12.75 > 7.0
#
# כלומר קריאה יחידה איטית **לא** נחתכת, ו-retry כן עשוי להיחתך — וזה
# הגיוני: retry עוזר כש-503 חוזר מהר, ולא כש-PostHog לוקח שש שניות לענות.
# להכניס את ה-worst case מתחת ל-7 היה מחייב ``connect + read <= 3.125``,
# כלומר לחנוק שאילתה על 30 יום נתונים. ראו ``docs/webapp/mcp-analytics.rst``.
REQUEST_CONNECT_TIMEOUT_SECONDS = 2.0
REQUEST_READ_TIMEOUT_SECONDS = 4.0
REQUEST_TIMEOUT = (REQUEST_CONNECT_TIMEOUT_SECONDS, REQUEST_READ_TIMEOUT_SECONDS)
REQUEST_MAX_ATTEMPTS = 2
TOTAL_BUDGET_SECONDS = 7.0

# כתובת הבליעה של PostHog (``us.i.posthog.com``) אינה כתובת ה-API
# (``us.posthog.com``). אותו שם משתנה משמש את שני השירותים עם ערכים שונים,
# ולכן ערך של שירות ה-MCP שיגיע לכאן היה מחזיר 404 — הודעה שמכוונת לחפש
# אנדפוינט חסר במקום משתנה סביבה שגוי.
#
# ההשוואה היא מול ה-**hostname** המפורסר ולא מול המחרוזת כולה: כתובת
# שנושאת את הרצף הזה בנתיב או בשאילתה אינה כתובת בליעה.
INGESTION_HOST_SUFFIX = ".i.posthog.com"

# מזהה הפרויקט ב-PostHog הוא מספר, והוא הערך היחיד מבין השלושה שנכנס
# לנתיב הכתובת. ספרות ASCII בלבד — ראו ההסבר ב-``resolve_config``.
PROJECT_ID_PATTERN = re.compile(r"[0-9]+")

# HTTPS בלבד. הבקשה נושאת את המפתח בכותרת ``Authorization``, ו-HTTP רגיל
# היה שולח אותו בטקסט גלוי — כלומר קונפיגורציה שגויה אחת מספיקה כדי
# להפוך את הסוד לחשוף על החוט.
ALLOWED_SCHEMES = ("https",)

# תווית ה-service למפסק. ה-endpoint נקבע פר-אנדפוינט כדי שכשל של אחד לא
# יפתח מפסק שחוסם את השניים האחרים.
CIRCUIT_SERVICE = "posthog"


# --- ניקוי הודעת ולידציה של Pydantic ---
#
# ההודעה הגולמית בנויה כך (**נמדד** על ``pydantic 2.12.3``, לא נזכר — הרינדור
# עצמו הוא ב-Rust ב-``pydantic_core`` ואין קוד פייתון לקרוא):
#
#   1 validation error for get_fileArguments      ← כותרת
#   lines.1                                       ← מיקום השדה
#     Input should be a valid integer [type=int_type, input_value='9', ...]
#       For further information visit https://errors.pydantic.dev/2.12/v/int_type
#
# בטבלה שלוש מתוך ארבע השורות האלה הן רעש: הכותרת נושאת את שם הכלי, שכבר יש
# לו עמודה משלו; ושורת ה-``For further information`` היא קישור לתיעוד של
# Pydantic, זהה בכל שגיאה מאותו סוג.
#
# **הפירסור פייל-סייף.** מה שאינו נראה כמו הודעת Pydantic מוחזר **כפי שהוא**,
# בלי לגעת. זה חשוב יותר מהניקוי עצמו: מאז שהשער נפתח לכל סוגי השגיאות,
# ההודעה כאן יכולה להיות של כל ספרייה — וקיצור שמנחש פורמט היה מוחק דווקא את
# מה שאי אפשר לאבחן בלעדיו.
_PYDANTIC_HEADER = re.compile(r"^\d+ validation errors? for \S+$")
_PYDANTIC_DOCS_LINE = re.compile(r"^\s+For further information visit https?://\S+$")
#: ``type=`` מוסר מהסוגריים — ההודעה עצמה ("Input should be a valid integer")
#: כבר אומרת את אותו דבר במילים. ``input_value`` ו-``input_type`` נשארים: הם
#: מה שמפריד בין "הסוכן טעה" ל"הסכימה לא ברורה".
_PYDANTIC_ERROR_TYPE = re.compile(r"\[type=[^,\]]+(,\s*)?")


def summarize_validation_message(message: Any) -> Any:
    """מקצר הודעת ולידציה של Pydantic לשורה אחת לכל שגיאה.

    ``lines.1 · Input should be a valid integer [input_value='9', input_type=str]``

    **מחזיר את הקלט כפי שהוא** כשהוא אינו מחרוזת, כשאין לו כותרת של Pydantic,
    או כשהמבנה אינו כצפוי. הכלל הזה הוא העיקר: הפונקציה מסירה רעש מוכר ואינה
    מנחשת. הודעה של ספרייה אחרת — pymongo, שגיאת מערכת — עוברת שלמה.
    """
    if not isinstance(message, str):
        return message
    lines = message.split("\n")
    if not lines or not _PYDANTIC_HEADER.match(lines[0].strip()):
        return message

    out: list[str] = []
    location: str | None = None
    for line in lines[1:]:
        if not line.strip() or _PYDANTIC_DOCS_LINE.match(line):
            continue
        if line[:1].strip():
            # שורה בלי הזחה — זה המיקום של השדה שנדחה.
            location = line.strip()
            continue
        detail = _PYDANTIC_ERROR_TYPE.sub("[", line.strip(), count=1).replace("[]", "").strip()
        out.append(f"{location} · {detail}" if location else detail)
        location = None

    # לא הצלחנו לחלץ ולו שורה אחת — עדיף המקור המלא מאשר תא ריק.
    return "\n".join(out) if out else message


@dataclass
class EndpointResult:
    """תוצאה של קריאה אחת לאנדפוינט PostHog.

    **החוזה: אף פונקציה במודול הזה אינה זורקת.** כשל מדווח ב-``error_code``
    בלבד, ולכן ``try/except`` סביב הקריאות כאן לא יופעל לעולם ואינו תחליף
    לבדיקת הערך.

    שני מצבים נראים דומה וחייבים להיבדל:

    * ``rows`` ריקה **ו**-``error_code`` ריק — הצלחה בלי שורות. זה המצב
      התקין של "כלים חסרים" עד שסוכן ידווח לראשונה.
    * ``rows`` ריקה **ו**-``error_code`` מלא — כשל.

    בלי ההבחנה הזו העמוד מציג "אין נתונים" על תקלה, וזו בדיוק הבליעה
    השקטה שהיא מקור הבאג הנפוץ ביותר בריפו.
    """

    rows: list[dict[str, Any]] = field(default_factory=list)
    error_code: str = ""
    error_detail: str = ""
    is_cached: bool = False
    last_refresh: str = ""
    has_more: bool = False
    total: int | None = None

    @property
    def ok(self) -> bool:
        """הצליח — כולל המקרה של אפס שורות."""
        return not self.error_code


def _config_error(code: str, detail: str) -> EndpointResult:
    return EndpointResult(error_code=code, error_detail=detail)


@dataclass(frozen=True)
class PostHogConfig:
    """קונפיגורציה תקפה של PostHog — כל שדה בה כבר אומת.

    המחלקה הזו קיימת כדי שלא ניתן יהיה לייצג "קונפיגורציה חלקית": פונקציית
    הפתרון מחזירה **או** את זה **או** ``EndpointResult`` עם שגיאה, ולעולם
    לא טאפל שבו חלק מהערכים ריקים לצד שגיאה. אותו עיקרון שחל על החוזה של
    ``EndpointResult`` — ערוץ אחד, ומצב לא חוקי שאינו ניתן לייצוג.
    """

    host: str
    project_id: str
    api_key: str


class McpAnalyticsService:
    """קורא את האנדפוינטים של PostHog ומחזיר שורות מוכנות לתבנית.

    הרשימה עצמה היא ``DASHBOARD_ENDPOINTS``, ולא מספר שכתוב כאן: ספירה בפרוזה
    מתיישנת בשקט ברגע שמישהו מוסיף אנדפוינט.
    """

    def resolve_config(self) -> PostHogConfig | EndpointResult:
        """מחזיר קונפיגורציה מאומתת, או שגיאה — לעולם לא שילוב של השתיים.

        כל הבדיקות כאן רצות **לפני** שנשלחת בקשה, מפני שקוד סטטוס שחוזר
        מכתובת שגויה מטעה יותר משהוא עוזר: כתובת הבליעה מחזירה ``404``,
        וההודעה על ``404`` שולחת לחפש אנדפוינט קיים.
        """
        api_key = (os.environ.get(ENV_API_KEY) or "").strip()
        project_id = (os.environ.get(ENV_PROJECT_ID) or "").strip()
        host = (os.environ.get(ENV_HOST) or "").strip().rstrip("/")

        missing = [
            name
            for name, value in (
                (ENV_API_KEY, api_key),
                (ENV_PROJECT_ID, project_id),
                (ENV_HOST, host),
            )
            if not value
        ]
        if missing:
            return _config_error(
                "config_missing",
                "המדידה אינה מוגדרת בשירות הוובאפ. חסר: " + ", ".join(missing),
            )

        # ``project_id`` הוא הערך היחיד מבין השלושה שנכנס ל**נתיב הכתובת**,
        # ו-``http_sync`` רושם את הכתובת המלאה כ-``http.url`` על ה-span. כלומר
        # ערך שנחת כאן בטעות — למשל מפתח שהודבק במשתנה הלא נכון — היה נרשם
        # לערוץ תצפית. זה ``CRITICAL-PATTERNS.md`` K14, בנתיב במקום בשורת
        # השאילתה.
        #
        # הבדיקה היא **רשימה לבנה**: היא מצהירה על הצורה הנתמכת במקום לנסות
        # לזהות "מה נראה כמו סוד". רשימה שחורה מפספסת כל צורה שלא נחזתה
        # מראש, וזו בדיוק הנקודה של K14. מזהה הפרויקט ב-PostHog הוא מספר
        # (הערך שהפרויקט הזה מחזיר הוא ``567754``), ולכן ספרות בלבד.
        #
        # ``str.isdigit()`` **אינו** מספיק כאן: הוא מחזיר ``True`` גם על
        # ספרות יוניקוד שאינן ASCII (``'٣٤'``, ``'²'``) — נבדק. הן היו
        # עוברות את מה שההערה למעלה מבטיחה ונכנסות לנתיב הכתובת. הביטוי
        # הרגולרי אומר בדיוק את מה שנטען.
        if not PROJECT_ID_PATTERN.fullmatch(project_id):
            # כמו ההודעות האחרות — מתארת מה נדרש, ואינה מצטטת את הערך.
            return _config_error(
                "config_invalid",
                f"הערך של {ENV_PROJECT_ID} אינו מזהה פרויקט תקין. נדרש מספר "
                "(ספרות בלבד) — מזהה הפרויקט המספרי של PostHog.",
            )

        parts = urlsplit(host)
        # הערך משמש כ-origin שאליו משורשר נתיב ה-API, ולכן כל רכיב נוסף —
        # נתיב, שאילתה, פרגמנט או פרטי הזדהות — היה מייצר כתובת שגויה
        # בשקט. נדחה כאן ולא מתגלה כ-404 מאוחר יותר.
        #
        # **הבדיקה היא ``is not None`` ולא ערך אמיתי, ולא ניסוח יפה.** נמדד:
        # ב-``https://:secret@us.posthog.com`` מחזיר ``urlsplit`` את
        # ``username=''`` — מחרוזת ריקה, שהיא falsy — ולכן ``or parts.username``
        # לבדו אישר את הכתובת. הסיסמה נשארה בערך הגולמי, שממנו נבנים גם נתיב
        # ה-API וגם הקישורים היוצאים שמרונדרים לעמוד: סוד ב-``href`` שנפתח
        # בדפדפן, כלומר בהיסטוריה וב-``Referer``.
        #
        # ולכן גם ``parts.password`` נבדק בנפרד: זו בדיוק הצורה שבה חצי מפרטי
        # ההזדהות קיים והחצי השני ריק.
        has_extra_parts = bool(
            parts.path
            or parts.query
            or parts.fragment
            or parts.username is not None
            or parts.password is not None
        )
        if parts.scheme not in ALLOWED_SCHEMES or not parts.hostname or has_extra_parts:
            # ההודעה מתארת מה נדרש, ולא מצטטת את הערך שהתקבל. הערך מגיע
            # מ-``os.environ`` ומוצג בעמוד HTML; מספיקה טעות העתקה אחת בין
            # שני משתני הסביבה כדי שסוד ייחת לכאן ויוצג. הערך עצמו נבדק
            # ב-Config Inspector, שם הוא ממוסך כשהוא רגיש.
            return _config_error(
                "config_invalid",
                f"הערך של {ENV_HOST} אינו כתובת תקינה. נדרשת כתובת https "
                "בלבד, בלי נתיב ובלי פרמטרים — למשל https://us.posthog.com",
            )

        # ההשוואה על ה-hostname המפורסר. ``in host`` היה תופס גם כתובת
        # שנושאת את הרצף בנתיב או בשאילתה, וזו אינה כתובת בליעה.
        hostname = parts.hostname.lower()
        bare_ingestion = INGESTION_HOST_SUFFIX.lstrip(".")
        if hostname.endswith(INGESTION_HOST_SUFFIX) or hostname == bare_ingestion:
            return _config_error(
                "host_is_ingestion",
                f"הערך של {ENV_HOST} בוובאפ הוא כתובת שליחת האירועים, "
                "ולא כתובת קריאת הנתונים. לקריאה צריך https://us.posthog.com "
                "(שירות ה-MCP משתמש באותו שם משתנה עם הכתובת השנייה).",
            )

        return PostHogConfig(host=host, project_id=project_id, api_key=api_key)

    def run_endpoint(self, name: str, limit: int | None = None) -> EndpointResult:
        """מריץ אנדפוינט אחד. לעולם אינו זורק — ראו ``EndpointResult``."""
        import requests  # noqa: PLC0415 — נדרש רק לטיפוסי החריגות

        from http_sync import CircuitOpenError
        from http_sync import request as http_request

        config = self.resolve_config()
        if isinstance(config, EndpointResult):
            return config

        url = f"{config.host}/api/projects/{config.project_id}/endpoints/{name}/run"
        body: dict[str, Any] = {}
        if limit is not None:
            body["limit"] = limit

        try:
            resp = http_request(
                "POST",
                url,
                json=body,
                headers={
                    # הסוד יושב כאן ורק כאן. אין לו דרך להגיע לכתובת.
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=REQUEST_TIMEOUT,
                max_attempts=REQUEST_MAX_ATTEMPTS,
                # בלי זה ``max_attempts`` אינו מספר הבקשות: ה-adapter של
                # ``http_sync`` נושא ``Retry`` משלו, ושתי השכבות מוכפלות.
                adapter_retries=False,
                service=CIRCUIT_SERVICE,
                endpoint=f"mcp_analytics.{name}",
            )
        except CircuitOpenError:
            return EndpointResult(
                error_code="unavailable",
                error_detail="הקריאות ל-PostHog הושהו זמנית אחרי כשלים חוזרים. נסה שוב בעוד רגע.",
            )
        except requests.RequestException as exc:
            # ``str(exc)`` נושא את הכתובת, והכתובת כאן נקייה: הסוד בכותרת
            # והפרמטרים בגוף. מי שיוסיף פרמטר לכתובת חייב לחזור לשורה הזו.
            logger.warning(
                "mcp_analytics_request_failed",
                extra={"mcp_endpoint": name, "error_type": type(exc).__name__},
            )
            return EndpointResult(
                error_code="unavailable",
                error_detail="הקריאה ל-PostHog נכשלה. נסה שוב בעוד רגע.",
            )

        return self._result_from_response(resp, name)

    def _result_from_response(self, resp: Any, name: str) -> EndpointResult:
        status = getattr(resp, "status_code", None)

        if status in (401, 403):
            return EndpointResult(
                error_code="unauthorized",
                error_detail=(
                    f"המפתח ב-{ENV_API_KEY} אינו תקף, או שחסר לו ה-scope ‎endpoint:read."
                ),
            )
        if status == 404:
            return EndpointResult(
                error_code="endpoint_not_found",
                error_detail=f"האנדפוינט {name} אינו קיים בפרויקט ה-PostHog הזה.",
            )

        payload = self._json_or_none(resp)

        if status == 503:
            return EndpointResult(
                error_code="unavailable",
                error_detail="PostHog עמוס כרגע. נסה שוב בעוד רגע.",
            )
        if status != 200:
            code, detail = self._error_fields(payload)
            return EndpointResult(
                error_code="query_failed",
                error_detail=self._query_failure_message(code, detail, status),
            )

        if not isinstance(payload, dict):
            return EndpointResult(
                error_code="bad_payload",
                error_detail="התשובה מ-PostHog אינה בפורמט הצפוי.",
            )

        # קוד סטטוס 200 אינו ראיה להצלחה: ``error`` בגוף התשובה הוא ערוץ
        # כשל נפרד, וקורא שבודק רק את הסטטוס יציג שגיאה כטבלה ריקה.
        inline_error = payload.get("error")
        if inline_error:
            return EndpointResult(
                error_code="query_failed",
                error_detail=f"השאילתה ב-PostHog החזירה שגיאה: {inline_error}",
            )

        rows, parse_error = self._rows_from_payload(payload)
        if parse_error:
            return EndpointResult(error_code="bad_payload", error_detail=parse_error)

        total = None
        if rows and isinstance(rows[0].get(TOTAL_COLUMN), int):
            total = rows[0][TOTAL_COLUMN]

        return EndpointResult(
            rows=rows,
            is_cached=bool(payload.get("is_cached")),
            last_refresh=str(payload.get("last_refresh") or ""),
            has_more=bool(payload.get("hasMore")),
            total=total,
        )

    @staticmethod
    def _json_or_none(resp: Any) -> Any:
        try:
            return resp.json()
        except Exception:
            return None

    @staticmethod
    def _error_fields(payload: Any) -> tuple[str, str]:
        if not isinstance(payload, dict):
            return "", ""
        return str(payload.get("code") or ""), str(payload.get("detail") or "")

    @staticmethod
    def _query_failure_message(code: str, detail: str, status: Any) -> str:
        """ה-spec של PostHog מורה במפורש להסתעף על ``code`` ולא על ``type``."""
        known = {
            "query_timeout": "השאילתה ב-PostHog חרגה מזמן הריצה המותר.",
            "query_memory_limit": "השאילתה ב-PostHog חרגה ממגבלת הזיכרון.",
            "query_too_large": "השאילתה ב-PostHog גדולה מדי.",
            "query_estimated_too_slow": "PostHog העריך שהשאילתה איטית מדי מכדי לרוץ.",
            "query_capacity": "PostHog עמוס כרגע. נסה שוב בעוד רגע.",
        }
        if code in known:
            return known[code]
        if detail:
            return f"השאילתה ב-PostHog נכשלה: {detail}"
        return f"השאילתה ב-PostHog נכשלה (קוד {status})."

    @staticmethod
    def _rows_from_payload(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
        """ממיר ``results`` + ``columns`` לרשימת מילונים.

        ה-spec מבטיח את ``results`` בלבד; ``columns`` אינו מובטח חוזית. ``zip``
        על רשימות באורך שונה חותך בשקט, ולכן אי-התאמה היא כשל מפורש כאן.
        """
        results = payload.get("results")
        columns = payload.get("columns")

        if not isinstance(results, list):
            return [], "התשובה מ-PostHog אינה כוללת שורות תקינות."
        # אפס שורות הוא מצב תקין ומצופה (הטאב השלישי בהשקה), ואין בו מה
        # לזווג — לכן הוא אינו תלוי בקיום ``columns``. בפועל PostHog כן
        # מחזיר ``columns`` גם ריק, אבל ה-spec מבטיח רק את ``results``.
        if not results:
            return [], ""
        if not isinstance(columns, list) or not columns:
            return [], "התשובה מ-PostHog אינה כוללת את שמות העמודות."
        if not all(isinstance(col, str) for col in columns):
            return [], "שמות העמודות בתשובה מ-PostHog אינם תקינים."

        rows: list[dict[str, Any]] = []
        for raw in results:
            if not isinstance(raw, (list, tuple)):
                return [], "שורה בתשובה מ-PostHog אינה בפורמט הצפוי."
            if len(raw) != len(columns):
                return [], "מספר הערכים בשורה אינו תואם למספר העמודות."
            # ``strict`` מיותר אחרי בדיקת האורך שלמעלה, והוא נשאר כרשת שנייה:
            # אם מישהו יסיר את הבדיקה, ה-``zip`` יזרוק במקום לחתוך בשקט.
            rows.append(dict(zip(columns, raw, strict=True)))
        return rows, ""

    def posthog_links(self) -> dict[str, str]:
        """קישורים יוצאים לתצוגות של PostHog עצמו, או מילון ריק.

        **מה הם, ולמה הם קישור ולא טבלה.** סיכום כוונה לסשן ואשכולות כוונות
        הם *כלי API* של PostHog — עבודת LLM שרצה ונשמרת אצלם — ולא שאילתות.
        הדשבורד הזה מדבר עם PostHog רק דרך אנדפוינטים שמורים, שהם HogQL בלבד,
        ולכן אין דרך להביא אותם לכאן. חיקוי חלקי היה מציג מספר שנראה כמו
        ``discovery rate`` בלי להיות אחד.

        הכתובת נבנית משני הערכים שכבר עברו ולידציה ב-:meth:`resolve_config`,
        ולכן אין כאן מה לנקות: ``project_id`` הוא ספרות ASCII בלבד ו-``host``
        הוא origin של ``https`` בלי נתיב, שאילתה או פרטי הזדהות. המפתח אינו
        משתתף בבנייה כלל — הוא חי רק בכותרת ``Authorization``.

        מילון ריק כשהקונפיגורציה פסולה: קישור שנבנה מערך שגוי מוביל לשום מקום,
        וההודעה על הקונפיגורציה כבר מוצגת בטאב עצמו.
        """
        config = self.resolve_config()
        if isinstance(config, EndpointResult):
            return {}
        base = f"{config.host}/project/{config.project_id}"
        return {
            "intent_clusters": f"{base}{POSTHOG_INTENT_CLUSTERS_PATH}",
            "sessions": f"{base}{POSTHOG_SESSIONS_PATH}",
        }

    def get_dashboard(self) -> dict[str, EndpointResult]:
        """מריץ את ארבעת האנדפוינטים ומחזיר מילון לפי שם.

        הקריאות רצות במקביל כדי להוריד את המקרה הטיפוסי מארבעה סבבי רשת
        לאחד. **המקבול אינו ההגנה מפני היתקעות** — הוא מקצר את הסכום ולא
        את הגרוע ביותר; לזה משמש התקציב העליון.

        התקציב לא זז כשנוסף האנדפוינט הרביעי, וזה לא פספוס: הוא נגזר מהמקרה
        הגרוע של קריאה **בודדת** (``connect + read``), וקריאה נוספת שרצה
        לצידה אינה מאריכה אותו. ה-pool מקבל worker לכל spec, ולכן הרביעי לא
        ממתין בתור.
        """
        specs = DASHBOARD_ENDPOINTS
        out: dict[str, EndpointResult] = {}
        deadline = time.monotonic() + TOTAL_BUDGET_SECONDS

        pool = ThreadPoolExecutor(max_workers=len(specs), thread_name_prefix="mcp-analytics")
        try:
            futures = {name: pool.submit(self.run_endpoint, name, limit) for name, limit in specs}
            for name, future in futures.items():
                remaining = max(0.0, deadline - time.monotonic())
                try:
                    out[name] = future.result(timeout=remaining)
                except FutureTimeoutError:
                    out[name] = EndpointResult(
                        error_code="unavailable",
                        error_detail="PostHog לא הספיק להשיב בזמן. נסה שוב בעוד רגע.",
                    )
                except Exception:
                    # ``run_endpoint`` אינו אמור לזרוק. אם הגענו לכאן, החוזה
                    # הופר — ורוצים לראות את זה בלוג, לא לבלוע.
                    logger.exception(
                        "mcp_analytics_unexpected_error", extra={"mcp_endpoint": name}
                    )
                    out[name] = EndpointResult(
                        error_code="unavailable",
                        error_detail="אירעה שגיאה בטעינת הנתונים.",
                    )
        finally:
            # ``with`` היה קורא ל-``shutdown(wait=True)`` וממתין לכל העבודה
            # שנותרה — כלומר מבטל את התקציב שנאכף למעלה.
            #
            # ``cancel_futures`` מבטל רק משימות שטרם התחילו; משימה שכבר רצה
            # ממשיכה עד שה-``timeout`` של הבקשה עוצר אותה. זו הסיבה שהתקציב
            # נקבע מעל המקרה הגרוע של קריאה בודדת — כך ה"זנב" הזה קצר
            # מהתשובה עצמה ואינו מחזיק את ה-worker בזמן כיבוי.
            pool.shutdown(wait=False, cancel_futures=True)

        return out


_service: McpAnalyticsService | None = None


def get_mcp_analytics_service() -> McpAnalyticsService:
    """קבלת instance יחיד של השירות."""
    global _service
    if _service is None:
        _service = McpAnalyticsService()
    return _service
