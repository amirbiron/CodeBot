"""``GET /api/agent/download`` — הורדת קובץ שמור לדיסק של הסוכן בלי לעבור דרך המודל.

המראה של ``PUT /api/agent/upload`` (``mcp_server/uploads.py``). סוכן שצריך להריץ
בקונטיינר סקריפט ששמור ב-CodeKeeper היה קורא אותו ב-``codekeeper_get_file`` ומעתיק
את כל התוכן לכלי הכתיבה שלו: משלם פעמיים על אותם בתים, ופותח פתח לשגיאת העתקה
שרק השוואת hash תופסת. כאן הבתים יורדים בקריאת ``curl`` אחת, ישר לקובץ.

**לא קישור חתום, מאותו נימוק של ההעלאה (#3502).** ה-PAT שכבר בסביבה מאמת את הבקשה
עצמה: אין מה להטביע, אין סוד בכתובת, ואין אחסון זמני. וכאן גם ה-scope אינו שאלה:
הורדה היא קריאה, וטוקן ``read`` — זה שמשרת את הפריימר — מספיק.

**אותה בנייה של התאומים** (``agent_primer_route``, ``agent_upload_route``) ואותו סדר:
אימות (``authenticate_bearer``, טוקן תקין בכל scope) ← מגבלת הקצב (**אותו מופע** של
``call_tool``, משקל 1: הורדה היא קריאת כלי אחת מתוך המכסה) ← צורת הבקשה ← השליפה ←
התשובה. אין גוף בבקשה, ולכן אין דדליין לגוף. במצב PAT הנתיב פטור מ-``PATAuthMiddleware``
(``build_app``), כדי שה-401 יהיה של הראוט — עם ``Connection: close`` ו-``no-store``.

**הזיהוי הוא של ``codekeeper_get_file``, דרך אותה שליפה** — ``handlers.get_file``, הפונקציה
שהכלי קורא לה: ``file_id`` של גרסה, או ``file_name`` ו-``version`` אופציונלי, לפי ה-
``user_id`` של הטוקן. ``ProductionBackend.get_file`` מאתר לפי ``file_id`` בלי ``user_id``
בשאילתה ובודק את הבעלות על המסמך שחזר; לפי שם, ``user_id`` הוא חלק מהשאילתה. מזהה
של משתמש אחר, מזהה שאינו קיים ומזהה פגום — 404 אחד לשלושתם (``not_found``), כמו
``found: false`` של הכלי. **השליפה רצה ב-``asyncio.to_thread``**, כמו גוף הכלי
(``_offload_to_thread`` ב-``server.py``): במאגר הקריאה שגודלו נגזר ממכסת הזיכרון
(``attach_read_pool``), ולא במאגר החוטים של anyio, שאינו נספר שם.

**הגוף הוא ``code.encode("utf-8")`` ותו לא.** BOM, CRLF וירידת שורה בסוף נשארים —
אותו טקסט שנשמר בדיוק כמו שנשלח (#3469). ``X-Content-SHA256`` הוא ``content_sha256``
ש-``_full`` (``mcp_server/backend.py``) מחשב — אותו ערך של ``file.content_sha256`` בתשובת
הכלי, ובהגדרה ה-hash של הבתים שנשלחו. ``X-File-Version`` — מספר הגרסה שירדה. שם
הקובץ אינו בכותרת: הסוכן בחר את שם היעד ב-``-o``, ושם בעברית אינו נכנס לכותרת HTTP
בלי קידוד.

**אין תקרה חדשה.** קובץ שמור חסום ב-``max_code_size()`` כבר בשמירה, ומוחזר שלם.
``large_files`` מחוץ להישג, כמו בכל ה-MCP. **קבצים מהמראות** (``repo``/``path``/``ref``)
**אינם כאן**: שער האדמין, מדיניות הסודות, ``ref`` ו-``sync_in_progress`` הם מחלקת סיכון
אחרת, ולכן שינוי נפרד — ועד אז ``repo`` הוא פרמטר לא מוכר, כמו כל שם אחר.

**HEAD.** Starlette מוסיף ``HEAD`` לכל ראוט ``GET`` (``Route.__init__``,
``starlette/routing.py``), ו-uvicorn שולח לה את הכותרות בלי הגוף (``h11_impl.py``,
``send``). כלומר ``HEAD`` עוברת את כל הראוט — אימות, מכסה ושליפה — ומחזירה את
``X-Content-SHA256`` בלי הבתים.

אוצר המילים הוא של תשובות HTTP של השירות — ``{"error": ...}`` בלי ``ok``, כמו ה-401
של האימות. **כל סירוב נושא ``Connection: close``**, כמו בהעלאה; שם הסיבה היא גוף
שהשרת היה ממשיך לקרוא (``mcp_server/limits.py``, "סירוב סוגר את החיבור"), וכאן אין
גוף — זה חוזה אחד לכל סירוב של ראוט, לא תיקון של בעיה של הראוט הזה. **כל תשובה
שהראוט בונה נושאת ``Cache-Control: no-store``,** גם הצלחה וגם סירוב: זה תוכן פרטי שעבר
אימות, ואין סיבה שמטמון בדרך ישמור אותו. (``405`` של Starlette על מתודה אחרת, ו-``500``
מחריגה שלא נתפסה, אינם נבנים כאן — ואינם נושאים תוכן.) (``no-store`` ולא ``no-cache``: האזהרה של
``stale-asset-cache-policy`` מפני ``no-store`` מכוונת לנכסים סטטיים שמרוויחים מ-
revalidation, ואין כאן נכס כזה.) שורת ``INFO`` אחת על כל הורדה — משתמש, מזהה ובתים,
בלי תוכן ובלי שם הקובץ; סירובים אינם נרשמים, ו-PostHog אינו רואה ראוטים.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from starlette.datastructures import QueryParams
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from . import handlers
from .auth import authenticate_bearer, unauthorized
from .limits import ToolRateLimiter

logger = logging.getLogger(__name__)

DOWNLOAD_PATH = "/api/agent/download"

#: הפרמטרים שהראוט מקבל — פרמטרי הזיהוי של ``codekeeper_get_file``, ותו לא. הסדר
#: הוא הסדר שבו ``allowed`` מחזיר אותם.
PARAMETERS = ("file_id", "file_name", "version")

NOT_FOUND = "not_found"
MISSING_TARGET = "missing_target"
UNKNOWN_PARAMETER = "unknown_parameter"
REPEATED_PARAMETER = "repeated_parameter"
EMPTY_PARAMETER = "empty_parameter"
AMBIGUOUS_TARGET = "ambiguous_target"
INVALID_VERSION = "invalid_version"

#: ``version`` בשורת השאילתה: ספרות ASCII בלבד, כמו ``_CONTENT_LENGTH`` ב-``limits.py``
#: (``str.isdigit()`` היה מקבל ``²`` ונופל ב-``int()``), ועד תשע ספרות. בלי התקרה
#: ``int()`` על יותר מ-``sys.int_info.default_max_str_digits`` ספרות (4300 ב-CPython
#: 3.13) זורק ``ValueError``, כלומר 500 במקום 400; ותשע ספרות הן הרבה מעל כל גרסה.
_VERSION = re.compile(r"[0-9]{1,9}")

_NO_STORE = {"cache-control": "no-store"}
_REFUSAL_HEADERS = {**_NO_STORE, "connection": "close"}

#: סוג התוכן של הגוף. ``charset`` מפורש — Starlette מוסיף אותו בעצמו רק כשאינו
#: כתוב (``Response.init_headers``), והתוכן הוא בדיוק בתי ה-UTF-8 של ``code``.
_MEDIA_TYPE = "text/plain; charset=utf-8"


def _refuse(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=_REFUSAL_HEADERS)


def download_target(params: QueryParams) -> dict[str, Any] | tuple[int, dict[str, Any]]:
    """הארגומנטים של ``handlers.get_file`` מתוך שורת השאילתה — או ``(status, body)`` של סירוב.

    שורת השאילתה היא קלט חיצוני (U3). Starlette מפרק אותה ב-``parse_qsl`` עם
    ``keep_blank_values=True`` (``QueryParams`` ב-``starlette/datastructures.py``),
    ולכן כל ערך הוא מחרוזת, ערך ריק נשמר, ומפתח שחוזר מופיע ב-``multi_items()``
    בכל מופעיו. גודל השורה כולה חסום בשרת לפני שהיא מגיעה לכאן: בלי ``httptools``
    בדרישות uvicorn רץ על h11, ששורת הבקשה והכותרות שלו חסומות יחד ב-
    ``DEFAULT_MAX_INCOMPLETE_EVENT_SIZE`` (16KiB ב-h11 0.16.0).

    **סירוב ולא התעלמות.** הכלי מתעלם בשקט מ-``version`` לצד ``file_id`` (התיאור שלו
    אומר זאת), ו-``request.query_params[...]`` היה בוחר בשקט אחד משני ערכים של אותו
    מפתח ומתעלם משם שגוי לגמרי. כאן כל אחד מהם הוא 400 עם קוד משלו: ``verison=3``
    שהיה נבלע היה מחזיר בשקט את הגרסה האחרונה — קובץ אחר ממה שהתבקש, עם 200.

    ``parameter`` בסירוב נוקב בשם מתוך :data:`PARAMETERS` בלבד, ולכן אינו מהדהד קלט;
    ``unknown_parameter`` אינו מחזיר את השם שנשלח, אלא את הרשימה של מה שמותר.
    """
    seen: dict[str, str] = {}
    for key, value in params.multi_items():
        if key not in PARAMETERS:
            return 400, {"error": UNKNOWN_PARAMETER, "allowed": list(PARAMETERS)}
        if key in seen:
            return 400, {"error": REPEATED_PARAMETER, "parameter": key}
        if value == "":
            return 400, {"error": EMPTY_PARAMETER, "parameter": key}
        seen[key] = value
    if "file_id" in seen:
        if "file_name" in seen or "version" in seen:
            return 400, {"error": AMBIGUOUS_TARGET}
        return {"file_id": seen["file_id"]}
    if "file_name" not in seen:
        return 400, {"error": MISSING_TARGET}
    target: dict[str, Any] = {"file_name": seen["file_name"]}
    if "version" in seen:
        if _VERSION.fullmatch(seen["version"]) is None:
            return 400, {"error": INVALID_VERSION}
        target["version"] = int(seen["version"])
    return target


def _load(backend: Any, user_id: int, target: dict[str, Any]) -> tuple[bytes, dict[str, Any]] | None:
    """השליפה והקידוד, על חוט העבודה: ``(הבתים, הקובץ)`` או ``None`` כשאין קובץ כזה של המשתמש.

    ``handlers.get_file`` בלי אף מצב קריאה מחזיר את ``_full(doc)`` — ``code`` כמחרוזת
    (``_full`` זורק ``TypeError`` כשהוא אינו מחרוזת, וזה עולה כ-500: חוזה שנשבר, לא
    "לא נמצא") ו-``content_sha256`` שלו — או ``None``. הקידוד כאן ולא על הלולאה: הוא
    עובר על כל הקובץ.
    """
    doc = handlers.get_file(backend, user_id, **target)
    if not doc:
        return None
    return doc["code"].encode("utf-8"), doc


def agent_download_route(
    backend: Any,
    *,
    token_store: Any = None,
    auth_provider: Any = None,
    rate_limiter: ToolRateLimiter,
) -> Route:
    """בונה את ה-``Route`` של ``GET /api/agent/download``.

    ``token_store``/``auth_provider`` — אותם מאמתים של טרנספורט ה-MCP, כמו בתאומים.
    ``rate_limiter`` — **המופע** של ``call_tool``, ולא מופע חדש: הורדה וקריאת כלי הן
    שתי קריאות מאותה מכסה, ומגביל נפרד היה מכפיל את הקצב שמותר לזהות אחת. לכן הוא
    חובה ואין לו ברירת מחדל.
    """

    async def endpoint(request: Request) -> Response:
        principal = await authenticate_bearer(
            request, token_store=token_store, auth_provider=auth_provider
        )
        if not principal:
            response = unauthorized("invalid_token")
            response.headers.update(_REFUSAL_HEADERS)
            return response
        user_id = int(principal["user_id"])

        # משקל 1. ``admit`` כותב את ה-WARNING (אחד לזהות לחלון) ומחשב את ``retry_after_seconds``.
        refusal = await rate_limiter.admit(user_id)
        if refusal is not None:
            return _refuse(
                429,
                {
                    "error": refusal["error"],
                    "limit_per_minute": refusal["limit_per_minute"],
                    "retry_after_seconds": refusal["retry_after_seconds"],
                },
            )

        target = download_target(request.query_params)
        if isinstance(target, tuple):
            return _refuse(*target)

        loaded = await asyncio.to_thread(_load, backend, user_id, target)
        if loaded is None:
            return _refuse(404, {"error": NOT_FOUND})
        body, doc = loaded

        headers = {**_NO_STORE, "x-content-sha256": doc["content_sha256"]}
        version = doc.get("version")
        # מספר שלם בלבד: כל כותבי ``code_snippets`` כותבים ``version`` מספרי, וערך מצורה
        # אחרת אינו מספר גרסה — עדיף כותרת חסרה על כותרת שאומרת משהו אחר.
        if isinstance(version, int) and not isinstance(version, bool):
            headers["x-file-version"] = str(version)
        # בלי התוכן ובלי שם הקובץ: המזהה הוא של הגרסה, והבתים — כמה ירדו.
        logger.info(
            "mcp download: %d bytes of file %s (version %s) for user %s",
            len(body), doc.get("id"), version, user_id,
        )
        return Response(body, media_type=_MEDIA_TYPE, headers=headers)

    return Route(DOWNLOAD_PATH, endpoint, methods=["GET"])
