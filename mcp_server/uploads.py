"""``PUT /api/agent/upload`` — העלאת תוכן ארוך בלי לעבור דרך המודל.

סוכן שכבר מחזיק את התוכן כקובץ מקומי (דוח, ניתוח, handoff) היה קורא את כולו
להקשר וכותב את כולו שוב בתוך קריאת הכלי — משלם פעמיים על אותם בתים, ובמסמך
ארוך מסתכן בקיטוע או בסחיפה בהעתקה. כאן הבתים עולים בקריאת ``curl`` אחת, נשמרים
לזמן קצוב, והסוכן מעביר ל-``codekeeper_save_file`` / ``codekeeper_append_file``
רק את ``upload_id``. **הראוט רק מחזיק בתים**: הכתיבה לקבצים נשארת קריאת כלי,
ולכן מקבלת את תור הכתיבה, את ``require_write``, את מגבלת הקצב ואת PostHog.

האח התאום של ``agent_primer_route`` (``mcp_server/primer.py``), ומאותן סיבות:

* **אימות בגוף הראוט, בשני מצבי האימות.** במצב OAuth ה-SDK עוטף רק את ה-mount
  של ``/mcp``, וראוט שנרשם ידנית מוגש בלי אימות. במצב PAT הנתיב פטור מ-
  ``PATAuthMiddleware`` (``build_app``), כדי שה-401 יהיה של הראוט — עם
  ``Connection: close`` — ולא של המידלוור.
* **טוקן תקין, לא scope ``write``.** ה-PAT שבסביבת Claude Code מונפק כ-``read``
  ומשרת את הפריימר; דרישת ``write`` כאן הייתה מחייבת PAT של כתיבה במשתני הסביבה
  של כל סשן — נגיש לכל הוק, סוכן-משנה וסקריפט בקונטיינר, וממנו אפשר לשלוח
  ``tools/call`` ישר ל-``/mcp``. שום דבר לא מגיע לקבצים בלי ``save_file``, שדורש
  ``write`` מטוקן הקונקטור, ובלי שה-``user_id`` של ההעלאה שווה לזה של השומר.

**הסדר קבוע, וכל מה שאינו צריך את הגוף בא לפני קריאתו:** אימות ← מגבלת הקצב
(אותו מופע של הכלים) ← מכסת הממתינות ← מוכנות האחסון ← הגוף, תחת דדליין ← פענוח
← שמירה. **כל סירוב נושא ``Connection: close``:** נמדד על uvicorn 0.38.0 שאחרי
סירוב שנשלח לפני קריאת הגוף השרת ממשיך לקרוא ולזרוק את מה שהלקוח שולח, והחיבור
נשאר פתוח שניות; עם ``close`` הוא נסגר מיד (``mcp_server/limits.py``, "סירוב
סוגר את החיבור").

אוצר המילים הוא של תשובות HTTP של השירות — ``{"error": ...}`` בלי ``ok``, כמו
ה-401 של האימות ו-``body_too_large`` — וכל מילה שיש לה מקבילה בתשובות הכלים היא
אותה מילה (``rate_limited``, ``code_too_large``, ``body_read_timeout``).
"""

from __future__ import annotations

import functools
import logging
import math
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import anyio
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from mcp_uploads import MAX_PENDING_UPLOADS, UPLOAD_TTL_SECONDS, UploadStorageUnavailable

from .auth import authenticate_bearer, unauthorized
from .handlers import max_code_size
from .limits import BODY_READ_TIMEOUT, DEFAULT_BODY_READ_SECONDS, ToolRateLimiter

logger = logging.getLogger(__name__)

UPLOAD_PATH = "/api/agent/upload"

UPLOAD_STORAGE_UNAVAILABLE = "upload_storage_unavailable"
TOO_MANY_PENDING_UPLOADS = "too_many_pending_uploads"
EMPTY_UPLOAD = "empty_upload"
INVALID_UTF8 = "invalid_utf8"
#: אותה מילה של ``codekeeper_save_file``, כי זו אותה תקרה (``max_code_size()``).
CODE_TOO_LARGE = "code_too_large"

#: ה-host בפקודה שבתיאורי הכלים, כשכתובת השירות אינה ידועה.
PLACEHOLDER_HOST = "<mcp-host>"

_CLOSE = {"connection": "close"}


def _why_not_usable(public_url: str) -> str | None:
    """למה הכתובת לא תיכנס לפקודה — או ``None`` כשהיא תקינה.

    הסיבה, ולא הערך: היא זו שנרשמת בלוג, ומה שנדחה עלול להיות בדיוק סיסמה
    בכתובת (K13). ``port`` נקרא כאן כדי שפורט שבור ייפול כאן, ולא בפקודה שהסוכן
    מריץ — ``SplitResult.port`` זורק ``ValueError`` על פורט שאינו מספר או שמחוץ
    לטווח (``urllib/parse.py``, ``_NetlocResultMixinBase.port``).
    """
    try:
        parts = urlsplit(public_url)
        hostname = parts.hostname
        _ = parts.port
    except ValueError:
        return "not a valid URL"
    if parts.scheme not in {"http", "https"}:
        return "scheme is not http or https"
    if not hostname:
        return "no host"
    if "@" in parts.netloc:
        return "carries a user name or password"
    if parts.query or parts.fragment:
        return "carries a query or a fragment"
    return None


def upload_url_for(public_url: str | None) -> str:
    """כתובת ההעלאה לפקודה שבתיאורי הכלים — מ-``MCP_SERVER_URL`` כשהיא ידועה.

    הערך מגיע מהסביבה (U3), והוא נכנס לתיאור שכל לקוח מקבל ב-``tools/list``.
    לכן רק ``http``/``https`` עם host ופורט תקין, **בלי** שם משתמש או סיסמה
    בכתובת (K13), ובלי query או fragment. כל צורה אחרת — ה-host המדומה, ולא ניחוש.

    **כתובת שלא הוגדרה וכתובת שנדחתה אינן אותו מצב.** בלי ``MCP_SERVER_URL`` (מצב
    PAT מקומי) הכתובת פשוט לא ידועה — מצב סטטי ומוכר, בלי לוג. כתובת שהוגדרה
    ונדחתה היא תצורה שגויה, והפקודה בתיאור נשארת בלי host שאפשר להריץ; בלי WARNING
    היא הייתה נראית בדיוק כמו "לא הוגדר".
    """
    placeholder = f"https://{PLACEHOLDER_HOST}{UPLOAD_PATH}"
    if not isinstance(public_url, str) or not public_url:
        return placeholder
    reason = _why_not_usable(public_url)
    if reason is not None:
        logger.warning(
            "MCP_SERVER_URL not used for the upload command: %s — tool descriptions show %s instead",
            reason, PLACEHOLDER_HOST,
        )
        return placeholder
    # אותה הרכבה של ``consent_url`` ב-``mcp_server/app.py``: הבסיס, ואחריו הנתיב.
    return f"{public_url.rstrip('/')}{UPLOAD_PATH}"


def _refuse(status: int, body: dict[str, Any]) -> JSONResponse:
    return JSONResponse(body, status_code=status, headers=_CLOSE)


def agent_upload_route(
    backend: Any,
    *,
    token_store: Any = None,
    auth_provider: Any = None,
    rate_limiter: ToolRateLimiter,
    read_timeout: float = DEFAULT_BODY_READ_SECONDS,
) -> Route:
    """בונה את ה-``Route`` של ``PUT /api/agent/upload``.

    ``token_store``/``auth_provider`` — אותם מאמתים של טרנספורט ה-MCP, כמו
    בפריימר. ``rate_limiter`` — **המופע** של ``call_tool``, ולא מופע חדש: העלאה
    ושמירה הן שתי קריאות מאותה מכסה, ומגביל נפרד היה מכפיל את הקצב שמותר לזהות
    אחת. לכן הוא חובה ואין לו ברירת מחדל. ``read_timeout`` — פרמטר כדי שטסט
    יוכל להקטין אותו, כמו במידלוור.
    """

    async def endpoint(request: Request) -> Response:
        principal = await authenticate_bearer(
            request, token_store=token_store, auth_provider=auth_provider
        )
        if not principal:
            response = unauthorized("invalid_token")
            response.headers["connection"] = "close"
            return response
        user_id = int(principal["user_id"])

        # משקל 1: העלאה ושמירה הן שתי קריאות מהמכסה. ``admit`` כותב את ה-WARNING
        # (אחד לזהות לחלון) ומחשב את ``retry_after_seconds``.
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

        try:
            # **מעקה ולא נעילה**, כמו ``file_exists``: הספירה וההכנסה אינן
            # אטומיות, ושתי העלאות מקבילות של אותו משתמש יכולות לעבור שתיהן
            # מעל התקרה באחת. מה שהחסם שומר עליו — אחסון שאינו גדל בלי גבול —
            # נשמר גם אז, כי כל העלאה פוקעת.
            expiries = await anyio.to_thread.run_sync(
                functools.partial(backend.pending_upload_expiries, user_id, limit=MAX_PENDING_UPLOADS)
            )
            if len(expiries) >= MAX_PENDING_UPLOADS:
                wait = (expiries[0] - datetime.now(timezone.utc)).total_seconds()
                return _refuse(
                    429,
                    {
                        "error": TOO_MANY_PENDING_UPLOADS,
                        "max": MAX_PENDING_UPLOADS,
                        "retry_after_seconds": max(1, math.ceil(wait)),
                    },
                )
            # בלי TTL מאומת, "חמש העלאות" הוא חסם על הנייר והתוכן נשאר לצמיתות.
            if not await anyio.to_thread.run_sync(backend.upload_storage_ready):
                return _refuse(503, {"error": UPLOAD_STORAGE_UNAVAILABLE})

            # הגוף נקרא רק עכשיו, ותחת דדליין משלו: גוף עם אורך מוצהר תקין עובר
            # את ``BodySizeLimitMiddleware`` בלי שנקרא (השרת תוחם אותו), ולכן אין
            # לו שום תקרת זמן מלבד זו. ``DEFAULT_BODY_READ_SECONDS`` — אותו מספר
            # של המידלוור, ואותה תשובה.
            chunks: list[bytes] = []
            received = 0
            try:
                with anyio.fail_after(read_timeout):
                    async for chunk in request.stream():
                        chunks.append(chunk)
                        received += len(chunk)
            except TimeoutError:
                # ``anyio.fail_after`` מרים ``TimeoutError`` (``anyio/_core/_tasks.py``).
                return _refuse(
                    408,
                    {
                        "error": BODY_READ_TIMEOUT,
                        "read_timeout_seconds": read_timeout,
                        "received_bytes": received,
                    },
                )
            raw = b"".join(chunks)

            # **הגוף הוא בתים, ותו לא** — ``Content-Type`` אינו נקרא ואינו נדרש.
            if not raw:
                return _refuse(400, {"error": EMPTY_UPLOAD})
            try:
                # ``utf-8`` ולא ``utf-8-sig``: BOM נשאר תו, כמו שהוא נשאר ב-``code``.
                # התוכן נשמר בדיוק כמו שנשלח (#3469) — שום נרמול.
                text = raw.decode("utf-8")
            except UnicodeDecodeError:
                return _refuse(400, {"error": INVALID_UTF8})
            limit = max_code_size()
            if len(text) > limit:
                return _refuse(413, {"error": CODE_TOO_LARGE, "max": limit})

            # לא דרך תור הכתיבה: זו אינה כתיבה לקובץ של משתמש, ואין לה סדר לשמור.
            stored = await anyio.to_thread.run_sync(
                functools.partial(backend.create_upload, user_id, text=text, size_bytes=len(raw))
            )
        except UploadStorageUnavailable:
            # נרשם ב-backend, עם הסיבה; כאן רק התשובה.
            return _refuse(503, {"error": UPLOAD_STORAGE_UNAVAILABLE})
        except ClientDisconnect:
            # הלקוח עזב באמצע הגוף. אין מי שיקרא תשובה — uvicorn מתעלם משליחה
            # אחרי ניתוק (``protocols/http/h11_impl.py``, ``send``) — והסגירה
            # מבטיחה שהחיבור לא ימוחזר גם בשרת שכן שולח.
            return Response(status_code=400, headers=_CLOSE)

        return JSONResponse(
            {
                "upload_id": stored["upload_id"],
                "bytes": len(raw),
                "chars": len(text),
                "content_sha256": stored["content_sha256"],
                "expires_in_seconds": UPLOAD_TTL_SECONDS,
            },
            status_code=201,
        )

    return Route(UPLOAD_PATH, endpoint, methods=["PUT"])
