"""גבולות הבקשה של שרת ה-MCP — תקרת גודל לגוף הבקשה, והגבלת קצב לפי זהות (#3431).

**מה היה חסר.** המידלוור היחיד שרץ היה ``PATAuthMiddleware`` — אימות ותו לא: כל
משתמש מאומת יכול היה לשלוח בקשות בכל גודל ובכל תדירות. ‏#3428 הוסיף תקרת אורך
ל-``path`` של כלי אחד, אחרי שנמדד שנתיב של 400KB עלה 608ms של מעבד — וזו
הקטנת משטח לבקשה בודדת, לא תחליף לשני הגבולות שכאן.

**שני גבולות, בשתי שכבות שונות, ולא במקרה.**

1. **גודל הגוף — במידלוור ASGI, לפני שהטרנספורט מפענח JSON.** הטרנספורט של
   ה-SDK (``mcp/server/streamable_http.py``, ‏``_handle_post_request``, ‏mcp 1.28.1)
   קורא את הגוף כולו ב-``await request.body()`` ואז ``json.loads`` — כלומר גוף
   של 20MB נטען ומפוענח במלואו לפני שאף כלי רואה ארגומנט. התקרה כאן היא לכן
   הגבול היחיד על **כל** ארגומנט של **כל** כלי, קיים ועתידי.

   **ולמה חיץ עד התקרה, ולא חריגה מתוך ``receive``.** אותו ``_handle_post_request``
   עוטף את קריאת הגוף ב-``try`` שתופס ``Exception`` ומחזיר שגיאת JSON-RPC משלו —
   חריגה שהיינו מרימים מתוך ``receive`` הייתה נבלעת שם והופכת ל"שגיאת שרת" בלי
   סיבה. לכן המידלוור קורא בעצמו את הודעות ``http.request`` עד התקרה, מסרב
   ב-413 **בעצמו** כשהיא נחצית, ואחרת משדר את מה שכבר נקרא הלאה כמות שהוא.
   גוף שמתחת לתקרה ממילא מוחזק בשלמותו על ידי ``request.body()``, ולכן החיץ אינו
   עולה זיכרון נוסף. ‏``Content-Length`` שמצהיר על יותר מהתקרה נדחה עוד לפני
   שנקרא בית אחד; כותרת חסרה או מכזבת נתפסת בספירה של מה שבאמת מגיע.
   הפרוטוקול: הודעות ``http.request`` עם ``body`` ו-``more_body``, ו-``http.disconnect``
   — כפי ש-``starlette/requests.py::Request.stream`` (Starlette 1.6.0) קורא אותן.

2. **קצב — בנקודת הכניסה של קריאות הכלים, לא במידלוור.** הזהות שהאישו מציע
   לספור לפיה ("הטוקן כבר מזוהה במידלוור") קיימת ב-``request.state`` רק במצב PAT;
   במצב OAuth — הייצור — ``PATAuthMiddleware`` אינו מותקן כלל, וה-SDK מאמת בתוך
   ה-mount של ``/mcp`` (ראו את ה-docstring של ``mcp_server/auth.py``). המקום היחיד
   שרואה את הזהות **בשני המצבים** הוא ``current_user_id`` על ה-``Context`` של
   הקריאה, ולכן ההכרעה יושבת ב-``AdminAwareFastMCP.call_tool`` — המתודה שה-SDK
   רושם כמטפל של ``tools/call`` (``FastMCP._setup_handlers``, ‏mcp 1.28.1), כלומר
   נקודה אחת שכל קריאת כלי עוברת בה: גוף סינכרוני לפני שהוא נמסר לחוט, גוף
   אסינכרוני לפני שהוא רץ על הלולאה. קריאה שנדחתה אינה עולה עובד. מה שאינו
   קריאת כלי — ``initialize``, ‏``tools/list``, זרם ה-SSE — זול ואינו נספר.

   **הפטור לנתיבי הדופק הוא מבני, לא רשימה.** ‏``/healthz`` (וכל נתיב HTTP אחר)
   לעולם אינו מגיע לנקודת השיגור של הכלים, ולכן המוניטור החיצוני שדוגם אותו
   בקצב קבוע אינו יכול לקבל 429 — המלכודת של ``blanket-policy-silent-block`` §7.
   וגם תקרת הגוף אינה נוגעת בו: ל-``GET`` אין גוף. שניהם מקובעים בטסט על
   האפליקציה האמיתית, לא על ההיגיון.

**הסירוב נוקב בסיבתו** — כמו ``path_too_long`` ו-``too_many_sections``: ‏413 עם
``{"error": "body_too_large", "max_bytes": ...}`` באותה צורה של ה-401 ב-``auth.py``,
וקריאת כלי שנחסמה מחזירה ``{"ok": false, "error": "rate_limited",
"limit_per_minute": ..., "retry_after_seconds": ...}`` — תשובת כלי רגילה, כי זה
מה שהסוכן קורא, ועם הזמן שנותר עד שהחלון משתחרר במקום "נסה שוב".

**המספרים, ומאיפה.** ראו ליד הקבועים. שניהם ניתנים לכיוון במשתני סביבה שנקראים
ב-``create_app`` (בכניסה לשירות, לא בזמן ייבוא), דרך :func:`limit_from_env`,
שלעולם אינו הופך ערך פגום לגבול רחב יותר מברירת המחדל.
"""

from __future__ import annotations

import logging
import math
import os
import time
from typing import Any, Awaitable, Callable

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

#: תקרת גוף הבקשה בבתים. הארגומנט הלגיטימי הגדול ביותר הוא ``content`` של
#: ``codekeeper_save_file``, שחסום ב-``config.MAX_CODE_SIZE`` — 100,000 תווים
#: (``mcp_server/handlers.py::_max_code_size``). לקוח שמקודד JSON עם
#: ``ensure_ascii`` הופך כל תו עברי ל-``\\uXXXX``, שישה בתים, ולכן הגוף הגדול
#: ביותר שיכול להיות נכון הוא כ-600KB ועוד המעטפת. 1MiB משאיר לזה מרווח,
#: ועדיין נמוך בסדר גודל ומעלה מגוף שהטרנספורט היה מפענח בלי התקרה.
DEFAULT_MAX_REQUEST_BYTES = 1_048_576

#: הרצפה לערך ממשתנה הסביבה: תקרה של עשרה בתים היא הפסקת שירות, לא הקשחה —
#: הודעת ``initialize`` לבדה היא כמה מאות בתים.
MIN_MAX_REQUEST_BYTES = 65_536

#: קריאות כלים לזהות אחת בדקה. נגזר מהמדידות בתגובה ב-#3431 (2026-09-20):
#: הבקשה הציבורית היקרה ביותר היום היא עמוד RST של 500KB — ‏0.24 שניות מעבד
#: עם תקרת הסקשנים (0.035 לעמוד הצפוף האמיתי); במסלול ה-Markdown (#3428)
#: המסמך הצפוף האמיתי עולה 0.47 שניות והצורה העוינת 2.3; המכסה היא 0.5 מעבד,
#: כלומר 30 שניות-מעבד בדקה. שישים קריאות של המסמך הצפוף האמיתי הן 28 שניות —
#: זהות אחת יכולה לכל היותר למלא דקת מעבד אחת משלה, ולא יותר; קריאה רגילה
#: (10–50ms) הופכת 60 בדקה לאחוז עד שלושה מהמכסה. ומול מאגר של 10 חוטים,
#: 60 בדקה הן קריאה אחת בשנייה לזהות — הוגנות, לא חנק.
DEFAULT_RATE_LIMIT_PER_MINUTE = 60

MAX_REQUEST_BYTES_ENV = "MCP_MAX_REQUEST_BYTES"
RATE_LIMIT_ENV = "MCP_RATE_LIMIT_PER_MINUTE"

BODY_TOO_LARGE = "body_too_large"
RATE_LIMITED = "rate_limited"


def limit_from_env(name: str, default: int, *, minimum: int, zero_disables: bool = False) -> int:
    """ערך מספרי ממשתנה סביבה, בלי שטעות תצורה תפתח את הגבול.

    ריק או חסר — ברירת המחדל. ערך שאינו מספר שלם — ברירת המחדל, עם WARNING
    שאומר מה נקרא (U3: משתנה סביבה הוא קלט חיצוני). ‏``0`` כשמותר לכבות —
    כיבוי מפורש, עם WARNING, כי זה מצב שצריך להיראות בלוג העלייה ולא להתגלות
    במקרה (K12 §3: בלי ברירת מחדל שקטה שמרחיבה). מתחת למינימום — המינימום,
    עם WARNING. בשום מסלול ערך פגום אינו הופך לגבול רחב יותר מברירת המחדל.
    """
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("%s=%r is not an integer; using the default %d", name, raw, default)
        return default
    if value == 0 and zero_disables:
        logger.warning("%s=0: this limit is switched off by configuration", name)
        return 0
    if value < minimum:
        logger.warning("%s=%d is below the minimum %d; using the minimum", name, value, minimum)
        return minimum
    return value


class BodySizeLimitMiddleware:
    """מידלוור ASGI טהור: גוף בקשה גדול מ-``max_bytes`` נדחה ב-413 לפני שמישהו מפענח אותו.

    ASGI טהור ולא ``BaseHTTPMiddleware``, כי הוא צריך את ``receive`` עצמו: ההודעות
    נקראות כאן, נספרות, ומשודרות הלאה — ו-``BaseHTTPMiddleware`` מסתיר את זה
    מאחורי ``Request``. ראו את ה-docstring של המודול על למה חיץ ולא חריגה.
    """

    def __init__(self, app: Any, *, max_bytes: int = DEFAULT_MAX_REQUEST_BYTES) -> None:
        self.app = app
        self.max_bytes = int(max_bytes)

    async def __call__(self, scope: dict, receive: Callable[[], Awaitable[dict]], send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        # U3: הכותרת היא קלט חיצוני. ספרות בלבד נחשבות מספר; כל צורה אחרת
        # נשארת לשרת ולטרנספורט לדחות, והספירה למטה עדיין תופסת מה שבאמת מגיע.
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_bytes:
            await self._refuse(scope, receive, send, content_length=int(declared))
            return

        buffered: list[dict] = []
        received = 0
        while True:
            message = await receive()
            buffered.append(message)
            if message.get("type") != "http.request":
                break  # ``http.disconnect`` — משודר הלאה כמות שהוא
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                await self._refuse(scope, receive, send, received_bytes=received)
                return
            if not message.get("more_body", False):
                break

        async def replay() -> dict:
            if buffered:
                return buffered.pop(0)
            return await receive()

        await self.app(scope, replay, send)

    async def _refuse(self, scope: dict, receive: Any, send: Any, **detail: int) -> None:
        # גודל ונתיב בלבד — לא הגוף ולא הטוקן (K13).
        logger.warning(
            "mcp request refused: body over %d bytes (%s) on %s",
            self.max_bytes,
            ", ".join(f"{k}={v}" for k, v in detail.items()),
            scope.get("path"),
        )
        response = JSONResponse(
            {"error": BODY_TOO_LARGE, "max_bytes": self.max_bytes, **detail}, status_code=413
        )
        await response(scope, receive, send)


class ToolRateLimiter:
    """הגבלת קצב לפי זהות על קריאות כלים, מעל ``rate_limiter.RateLimiter`` הקיים.

    אותו מגביל שהבוט משתמש בו (R6: לא עותק שני של חלון מתגלגל) — בזיכרון,
    ללא Redis, וזה מספיק כי שירות ה-MCP רץ במופע אחד (``numInstances: 1``,
    ‏``docs/mcp-server.rst``). ‏``per_minute == 0`` פירושו כבוי במפורש.
    """

    def __init__(self, per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE) -> None:
        self.per_minute = int(per_minute)
        self._limiter = RateLimiter(max_per_minute=self.per_minute) if self.per_minute > 0 else None
        self._warned_at: dict[int, float] = {}

    @property
    def enabled(self) -> bool:
        return self._limiter is not None

    async def admit(self, user_id: int) -> dict | None:
        """‏``None`` כשהקריאה מותרת; אחרת תשובת הסירוב שהכלי מחזיר במקום לרוץ."""
        if self._limiter is None:
            return None
        if await self._limiter.check_rate_limit(user_id):
            return None
        retry_after = await self._limiter.seconds_until_allowed(user_id)
        self._warn_once_per_window(user_id, retry_after)
        return {
            "ok": False,
            "error": RATE_LIMITED,
            "limit_per_minute": self.per_minute,
            "retry_after_seconds": math.ceil(retry_after),
        }

    def _warn_once_per_window(self, user_id: int, retry_after: float) -> None:
        # סירוב אחד נרשם לכל זהות לכל חלון — סוכן שממשיך לדפוק לא הופך את הלוג לתור.
        now = time.monotonic()
        last = self._warned_at.get(user_id)
        if last is not None and now - last < 60.0:
            return
        self._warned_at[user_id] = now
        logger.warning(
            "mcp tool rate limit: identity %s exceeded %d calls/min; refused for the next %.0fs",
            user_id,
            self.per_minute,
            retry_after,
        )
