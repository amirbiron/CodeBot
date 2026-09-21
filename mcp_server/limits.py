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

   **מה המידלוור קורא, ומה לא.** הגרסה הראשונה (#3431) קראה כל גוף עד התקרה
   לפני שהשכבה הבאה ראתה את הבקשה — גם גוף אנונימי שהאימות היה דוחה מהכותרות
   בלבד, ובלי דדליין; זו הייתה רגרסיה (SEC-001 בסקירת שבעת ה-PRים): במצב OAuth
   האימות של ה-SDK יושב **בתוך** ה-mount של ``/mcp``, ולכן התקרה, שהיא השכבה
   החיצונית, החזיקה עד 1MiB לכל חיבור אנונימי לפני ה-401, וכל עוד הלקוח טפטף
   בתים. שלושה כללים סוגרים את זה, וכל אחד מקובע בטסט שנפל לפני שנכתב:

   - **רק מתודות שנושאות גוף נבדקות** (:data:`METHODS_WITH_BODY`). שום route כאן
     אינו קורא גוף במתודה אחרת — הטרנספורט קורא ב-``POST``, ו-DCR, token ו-consent
     הם ``POST`` — ולכן ``GET /healthz`` עם ``Content-Length`` מזויף, שקודם ענה
     413, עובר בלי שהתקרה מסתכלת עליו.
   - **אורך מוצהר תקין עובר בלי קריאה.** ‏``Content-Length`` של ספרות ASCII (מה
     ש-h11 מקבל: ``_content_length_re = re.compile(rb"[0-9]+")``, ‏``h11/_headers.py``)
     שאין לצידו ``Transfer-Encoding`` הוא תיחום של השרת: uvicorn/h11 מוסרים
     לאפליקציה בדיוק את המספר הזה — נמדד: 20 בתים מאחורי ``Content-Length: 10``
     הגיעו כ-10. גדול מהתקרה — 413 בלי שנקרא בית; קטן ממנה — הבקשה עוברת הלאה
     כמות שהיא, והשכבה שעונה מהכותרות (ה-401) עונה בלי קריאה. **הסייג הוא
     ``Transfer-Encoding``:** לצידו h11 תוחם לפי chunked ומעביר את שתי הכותרות
     (RFC 7230 §3.3.3), ונמדד ש-200 בתים מאחורי ``Content-Length: 5`` הגיעו
     במלואם — ולכן שם סופרים כמו בלי כותרת.
   - **מה שנשאר לספירה — גוף בלי אורך מוצהר — נקרא עד התקרה, ותחת דדליין.**
     ל-uvicorn 0.38.0 אין timeout לגוף בקשה (``timeout_keep_alive`` חל אחרי
     תשובה), ולכן בלי דדליין ההמתנה לנתח הבא אינה חסומה. הלולאה כולה — לא כל
     קריאה בנפרד, כי בית כל 29 שניות היה עובר דדליין-לקריאה — רצה תחת
     ``anyio.fail_after`` (:data:`DEFAULT_BODY_READ_SECONDS`), וכשהוא פג התשובה
     היא 408 שאומר כמה נקרא.

   **ולמה חיץ עד התקרה, ולא חריגה מתוך ``receive``.** אותו ``_handle_post_request``
   עוטף את קריאת הגוף ב-``try`` שתופס ``Exception`` ומחזיר שגיאת JSON-RPC משלו —
   חריגה שהיינו מרימים מתוך ``receive`` הייתה נבלעת שם והופכת ל"שגיאת שרת" בלי
   סיבה. לכן המידלוור קורא בעצמו את הודעות ``http.request`` עד התקרה, מסרב
   ב-413 **בעצמו** כשהיא נחצית, ואחרת משדר את מה שכבר נקרא הלאה כמות שהוא.
   גוף שמתחת לתקרה ממילא מוחזק בשלמותו על ידי ``request.body()``, ולכן החיץ אינו
   עולה זיכרון נוסף. הפרוטוקול: הודעות ``http.request`` עם ``body`` ו-``more_body``,
   ו-``http.disconnect`` — כפי ש-``starlette/requests.py::Request.stream``
   (Starlette 1.6.0) קורא אותן.

   **סירוב סוגר את החיבור.** שני הסירובים מגיעים לפני שהגוף נגמר, ולכן נושאים
   ``Connection: close``: h11 מכבה keep-alive על תשובה שנושאת אותו
   (``h11/_connection.py::_keep_alive``), ו-uvicorn סוגר את ה-transport מיד אחרי
   התשובה (``h11_impl.py::send`` — ``our_state is MUST_CLOSE``). בלעדיו השרת היה
   ממשיך לקרוא ולזרוק את שארית הגוף שסירבנו לו, ומחזיק חיבור פתוח לגוף
   שלא הגיע. ל-408 זה גם מה שהתקן מבקש: "the server SHOULD send the 'close'
   connection option in the response, since 408 implies that the server has
   decided to close the connection rather than continue waiting" (RFC 9110
   §15.5.9, מצוטט כאן לפי MDN).

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

   **הפטור לנתיב הדופק — שני חצאים, ורק אחד מהם מבני.** מהמגביל ``/healthz`` פטור
   במבנה: הוא אינו קריאת כלי, ולכן לעולם אינו מגיע לנקודת השיגור, והמוניטור
   החיצוני שדוגם אותו בקצב קבוע אינו יכול לקבל 429 — המלכודת של
   ``blanket-policy-silent-block`` §7. מתקרת הגוף הוא פטור **בכלל**, לא במבנה:
   ``GET`` אינה מתודה שנושאת גוף ולכן התקרה אינה מסתכלת עליה — עד SEC-001 היא
   כן הסתכלה, ו-``GET /healthz`` עם ``Content-Length`` מזויף ענה 413. שני
   החצאים מקובעים בטסט על האפליקציה האמיתית, בשני מצבי האימות.

**הסירוב נוקב בסיבתו** — כמו ``path_too_long`` ו-``too_many_sections``: ‏413 עם
``{"error": "body_too_large", "max_bytes": ...}`` ו-408 עם ``{"error":
"body_read_timeout", "read_timeout_seconds": ..., "received_bytes": ...}``, באותה
צורה של ה-401 ב-``auth.py``; וקריאת כלי שנחסמה מחזירה ``{"ok": false, "error":
"rate_limited", "limit_per_minute": ..., "retry_after_seconds": ...}`` — תשובת
כלי רגילה, כי זה מה שהסוכן קורא, ועם הזמן שנותר עד שהחלון משתחרר במקום "נסה
שוב".

**המספרים, ומאיפה.** ראו ליד הקבועים. תקרת הגוף **נגזרת** מ-``MAX_CODE_SIZE``
(:func:`request_bytes_for`) ואינה מוקלדת לצידו, והקצב ניתן לכיוון במשתנה
סביבה; שניהם נקראים ב-``create_app`` (בכניסה לשירות, לא בזמן ייבוא), דרך
:func:`limit_from_env`, שלעולם אינו הופך ערך פגום לגבול רחב יותר מברירת המחדל.
"""

from __future__ import annotations

import logging
import math
import os
import re
import time
from typing import Any, Awaitable, Callable

# anyio הוא תלות ישירה של mcp (``anyio>=4.5``) ושל starlette, ומיובא כאן ישירות
# בדיוק כמו ש-starlette עצמו מיובא — בלי נעיצה נפרדת בדרישות.
import anyio
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from rate_limiter import RateLimiter

from .handlers import DEFAULT_MAX_CODE_SIZE

logger = logging.getLogger(__name__)

#: כמה בתים תו אחד של ``code`` יכול לעלות על החוט. לקוח שמקודד JSON עם
#: ``ensure_ascii`` — ברירת המחדל של ``json.dumps`` — כותב כל תו שאינו ASCII
#: כ-``\\uXXXX``: שישה בתים. עברית היא המקרה הרגיל כאן, וכולה מחוץ ל-ASCII.
JSON_BYTES_PER_CHAR = 6

#: כל מה שבבקשת ``tools/call`` אינו ``code``: מעטפת ה-JSON-RPC, שם הכלי, ושאר
#: הארגומנטים של ``codekeeper_save_file`` — שם הקובץ (בלי תקרה בשכבה הזאת),
#: שפה, ותיאור שחסום ב-``FILE_DESCRIPTION_MAX_CHARS`` (500 תווים, כלומר 3,000
#: בתים בקידוד היקר). ‏64KiB הם סדר גודל מעל כל זה, וטסט בונה את הבקשה הגדולה
#: ביותר ומודד שהיא נכנסת.
REQUEST_ENVELOPE_BYTES = 65_536

_MIB = 1024 * 1024


def request_bytes_for(max_code_chars: int) -> int:
    """תקרת הגוף שמכילה את הבקשה הלגיטימית הגדולה ביותר לתקרת קוד נתונה.

    הבקשה הגדולה ביותר היא ``codekeeper_save_file`` על קובץ בגודל ``MAX_CODE_SIZE``
    (תווים, לא בתים — ``mcp_server/handlers.py::max_code_size``), ולכן:
    ``MAX_CODE_SIZE × JSON_BYTES_PER_CHAR + REQUEST_ENVELOPE_BYTES``, מעוגל כלפי
    מעלה ל-MiB שלם. העיגול הוא כדי שהמספר יישאר מוכר ויציב מול שינוי קטן
    במרכיבים — תקרה היא תקרה, לא התאמה מדויקת. על ברירת המחדל של התצורה
    (100,000 תווים) זה 1MiB; ‏``tests/test_mcp_limits.py`` מצמיד את הגזירה.
    """
    needed = int(max_code_chars) * JSON_BYTES_PER_CHAR + REQUEST_ENVELOPE_BYTES
    return -(-needed // _MIB) * _MIB


#: תקרת גוף הבקשה בבתים על ברירת המחדל של ``MAX_CODE_SIZE`` — 1MiB. הערך
#: שהשירות באמת מריץ נגזר ב-``create_app`` מהתצורה בפועל (``max_code_size()``),
#: וזה כאן הוא ברירת המחדל של ``build_app`` ושל המידלוור, והמספר שהתיעוד מציג.
DEFAULT_MAX_REQUEST_BYTES = request_bytes_for(DEFAULT_MAX_CODE_SIZE)

#: הרצפה לערך ממשתנה הסביבה: תקרה של עשרה בתים היא הפסקת שירות, לא הקשחה —
#: הודעת ``initialize`` לבדה היא כמה מאות בתים.
MIN_MAX_REQUEST_BYTES = 65_536

#: המתודות שנושאות גוף — ולכן היחידות שהתקרה בודקת. הערך ב-scope הוא כפי
#: שהשרת נותן אותו ("The HTTP method name, uppercased" — מפרט ASGI), ומושווה
#: כמות שהוא, בדיוק כמו ש-Starlette מנתב לפיו. ``PUT`` ו-``PATCH`` אינם בשימוש
#: כאן היום, אבל הם המחלקה: route חדש שיקרא גוף באחת מהן מכוסה בלי לגעת בשער.
METHODS_WITH_BODY = frozenset({"POST", "PUT", "PATCH"})

#: כמה זמן הלולאה שקוראת גוף **בלי אורך מוצהר** מוכנה להמתין לו כולו. המסלול
#: הזה רץ רק ללקוח שאינו מצהיר ``Content-Length`` — לקוח MCP רגיל מצהיר, כי הוא
#: שולח הודעת JSON שלמה (httpx, שלקוח ה-SDK בנוי עליו, מוסיף ``Content-Length``
#: לכל גוף בתים: ``httpx/_content.py::encode_content``). ‏30 שניות לגוף של עד
#: 1MiB הן כ-35KB/s — מתחת לכל קו שלקוח כזה רץ עליו. מחיר טעות לכל כיוון: קצר
#: מדי — 408 שלקוח יכול לנסות שוב עם אורך מוצהר; ארוך מדי — קורוטינה (לא חוט)
#: שמחזיקה חיץ עד התקרה למשך הדדליין, לכל חיבור אנונימי שטורח.
DEFAULT_BODY_READ_SECONDS = 30.0

#: קריאות כלים לזהות אחת בדקה. נגזר מהמדידות בתגובה ב-#3431 (2026-09-20):
#: הבקשה הציבורית היקרה ביותר היום היא עמוד RST של 500KB — ‏0.24 שניות מעבד
#: עם תקרת הסקשנים (0.035 לעמוד הצפוף האמיתי); במסלול ה-Markdown (#3428)
#: המסמך הצפוף האמיתי עולה 0.47 שניות והצורה העוינת 2.3; המכסה היא 0.5 מעבד,
#: כלומר 30 שניות-מעבד בדקה. שישים קריאות של המסמך הצפוף האמיתי הן 28 שניות —
#: זהות אחת יכולה לכל היותר למלא דקת מעבד אחת משלה, ולא יותר; קריאה רגילה
#: (10–50ms) הופכת 60 בדקה לאחוז עד שלושה מהמכסה. ומול מאגר של 10 חוטים,
#: 60 בדקה הן קריאה אחת בשנייה לזהות — הוגנות, לא חנק.
#:
#: **וגם צד הכתיבה (סקירת שבעת ה-PRים, SUGG-005):** אותן 60 בדקה לזהות עומדות
#: גם מול מאגר הכתיבה של עובד אחד (``mcp_server/server.py::_WRITE_POOL``).
#: המגביל אינו ההגנה על תור כתיבה שאינו מתרוקן — זו ה-WARNING של
#: ``_SLOW_WRITE_QUEUE_WAIT`` — ובמספרים של היום התור מתרוקן הרבה מעל 60 בדקה:
#: בלוגי השירות בפרנקפורט (``srv-dal7o0u1egvs73eqp0pg``, מאז 2026-09-16, נקראו
#: 2026-09-21) 30 שורות ``mcp write``, ‏``queued 0.000s`` בכולן פרט לאחת (0.003s),
#: ו-``ran`` בין 0.012 ל-1.993 שניות. המספרים הישנים על גוף כתיבה (7.5 שניות
#: ב-p95, ‏4.3–4.9 ב-p50) נמדדו לפני המעבר לפרנקפורט והתיישנו.
DEFAULT_RATE_LIMIT_PER_MINUTE = 60

MAX_REQUEST_BYTES_ENV = "MCP_MAX_REQUEST_BYTES"
RATE_LIMIT_ENV = "MCP_RATE_LIMIT_PER_MINUTE"

BODY_TOO_LARGE = "body_too_large"
BODY_READ_TIMEOUT = "body_read_timeout"
RATE_LIMITED = "rate_limited"

# מה ש-h11 מקבל כאורך: ``_content_length_re = re.compile(rb"[0-9]+")``
# (``h11/_headers.py``). ‏``str.isdigit()`` היה מקבל גם ``²`` ונופל על ``int()``.
_CONTENT_LENGTH = re.compile(r"[0-9]+")


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
    מאחורי ``Request``. ראו את ה-docstring של המודול על מה נקרא כאן ומה לא,
    ועל למה חיץ ולא חריגה.

    ``read_timeout`` — הדדליין, בשניות, על קריאת גוף בלי אורך מוצהר; פרמטר כדי
    שטסט יוכל להקטין אותו במקום להמתין לו.
    """

    def __init__(
        self,
        app: Any,
        *,
        max_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
        read_timeout: float = DEFAULT_BODY_READ_SECONDS,
    ) -> None:
        self.app = app
        self.max_bytes = int(max_bytes)
        self.read_timeout = float(read_timeout)

    async def __call__(self, scope: dict, receive: Callable[[], Awaitable[dict]], send: Any) -> None:
        if scope.get("type") != "http" or scope.get("method") not in METHODS_WITH_BODY:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        declared = _declared_length(headers)
        if declared is not None:
            if declared > self.max_bytes:
                await self._refuse(
                    scope, receive, send,
                    status=413, reason=BODY_TOO_LARGE, max_bytes=self.max_bytes, content_length=declared,
                )
                return
            if headers.get("transfer-encoding") is None:
                # השרת תוחם את הגוף לאורך המוצהר — אין מה לקרוא כאן (ראו את
                # ה-docstring של המודול, "אורך מוצהר תקין עובר בלי קריאה").
                await self.app(scope, receive, send)
                return

        buffered: list[dict] = []
        received = 0
        over_cap = False
        try:
            with anyio.fail_after(self.read_timeout):
                while True:
                    message = await receive()
                    buffered.append(message)
                    if message.get("type") != "http.request":
                        break  # ``http.disconnect`` — משודר הלאה כמות שהוא
                    received += len(message.get("body", b""))
                    if received > self.max_bytes:
                        over_cap = True
                        break
                    if not message.get("more_body", False):
                        break
        except TimeoutError:
            # ``anyio.fail_after`` מרים ``TimeoutError`` (``anyio/_core/_tasks.py``,
            # anyio 4.15.1) אחרי שביטל את ההמתנה ל-``receive``.
            await self._refuse(
                scope, receive, send,
                status=408, reason=BODY_READ_TIMEOUT,
                read_timeout_seconds=self.read_timeout, received_bytes=received,
            )
            return
        if over_cap:
            await self._refuse(
                scope, receive, send,
                status=413, reason=BODY_TOO_LARGE, max_bytes=self.max_bytes, received_bytes=received,
            )
            return

        async def replay() -> dict:
            if buffered:
                return buffered.pop(0)
            return await receive()

        await self.app(scope, replay, send)

    async def _refuse(
        self, scope: dict, receive: Any, send: Any, *, status: int, reason: str, **detail: int | float
    ) -> None:
        # גודל, זמן ונתיב בלבד — לא הגוף ולא הטוקן (K13).
        logger.warning(
            "mcp request refused: %s (%s) on %s",
            reason,
            ", ".join(f"{k}={v}" for k, v in detail.items()),
            scope.get("path"),
        )
        # ``Connection: close`` — הסירוב הגיע לפני שהגוף נגמר; ראו את ה-docstring
        # של המודול, "סירוב סוגר את החיבור".
        response = JSONResponse({"error": reason, **detail}, status_code=status, headers={"connection": "close"})
        await response(scope, receive, send)


def _declared_length(headers: Headers) -> int | None:
    """‏``Content-Length`` כמספר — ורק כשהוא ספרות ASCII, כמו ש-h11 מקבל אותו (U3).

    כל צורה אחרת אינה אורך מוצהר: מול uvicorn היא נדחתה ב-400 עוד לפני ה-ASGI,
    ומול שרת אחר סופרים את מה שבאמת מגיע.
    """
    value = headers.get("content-length")
    if value is None or _CONTENT_LENGTH.fullmatch(value) is None:
        return None
    return int(value)


class ToolRateLimiter:
    """הגבלת קצב לפי זהות על קריאות כלים, מעל ``rate_limiter.RateLimiter`` הקיים.

    אותו מגביל שהבוט משתמש בו (R6: לא עותק שני של חלון מתגלגל) — בזיכרון,
    ללא Redis, וזה מספיק כי שירות ה-MCP רץ במופע אחד. **המופע היחיד הוא הגדרה
    של השירות ב-Render, מחוץ לריפו** (``numInstances: 1``; נבדק מול ה-API של
    Render ב-2026-09-21) — ``docs/mcp-server.rst`` מתאר זאת ואינו המקור. מי
    שמוסיף מופע מאבד את הזיכרון המשותף, וזה המקום להתחיל ממנו. ‏``per_minute == 0``
    פירושו כבוי במפורש.
    """

    def __init__(self, per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE) -> None:
        self.per_minute = int(per_minute)
        self._limiter = RateLimiter(max_per_minute=self.per_minute) if self.per_minute > 0 else None
        self._warned_at: dict[int, float] = {}

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
        # הפנקס החזיק חותמת לכל זהות שסורבה אי פעם (SUGG-011); חותמות שחלונן
        # עבר יורדות במעבר שממילא כותב חותמת חדשה — בלי מעבר נוסף על המסלול החם.
        self._warned_at = {uid: at for uid, at in self._warned_at.items() if now - at < 60.0}
        self._warned_at[user_id] = now
        logger.warning(
            "mcp tool rate limit: identity %s exceeded %d calls/min; refused for the next %.0fs",
            user_id,
            self.per_minute,
            retry_after,
        )
