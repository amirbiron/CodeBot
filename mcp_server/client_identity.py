"""מי הלקוח המחובר — השם שהלקוח הצהיר עליו ב-``initialize`` (``clientInfo.name``).

זה החלק של "מי כתב" שמגיע **מהשרת ולא מהסוכן** (האפיון של שרשורי התגובות): השם שמופיע
בלוח האנליטיקס כ-``$mcp_client_name`` — ``claude-code``, ``Anthropic/ClaudeAI``, ``Gemini``.
סוכן אינו יכול לבחור אותו בפרמטר של כלי, ולכן אינו יכול להציג את עצמו כסוכן אחר.

**שני מקורות, לפי מה שהחיבור נושא — לא חלופה לכשל.**

1. ``ctx.request_context.session.client_params.clientInfo.name`` — ה-``initialize`` של אותו
   session. קיים כשה-session חי בין בקשות: חיבור בזיכרון (הטסטים), או שרת עם מצב.
   (``ServerSession.client_params`` ב-``mcp/server/session.py``, mcp 1.28.1.)
2. **השרת הזה רץ ``stateless_http=True``**: כל בקשה פותחת session חדש
   (``StreamableHTTPSessionManager._handle_stateless_request``, mcp 1.28.1), ולכן ב-
   ``tools/call`` ``client_params`` הוא ``None`` — ה-``initialize`` נשלח בבקשה אחרת. מה
   שעובר בין הבקשות הוא הכותרת ``Mcp-Session-Id``: ``PostHogMcpStatelessSessionMiddleware``
   מטביע בה ב-``initialize`` טוקן שנושא את שם הלקוח, הלקוח שולח אותה בכל בקשה, והמידלוור
   מפענח אותה אל ה-scope של הבקשה. ``posthog.mcp.get_mcp_session(request)`` הוא הקורא
   הציבורי של מה שפוענח (``posthog/mcp/asgi.py``, posthog 7.45.3) — אותו מקור שממנו
   PostHog עצמו ממלא ``$mcp_client_name`` בשרת stateless
   (``resolve_session_and_client`` ב-``posthog/mcp/_instrumentation.py``).

**התלות ב-PostHog אמיתית ונאמרת כאן:** המידלוור מותקן רק כש-``instrument()`` רץ, כלומר
רק כש-PostHog מוגדר (``analytics.instrument_mcp_server``). בלי PostHog, ובלקוח שאינו שולח
את הכותרת, השם אינו ידוע: התגובה נשמרת עם ``client: null`` ומוצגת "סוכן", ושורת ``WARNING``
אומרת זאת — כדי ש"אין שם" לא ייראה כמו לקוח שאין לו שם.

הטוקן אינו חתום (``posthog/mcp/session_token.py``: "it holds only what the client already
self-reports"), וזה גם מעמדו של ``clientInfo.name`` עצמו: מה שהלקוח מצהיר. ההבדל שחשוב
כאן הוא בין **הלקוח** (התוכנה שמתחברת) לבין **המודל** שממלא פרמטרים של כלי — והמודל אינו
שולט בכותרות HTTP.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _request_context(ctx: Any) -> Any:
    """ה-``RequestContext`` של הקריאה, או ``None`` מחוץ לבקשה.

    ``Context.request_context`` זורק ``ValueError("Context is not available outside of a
    request")`` כשאין בקשה (``mcp/server/fastmcp/server.py``, mcp 1.28.1) — מצב של קריאה
    ישירה לגוף הכלי, לא כשל של בקשה.
    """
    if ctx is None:
        return None
    try:
        return ctx.request_context
    except ValueError:
        return None


def connected_client_name(ctx: Any) -> str | None:
    """שם הלקוח המחובר, או ``None`` כשהחיבור אינו נושא אותו (ראו את ה-docstring של המודול).

    הסדר הוא לפי מה שקיים בחיבור, ולא ניסיון אחרי כשל: חיבור עם ``client_params`` נושא את
    ה-``initialize`` שלו; חיבור stateless נושא את הטוקן. השם חוזר כמו שהוא — הנרמול לשמירה
    הוא ``note_threads.normalize_client_name``.
    """
    context = _request_context(ctx)
    session = getattr(context, "session", None)
    params = getattr(session, "client_params", None)
    info = getattr(params, "clientInfo", None)
    name = getattr(info, "name", None)
    if isinstance(name, str) and name.strip():
        return name

    request = getattr(context, "request", None)
    if request is not None:
        from posthog.mcp import get_mcp_session

        token = get_mcp_session(request)
        token_name = getattr(token, "client_name", None)
        if isinstance(token_name, str) and token_name.strip():
            return token_name

    logger.warning(
        "connected client name unknown: no clientInfo on the session and no session token on "
        "the request (has_request=%s) — the comment is saved with client=null",
        request is not None,
    )
    return None
