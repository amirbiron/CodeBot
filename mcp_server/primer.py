"""``GET /api/agent/primer`` — פריימר טקסטואלי שנקרא בפתיחת סשן של סוכן AI.

הגוף הוא ``text/plain``, לא JSON: מה שיוצא מכאן נכנס להקשר של המודל **כפי שהוא**.
הוא מורכב משני חלקים — הוראות חופשיות שהמשתמש עורך בדפדפן (עיקר התוכן), ואחריהן
שורת מצב קצרה שנבנית בזמן אמת.

ארבעה אילוצים מעצבים את הקוד כאן:

* **אימות.** הראוט קורא ל-``authenticate_bearer`` בגוף שלו. הוא *לא* מסתמך על כך
  שהאפליקציה מוגנת: במצב OAuth (הפרודקשן) ה-``PATAuthMiddleware`` לא מותקן בכלל,
  וה-SDK עוטף רק את ה-mount של ``/mcp`` — ראוט שנרשם ידנית יוצא ציבורי. ראו את
  ה-docstring של ``mcp_server.auth``.
* **תקרת 8KB.** חורגים ⇒ חותכים ומוסיפים שורה שאומרת שנחתך. לעולם לא שגיאה:
  פריימר חתוך עדיף על פריימר חסר.
* **60 שניות cache.** נקרא בפתיחת כל סשן, ולכן אסור לו לגעת בשאילתה כבדה.
* **סינון סודות.** הפריימר עובר דרך המודל, ולכן הוא מסונן בכל מקרה — גם אם
  המשתמש הדביק מפתח לשדה ההוראות בטעות. ערכי משתני סביבה של השרת לא נכנסים
  לגוף כלל: אין כאן שום קריאה ל-``os.environ``.

התקרה וה-TTL הם **קבועים בקוד** ולא משתני סביבה, במכוון. ה-8KB אינו כוונון
תפעולי אלא תקציב מול חלון ההקשר של המודל, שמתחלק עם כל השאר בסשן; אילו היה
משתנה סביבה, מצב הכשל של העלאתו היה בלתי-נראה (הקשר נאכל בשקט, בלי שאף אחד
מתריע). שינוי דורש PR — וזה החיכוך הנכון.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from datetime import UTC, datetime
from typing import Any

import anyio
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

from .auth import authenticate_bearer, unauthorized

logger = logging.getLogger(__name__)

PRIMER_PATH = "/api/agent/primer"

#: תקרת גודל הגוף בבייטים. קבוע במכוון — ראו את ה-docstring של המודול.
MAX_BYTES = 8 * 1024

#: משך ה-cache בשניות.
CACHE_TTL_SECONDS = 60

#: כותרת ה-cache. ``private`` — פריימר הוא תוכן אישי, אסור לפרוקסי משותף לשמור אותו.
_CACHE_CONTROL = f"private, max-age={CACHE_TTL_SECONDS}"

#: כמה קבצים אחרונים מופיעים בשורת המצב.
RECENT_FILES_COUNT = 3

#: תקרת ערכים ב-cache התהליכי (מונע דליפת זיכרון בשירות ארוך-חיים).
MAX_CACHE_ENTRIES = 512

#: סף האזהרה שה-UI בוובאפ מציג. חי כאן כי ``MAX_BYTES`` הוא מקור האמת שלו —
#: ``webapp.routes.settings_routes`` משכפל את שניהם (שני שירותים נפרדים, בלי
#: ייבוא ביניהם) ו-``test_mcp_primer`` מוודא שהערכים לא התפצלו.
WARN_BYTES = 7 * 1024

_TRUNCATION_NOTICE = (
    "\n[הפריימר נחתך כאן: ההוראות חורגות מתקרת 8KB. "
    "קצרו אותן בהגדרות CodeKeeper — ההמשך לא נשלח לסוכן.]"
)

_SEPARATOR = "\n\n---\n"


# --------------------------------------------------------------------------
# סינון סודות
# --------------------------------------------------------------------------
# מרחיב את הדפוסים של ``utils.SensitiveDataFilter`` (שמסנן לוגים) ומוסיף את
# הטוקנים של השירות הזה עצמו. הסינון רץ על **כל** הגוף המוגמר, לא רק על שדה
# ההוראות — כדי ששום נתיב עתידי שיוסיף תוכן לגוף לא יעקוף אותו בטעות.
_REDACTED = "***REDACTED***"

_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # מפתחות פרטיים — קודם, כי הם רב-שורתיים ובולעים את מה שביניהם
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
        f"[PRIVATE KEY {_REDACTED}]",
    ),
    # GitHub
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"), _REDACTED),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), _REDACTED),
    # הטוקנים של CodeKeeper עצמו: PAT, OAuth access, OAuth refresh, auth code
    (re.compile(r"ck(?:mcp|oat|ort|oc)_[A-Za-z0-9\-_]{16,}"), _REDACTED),
    # ספקי AI / ענן נפוצים
    (re.compile(r"sk-(?:ant-|proj-)?[A-Za-z0-9\-_]{20,}"), _REDACTED),
    (re.compile(r"AKIA[0-9A-Z]{16}"), _REDACTED),
    (re.compile(r"xox[abprs]-[A-Za-z0-9\-]{10,}"), _REDACTED),
    (re.compile(r"AIza[A-Za-z0-9\-_]{30,}"), _REDACTED),
    # JWT (שלושה חלקים base64url)
    (
        re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
        _REDACTED,
    ),
    # כותרת Authorization שהודבקה כטקסט
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9\-_.=:/+]{10,}"), f"Bearer {_REDACTED}"),
    # שורות בסגנון .env: ‏FOO_TOKEN=...‎ / ‏export API_KEY: ...‎
    #
    # שתי הגבלות שמונעות פגיעה בטקסט רגיל — פריימר מושחת גרוע מפריימר לא מסונן:
    # (1) הערך חייב להיות באורך של סוד אמיתי (12+ תווים), כדי ש-``key=value``
    #     בתוך הסבר לא ייעלם; (2) placeholder או הפניה למשתנה סביבה
    #     (``<your-key>``, ``${OPENAI_KEY}``, ``...``) אינם סוד ונשארים קריאים.
    (
        re.compile(
            r"(?im)^([ \t]*(?:export[ \t]+)?[A-Za-z0-9_]*"
            r"(?:KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIALS?|APIKEY)[A-Za-z0-9_]*)"
            r"[ \t]*[=:][ \t]*(?!['\"]?(?:<|\$\{|\$[A-Za-z_]|\.\.\.|%s|\{\{))"
            r"['\"]?[^\s'\"]{12,}"
        ),
        r"\1=" + _REDACTED,
    ),
    # מחרוזות חיבור עם סיסמה מוטמעת: scheme://user:pass@host
    (
        re.compile(r"(?i)\b([a-z][a-z0-9+.\-]*://[^\s:/@]+):[^\s/@]+@"),
        r"\1:" + _REDACTED + "@",
    ),
)


def redact_secrets(text: str) -> str:
    """מחזיר את הטקסט כשכל מה שנראה כמו מפתח/טוקן מוחלף.

    פייל-סייף: אם דפוס כלשהו נכשל, מדלגים עליו וממשיכים — עדיף סינון חלקי על
    פריימר שנופל. שאר הדפוסים עדיין רצים.
    """
    out = text or ""
    for pattern, replacement in _SECRET_PATTERNS:
        try:
            out = pattern.sub(replacement, out)
        except Exception:  # pragma: no cover — הגנה, לא זרימה צפויה
            logger.warning("primer redaction pattern failed", exc_info=True)
    return out


# --------------------------------------------------------------------------
# הרכבת הגוף
# --------------------------------------------------------------------------
def _truncate_to_bytes(text: str, max_bytes: int) -> tuple[str, bool]:
    """חותך ל-``max_bytes`` בגבול תו UTF-8 שלם.

    מחזיר ``(טקסט, נחתך?)``. חיתוך נאיבי של ``encode()[:n]`` היה יכול לחצות תו
    עברי באמצע ולהוציא בייטים לא-תקינים — ולכן ``errors="ignore"`` בפענוח החוזר,
    שמפיל בדיוק את התו החלקי האחרון.
    """
    if max_bytes <= 0:
        return "", bool(text)
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text, False
    return raw[:max_bytes].decode("utf-8", errors="ignore"), True


def _relative_time(when: datetime, *, now: datetime) -> str:
    """מתי נשמר, בשפה טבעית — בלי לדרוש מהסוכן לדעת מה השעה עכשיו."""
    delta = now - when
    seconds = int(delta.total_seconds())
    if seconds < 0:  # שעון שלא מסונכרן — לא ממציאים עתיד
        return "לפני רגע"
    minutes, hours, days = seconds // 60, seconds // 3600, seconds // 86400
    if seconds < 90:
        return "לפני רגע"
    if minutes < 60:
        return f"לפני {minutes} דקות"
    if hours < 24:
        return "לפני שעה" if hours == 1 else f"לפני {hours} שעות"
    if days < 30:
        return "אתמול" if days == 1 else f"לפני {days} ימים"
    return when.strftime("%Y-%m-%d")


def _as_utc(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def build_status_line(files: list[dict[str, Any]], *, now: datetime | None = None) -> str:
    """שורת המצב: שמות הקבצים האחרונים שנשמרו ומתי. ותו לא.

    מחזיר מחרוזת ריקה כשאין קבצים — שורת מצב ריקה עדיפה על שורה שמדווחת על כלום.
    """
    now = now or datetime.now(UTC)
    parts: list[str] = []
    for item in files or []:
        name = str((item or {}).get("file_name") or "").strip()
        if not name:
            continue
        when = _as_utc((item or {}).get("saved_at"))
        parts.append(f"{name} ({_relative_time(when, now=now)})" if when else name)
    if not parts:
        return ""
    return "קבצים אחרונים שנשמרו ב-CodeKeeper: " + ", ".join(parts)


def build_primer(
    instructions: str,
    files: list[dict[str, Any]] | None = None,
    *,
    now: datetime | None = None,
    max_bytes: int = MAX_BYTES,
) -> str:
    """מרכיב את גוף הפריימר המלא, מסונן וחתוך לפי הצורך.

    מחזיר מחרוזת ריקה כשאין הוראות — הקורא הופך את זה ל-204. הפריימר קיים כדי
    לשאת את ההוראות; שמות קבצים בלי מסגור הם רעש, לא פריימר.
    """
    # מסננים לפני המדידה: הצנזור משנה אורך, ומדידה על טקסט לא-מסונן הייתה
    # מוציאה גוף שחורג מהתקרה אחרי הסינון.
    body = redact_secrets((instructions or "").strip())
    if not body:
        return ""

    status = build_status_line(files or [], now=now)
    suffix = f"{_SEPARATOR}{status}\n" if status else "\n"

    # שורת המצב מקבלת מקום שמור: היא נבנית ראשונה ונחסרת מהתקציב, כדי שהוראות
    # ארוכות לא ידחפו אותה החוצה מהגוף.
    suffix_bytes = len(suffix.encode("utf-8"))
    notice_bytes = len(_TRUNCATION_NOTICE.encode("utf-8"))

    budget = max_bytes - suffix_bytes
    kept, truncated = _truncate_to_bytes(body, budget)
    if truncated:
        # מפנים מקום גם להודעת החיתוך עצמה — אחרת התוספת שלה תחזיר אותנו מעל התקרה.
        kept, _ = _truncate_to_bytes(body, max(budget - notice_bytes, 0))
        kept = kept.rstrip() + _TRUNCATION_NOTICE

    return kept + suffix


# --------------------------------------------------------------------------
# Cache
# --------------------------------------------------------------------------
class PrimerCache:
    """Cache תהליכי לפי ``user_id``, עם TTL ותקרת ערכים.

    לפי משתמש ולא גלובלי — פריימר של משתמש אחד לעולם לא יוגש לאחר. הזמן נמדד
    ב-``monotonic`` כדי שקפיצת שעון מערכת לא תאריך או תקצר TTL.
    """

    def __init__(
        self, ttl_seconds: float = CACHE_TTL_SECONDS, max_entries: int = MAX_CACHE_ENTRIES
    ):
        self._ttl = float(ttl_seconds)
        self._max = int(max_entries)
        self._lock = threading.Lock()
        self._data: dict[int, tuple[float, str]] = {}

    def get(self, user_id: int) -> str | None:
        now = time.monotonic()
        with self._lock:
            entry = self._data.get(int(user_id))
            if entry is None:
                return None
            expires_at, body = entry
            if expires_at <= now:
                self._data.pop(int(user_id), None)
                return None
            return body

    def put(self, user_id: int, body: str) -> None:
        now = time.monotonic()
        with self._lock:
            if len(self._data) >= self._max:
                # קודם ניקוי פגים; אם עדיין צפוף — מפנים את הישן ביותר.
                for key in [k for k, (exp, _) in self._data.items() if exp <= now]:
                    self._data.pop(key, None)
                while len(self._data) >= self._max:
                    oldest = min(self._data, key=lambda k: self._data[k][0])
                    self._data.pop(oldest, None)
            self._data[int(user_id)] = (now + self._ttl, body)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


#: ה-cache של השירות. מיוצא כדי שהוובאפ־צד־הבוט לא יצטרך להכיר את המבנה, ושטסטים
#: יוכלו לאפס אותו בין מקרים.
primer_cache = PrimerCache()


# --------------------------------------------------------------------------
# הראוט
# --------------------------------------------------------------------------
def _load_primer_sync(backend: Any, user_id: int) -> str:
    """שליפה + הרכבה. סינכרוני במכוון — הקורא מריץ אותו ב-thread נפרד."""
    try:
        instructions = backend.get_agent_instructions(int(user_id)) or ""
    except Exception:
        logger.warning("primer: failed to read agent instructions", exc_info=True)
        instructions = ""
    if not instructions.strip():
        # אין הוראות ⇒ 204. לא נוגעים במסד בשביל שורת מצב שלא תוגש.
        return ""
    try:
        files = backend.recent_files(int(user_id), limit=RECENT_FILES_COUNT) or []
    except Exception:
        # שורת המצב היא תוספת. אם היא נכשלה — עדיין מגישים את ההוראות.
        logger.warning("primer: failed to read recent files", exc_info=True)
        files = []
    return build_primer(instructions, files)


def agent_primer_route(
    backend: Any,
    *,
    token_store: Any = None,
    auth_provider: Any = None,
    cache: PrimerCache | None = None,
) -> Route:
    """בונה את ה-``Route`` של ``GET /api/agent/primer``.

    ``token_store``/``auth_provider`` הם אותם מאמתים שבהם משתמש טרנספורט ה-MCP —
    הראוט לא בונה מנגנון אימות משלו, רק קורא לאותו נתיב ולידציה.
    """
    active_cache = cache if cache is not None else primer_cache

    async def endpoint(request):
        principal = await authenticate_bearer(
            request, token_store=token_store, auth_provider=auth_provider
        )
        if not principal:
            return unauthorized("invalid_token")

        user_id = int(principal["user_id"])
        body = active_cache.get(user_id)
        if body is None:
            # קריאות pymongo חוסמות — מחוץ ל-event loop.
            body = await anyio.to_thread.run_sync(_load_primer_sync, backend, user_id)
            active_cache.put(user_id, body)

        if not body:
            # אין הוראות ⇒ אין פריימר. 204 ולא 200 עם גוף ריק.
            return Response(status_code=204, headers={"Cache-Control": _CACHE_CONTROL})

        return PlainTextResponse(
            body,
            media_type="text/plain; charset=utf-8",
            headers={"Cache-Control": _CACHE_CONTROL},
        )

    return Route(PRIMER_PATH, endpoint, methods=["GET"])
