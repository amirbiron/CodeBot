"""גבולות הבקשה של שרת ה-MCP (#3431): תקרת גוף במידלוור, והגבלת קצב לפי זהות בנקודת השיגור.

שני הגבולות נבדקים בשכבה שבה הם חיים — המידלוור מול הודעות ASGI ממש, והמגביל
דרך ``call_tool`` של ה-``FastMCP`` האמיתי — ואז על האפליקציה המלאה דרך
``TestClient``, כי הפטור לנתיבי הדופק והסדר מול האימות הם תכונות של ההרכבה
ולא של אף רכיב לבדו. בלי ``sleep``: התקרה, החלון והדדליין מוקטנים במקום
להמתין להם.

**מה המידלוור קורא, ומה לא (SEC-001 בסקירת שבעת ה-PRים).** הגרסה הראשונה קראה
כל גוף עד התקרה לפני שהשכבה הבאה ראתה את הבקשה — גם גוף אנונימי שהאימות היה
דוחה מהכותרות בלבד, ובלי דדליין. הטסטים כאן מקבעים את שלושת החלקים של התיקון:
אורך מוצהר תקין עובר בלי קריאה (השרת תוחם), הלולאה שנשארה לגוף chunked נסגרת
בדדליין, ורק מתודות שנושאות גוף נבדקות בכלל.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import types as mcp_types  # noqa: E402
from mcp.server.fastmcp import Context  # noqa: E402
from mcp.server.lowlevel.server import request_ctx  # noqa: E402
from mcp.shared.context import RequestContext  # noqa: E402
from starlette.requests import ClientDisconnect, Request  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import mcp_server.server as srv  # noqa: E402
from mcp_server import handlers, limits  # noqa: E402
from mcp_server.limits import BodySizeLimitMiddleware, ToolRateLimiter, limit_from_env  # noqa: E402
from mcp_server.server import _READ_ONLY_TOOL, build_app, build_mcp  # noqa: E402
from rate_limiter import RateLimiter  # noqa: E402

try:  # local `tests` pkg can be shadowed by an unrelated top-level `tests` on sys.path
    from tests._fake_mongo import FakeDB  # noqa: E402
except ImportError:  # fall back to the sibling module (tests/ is on sys.path under pytest)
    from _fake_mongo import FakeDB  # noqa: E402

_REPO = Path(__file__).resolve().parent.parent


class _Backend:
    """המשטח הקטן ביותר שהכלי הנבדק נוגע בו: ``get_file`` שמחזיר "לא נמצא"."""

    def get_file(self, *args, **kwargs):
        return None


class _Store:
    def verify(self, token):
        return {"user_id": 7, "scopes": ["read"]} if token == "good" else None


# ---------------------------------------------------------------------------
# המידלוור, מול הודעות ASGI ממש
# ---------------------------------------------------------------------------


def _scope(path="/mcp", method="POST", headers=()):
    # ``method`` is uppercased by the server ("The HTTP method name, uppercased" —
    # ASGI HTTP connection scope), and the middleware compares it as given.
    return {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "headers": [(k.encode(), v.encode()) for k, v in headers],
        "query_string": b"",
        "server": ("test", 80),
        "client": ("127.0.0.1", 1),
        "scheme": "http",
    }


def _mcp_post(headers=()):
    """‏``POST /mcp`` כפי שלקוח MCP שולח אותו: JSON, ומקבל JSON או SSE."""
    return _scope(headers=[("content-type", "application/json"),
                           ("accept", "application/json, text/event-stream"), *headers])


def _chunks(sizes, byte=b"x"):
    sizes = list(sizes)
    return [{"type": "http.request", "body": byte * n, "more_body": i < len(sizes) - 1}
            for i, n in enumerate(sizes)]


class _Echo:
    """אפליקציה שקוראת את הגוף כמו הטרנספורט — דרך ``Request.body()`` — ורושמת מה ראתה."""

    def __init__(self):
        self.calls = 0
        self.seen = None

    async def __call__(self, scope, receive, send):
        self.calls += 1
        self.seen = await Request(scope, receive).body()
        await PlainTextResponse("ok")(scope, receive, send)


async def _drive(app, scope, messages):
    """מריץ את האפליקציה על רצף הודעות נתון; ``receive`` שנקרא מעבר לרצף מפיל את הטסט."""
    queue = list(messages)
    sent = []

    async def receive():
        assert queue, "receive() was called after the last message"
        return queue.pop(0)

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return sent


async def _drive_traced(app, scope, messages, mark=lambda: None):
    """כמו ``_drive``, ורושם לכל קריאת ``receive()`` כמה הודעות כבר נשלחו וערך סימון מהטסט.

    ``(0, ...)`` ברשומה פירושו קריאה **לפני** שהתשובה התחילה; ``mark()`` נותן
    לטסט לרשום מה שהוא רוצה — למשל אם האפליקציה כבר נכנסה.
    """
    queue = list(messages)
    sent = []
    trace = []

    async def receive():
        assert queue, "receive() was called after the last message"
        trace.append((len(sent), mark()))
        return queue.pop(0)

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    return sent, trace


def _status(sent):
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def _headers(sent):
    start = next(m for m in sent if m["type"] == "http.response.start")
    return {k.lower(): v for k, v in start.get("headers", [])}


def _json_body(sent):
    return json.loads(b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body"))


async def test_a_declared_length_over_the_cap_is_refused_before_a_byte_is_read():
    echo = _Echo()
    mw = BodySizeLimitMiddleware(echo, max_bytes=100)

    sent = await _drive(mw, _scope(headers=[("content-length", "101")]), messages=[])

    assert _status(sent) == 413
    assert _json_body(sent) == {"error": "body_too_large", "max_bytes": 100, "content_length": 101}
    assert echo.calls == 0
    assert _headers(sent)[b"connection"] == b"close", "the body was refused unread; the connection is not kept"


async def test_a_valid_declared_length_under_the_cap_is_handed_on_without_a_read():
    """SEC-001, חלק 1: ``Content-Length`` תקין ובלי ``Transfer-Encoding`` — המידלוור אינו קורא בית.

    השרת תוחם את הגוף לאורך המוצהר: מול uvicorn 0.38.0 (h11) אמיתי, 20 בתים
    מאחורי ``Content-Length: 10`` הגיעו לאפליקציה כ-10. לכן אין כאן מה לספור,
    ומי שעונה מהכותרות בלבד — ה-401 של האימות — עונה בלי שנקרא דבר. לפני
    התיקון הקריאה הראשונה קרתה לפני שהאפליקציה נכנסה (``echo.calls == 0``
    בזמן הקריאה); עכשיו הקריאה היחידה היא של האפליקציה עצמה.
    """
    echo = _Echo()
    mw = BodySizeLimitMiddleware(echo, max_bytes=100)

    sent, trace = await _drive_traced(mw, _scope(headers=[("content-length", "50")]),
                                      _chunks([50]), mark=lambda: echo.calls)

    assert _status(sent) == 200 and echo.seen == b"x" * 50
    assert [entered for _, entered in trace] == [1], "the only read belongs to the app, after it was entered"


async def test_a_declared_length_beside_transfer_encoding_is_not_trusted():
    """‏``Content-Length`` לצד ``Transfer-Encoding: chunked`` — סופרים, כמו בלי כותרת.

    h11 תוחם לפי chunked ומעביר את **שתי** הכותרות ל-scope (נמדד מול uvicorn
    0.38.0: 200 בתים מאחורי ``Content-Length: 5`` הגיעו במלואם). זו הכותרת
    המכזבת היחידה שמסוגלת להעביר יותר ממה שהצהירה, ולכן המסלול המהיר דורש
    שאין ``Transfer-Encoding``. הטסט עובר גם על הקוד שלפני התיקון; הוא מפיל
    מסלול מהיר שמסתכל על ``Content-Length`` בלבד.
    """
    echo = _Echo()
    mw = BodySizeLimitMiddleware(echo, max_bytes=100)

    sent = await _drive(mw, _scope(headers=[("content-length", "5"), ("transfer-encoding", "chunked")]),
                        _chunks([60, 60]))

    assert _status(sent) == 413
    assert _json_body(sent) == {"error": "body_too_large", "max_bytes": 100, "received_bytes": 120}
    assert echo.calls == 0


async def test_a_declared_length_that_is_not_ascii_digits_is_not_a_length():
    """‏``Content-Length: ²`` — ``str.isdigit()`` מקבל ספרות-על ו-``int()`` נופל עליהן (U3).

    h11 דוחה כותרת כזאת ב-400 לפני ה-ASGI (``[0-9]+`` בלבד), ולכן מול uvicorn
    זה לא מגיע לכאן; מול שרת אחר, או ב-``TestClient``, זה היה 500. ערך שאינו
    ספרות ASCII אינו אורך מוצהר: סופרים את מה שבאמת מגיע.
    """
    echo = _Echo()
    mw = BodySizeLimitMiddleware(echo, max_bytes=100)
    scope = _scope()
    # latin-1 on the wire, as ``Headers`` decodes it: ``b"\xb2"`` reads back as ``²``.
    scope["headers"] = [(b"content-length", b"\xb2")]

    sent = await _drive(mw, scope, _chunks([40]))

    assert _status(sent) == 200 and echo.seen == b"x" * 40


async def test_a_streamed_body_over_the_cap_is_refused_and_the_app_never_runs():
    """בלי ``Content-Length`` (גוף chunked) — הספירה של מה שבאמת מגיע היא שעוצרת.

    **הטענה השתנתה ב-SEC-001, בכוונה.** עד אז הטסט שלח ``Content-Length: 90``
    עם 120 בתים, ו"כותרת מכזבת" נתפסה בספירה. אורך מוצהר תקין (בלי
    ``Transfer-Encoding``) עובר עכשיו בלי קריאה, כי השרת תוחם את הגוף לאורך
    המוצהר ואי אפשר להעביר דרכו יותר (נמדד מול uvicorn/h11 בטסט המסלול
    המהיר). הכותרת המכזבת היחידה שמסוגלת להעביר יותר היא זו שלצד
    ``Transfer-Encoding``, ויש לה טסט משלה. מה שנשאר לספירה הוא גוף בלי אורך
    מוצהר — וזה מה שכאן.
    """
    echo = _Echo()
    mw = BodySizeLimitMiddleware(echo, max_bytes=100)

    sent = await _drive(mw, _scope(), _chunks([60, 60]))

    assert _status(sent) == 413
    assert _json_body(sent) == {"error": "body_too_large", "max_bytes": 100, "received_bytes": 120}
    assert echo.calls == 0


async def test_a_body_that_stops_arriving_is_refused_at_the_deadline_with_what_was_read():
    """SEC-001, חלק 2: גוף chunked אנונימי שנעצר באמצע נסגר ב-408, ולא מוחזק לנצח.

    ל-uvicorn 0.38.0 אין timeout לגוף בקשה (``timeout_keep_alive`` חל אחרי
    תשובה), ולכן בלי דדליין ההמתנה כאן אינה חסומה — וזה המקרה שנשאר אחרי
    המסלול המהיר: לקוח בלי ``Content-Length``, לפני האימות. הסירוב נוקב
    בסיבתו ובכמה נקרא, ונושא ``Connection: close`` — "since 408 implies that
    the server has decided to close the connection rather than continue
    waiting" (MDN, ‏``408 Request Timeout``). ``asyncio.wait_for`` הוא השומר של
    הטסט עצמו: על הקוד שלפני התיקון הוא זה שנופל.
    """
    echo = _Echo()
    mw = BodySizeLimitMiddleware(echo, max_bytes=100, read_timeout=0.05)
    queue = _chunks([40, 40])  # the second chunk never arrives
    sent = []

    async def receive():
        if len(queue) == 2:
            return queue.pop(0)
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    await asyncio.wait_for(mw(_scope(), receive, send), timeout=5)

    assert _status(sent) == 408
    assert _json_body(sent) == {"error": "body_read_timeout", "read_timeout_seconds": 0.05, "received_bytes": 40}
    assert _headers(sent)[b"connection"] == b"close"
    assert echo.calls == 0


async def test_the_deadline_bounds_the_whole_body_and_not_each_chunk():
    """דדליין על הלולאה כולה: לקוח ששולח בית כל 29 שניות היה עובר דדליין-לקריאה.

    כאן כל נתח מגיע הרבה לפני הדדליין, ויש יותר נתחים ממה שהדדליין מכיל —
    מימוש שמודד כל קריאה בנפרד היה ממשיך לקרוא עד התקרה.
    """
    mw = BodySizeLimitMiddleware(_Echo(), max_bytes=1000, read_timeout=0.1)
    sent = []

    async def receive():
        await asyncio.sleep(0.03)
        return {"type": "http.request", "body": b"x", "more_body": True}

    async def send(message):
        sent.append(message)

    await asyncio.wait_for(mw(_scope(), receive, send), timeout=5)

    assert _status(sent) == 408
    assert _json_body(sent)["received_bytes"] >= 2, "more than one chunk was read, each within the deadline"


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS", "DELETE"])
async def test_a_method_that_carries_no_body_is_neither_capped_nor_read(method):
    """SEC-001, חלק 3 (WARN-002): רק מתודות שנושאות גוף נבדקות.

    ‏``GET /healthz`` עם ``Content-Length: 99999999`` מזויף ענה 413 — נמדד מול
    uvicorn אמיתי — בניגוד ל"פטור מבני" שהתיעוד הצהיר. שום route כאן אינו
    קורא גוף במתודה אחרת: הטרנספורט של ה-SDK קורא ב-``POST``, ו-DCR, token
    ו-consent הם ``POST``. התקרה היא לכן תכונה של המתודות שנושאות גוף.
    """
    echo = _Echo()
    mw = BodySizeLimitMiddleware(echo, max_bytes=100)

    sent = await _drive(mw, _scope(method=method, headers=[("content-length", "99999999")]), _chunks([0]))

    assert _status(sent) == 200
    assert echo.calls == 1, "handed straight to the app; the empty body read is the app's own"


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH"])
async def test_a_method_that_carries_a_body_is_capped(method):
    sent = await _drive(BodySizeLimitMiddleware(_Echo(), max_bytes=100),
                        _scope(method=method, headers=[("content-length", "101")]), [])
    assert _status(sent) == 413


async def test_a_body_under_the_cap_reaches_the_app_intact():
    echo = _Echo()
    mw = BodySizeLimitMiddleware(echo, max_bytes=100)
    chunks = [
        {"type": "http.request", "body": b"a" * 40, "more_body": True},
        {"type": "http.request", "body": b"b" * 50, "more_body": False},
    ]

    sent = await _drive(mw, _scope(), chunks)

    assert _status(sent) == 200
    assert echo.calls == 1 and echo.seen == b"a" * 40 + b"b" * 50


async def test_exactly_the_cap_passes_and_one_more_byte_does_not():
    at_cap = _Echo()
    await _drive(BodySizeLimitMiddleware(at_cap, max_bytes=5), _scope(),
                 [{"type": "http.request", "body": b"12345", "more_body": False}])
    assert at_cap.seen == b"12345"

    over = _Echo()
    sent = await _drive(BodySizeLimitMiddleware(over, max_bytes=5), _scope(),
                        [{"type": "http.request", "body": b"123456", "more_body": False}])
    assert _status(sent) == 413 and over.calls == 0


async def test_a_disconnect_is_handed_on_to_the_app_unchanged():
    seen = {}

    async def app(scope, receive, send):
        with pytest.raises(ClientDisconnect):
            await Request(scope, receive).body()
        seen["disconnected"] = True

    await _drive(BodySizeLimitMiddleware(app, max_bytes=100), _scope(), [{"type": "http.disconnect"}])
    assert seen == {"disconnected": True}


async def test_a_non_http_scope_passes_straight_through():
    seen = {}

    async def app(scope, receive, send):
        seen["type"] = scope["type"]

    await BodySizeLimitMiddleware(app, max_bytes=1)({"type": "lifespan"}, None, None)
    assert seen == {"type": "lifespan"}


# ---------------------------------------------------------------------------
# האפליקציה המלאה: הסדר מול האימות בשני המצבים, והפטור לנתיב הדופק
# ---------------------------------------------------------------------------


def test_on_the_real_app_the_401_comes_before_the_413_and_the_413_names_its_reason():
    app = build_app(_Backend(), _Store(), max_request_bytes=1000, rate_limit_per_minute=1)
    big = b"{" + b" " * 2000 + b"}"

    with TestClient(app) as client:
        anonymous = client.post("/mcp", content=big, headers={"content-type": "application/json"})
        assert anonymous.status_code == 401

        refused = client.post(
            "/mcp", content=big,
            headers={"content-type": "application/json", "authorization": "Bearer good"},
        )
        assert refused.status_code == 413
        assert refused.json() == {"error": "body_too_large", "max_bytes": 1000, "content_length": len(big)}

        small = client.post(
            "/mcp", content=b"{}",
            headers={"content-type": "application/json", "authorization": "Bearer good"},
        )
        assert small.status_code not in (413, 500), "a body under the cap must reach the transport"


def _oauth_app(backend, **kwargs):
    """האפליקציה במצב OAuth — הייצור — כפי ש-``tests/test_mcp_oauth_e2e.py`` בונה אותה."""
    from pydantic import AnyHttpUrl

    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions, RevocationOptions
    from mcp_server.oauth_provider import CodeKeeperOAuthProvider
    from mcp_server.oauth_routes import oauth_consent_routes
    from mcp_server.oauth_store import OAuthStore

    base = "https://mcp.test"
    store = OAuthStore(FakeDB())
    provider = CodeKeeperOAuthProvider(
        store=store, pat_verify=lambda t: None,
        identify_url=f"{base}/fake-identify", consent_url=f"{base}/oauth/consent",
    )
    settings = AuthSettings(
        issuer_url=AnyHttpUrl(base), resource_server_url=AnyHttpUrl(base),
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=["read", "write"], default_scopes=["read"]),
        revocation_options=RevocationOptions(enabled=True), required_scopes=[],
    )
    return build_app(backend, auth_provider=provider, auth_settings=settings,
                     consent_routes=oauth_consent_routes(store, "e2e-secret"), **kwargs)


async def test_in_oauth_mode_an_anonymous_post_is_a_401_before_a_byte_of_its_body_is_read():
    """טסט סדר-ההתקנה למצב OAuth, אח של הטסט במצב PAT שמעליו.

    במצב OAuth התקרה היא השכבה החיצונית ברמת האפליקציה, וה-``RequireAuthMiddleware``
    של ה-SDK יושב בתוך ה-mount של ``/mcp`` ועונה 401 מהכותרות בלבד
    (``mcp/server/auth/middleware/bearer_auth.py``, mcp 1.28.1). לפני SEC-001
    התקרה קראה את הגוף האנונימי כולו לפני ה-401: נמדדו 5 קריאות ``receive()``
    לפני התשובה על גוף של חמישה נתחים, גם עם ``Content-Length`` מוצהר. עכשיו:
    אורך מוצהר תקין — אפס קריאות; אורך מוצהר מעל התקרה — 413 בלי קריאה;
    וגוף chunked אנונימי הוא המקרה שנשאר — נספר עד התקרה, תחת הדדליין,
    והאפליקציה אינה נכנסת.
    """
    app = _oauth_app(_Backend(), max_request_bytes=limits.MIN_MAX_REQUEST_BYTES)
    body = _chunks([1000] * 5)

    sent, trace = await _drive_traced(app, _mcp_post([("content-length", "5000")]), body)
    assert _status(sent) == 401
    assert trace == [], "declared under the cap: the SDK's auth answered before any read"

    sent, trace = await _drive_traced(app, _mcp_post([("content-length", str(2 * limits.MIN_MAX_REQUEST_BYTES))]), body)
    assert _status(sent) == 413 and trace == []

    over = _chunks([limits.MIN_MAX_REQUEST_BYTES // 2 + 1] * 3)
    sent, trace = await _drive_traced(app, _mcp_post(), over)
    assert _status(sent) == 413
    assert [n for n, _ in trace] == [0, 0], "chunked and anonymous: read up to the cap, refused, the app never ran"


def test_health_is_never_counted_or_capped():
    """הפטור של ``blanket-policy-silent-block`` §7: ``/healthz`` אינו קריאת כלי, ו-``GET`` אינו נבדק."""
    app = build_app(_Backend(), _Store(), max_request_bytes=limits.MIN_MAX_REQUEST_BYTES, rate_limit_per_minute=1)
    with TestClient(app) as client:
        statuses = {client.get("/healthz").status_code for _ in range(100)}
    assert statuses == {200}


@pytest.mark.parametrize("mode", ["pat", "oauth"])
async def test_a_spoofed_length_on_the_health_check_is_still_a_200_in_both_modes(mode):
    """WARN-002 על האפליקציה האמיתית: ``GET /healthz`` עם ``Content-Length`` מעל התקרה ענה 413.

    כל לקוח אנונימי יכול היה לעשות זאת לבקשה שלו, בניגוד למה שהתיעוד הצהיר.
    עכשיו ``GET`` אינו נבדק כלל, בשני מצבי האימות.
    """
    if mode == "pat":
        app = build_app(_Backend(), _Store(), max_request_bytes=limits.MIN_MAX_REQUEST_BYTES)
    else:
        app = _oauth_app(_Backend(), max_request_bytes=limits.MIN_MAX_REQUEST_BYTES)

    sent = await _drive(app, _scope(path="/healthz", method="GET", headers=[("content-length", "99999999")]), [])

    assert _status(sent) == 200


# ---------------------------------------------------------------------------
# המגביל, דרך call_tool של ה-FastMCP האמיתי
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _inside_a_request():
    """מה שה-SDK עושה לכל ``tools/call``: ``request_ctx`` נקבע לפני שהמטפל נקרא.

    ``Server.request_context`` הוא ``request_ctx.get()`` (``mcp/server/lowlevel/server.py``,
    ‏mcp 1.28.1), ומחוץ לבקשה הוא מרים ``LookupError`` — וזה בדיוק הסימן שהמגביל
    קורא כדי לדעת שיש מישהו לחייב. ``RequestContext`` נבנה עם ארבעת שדות החובה
    שלו (``mcp/shared/context.py``); סשן אינו נדרש, כי איש כאן אינו שולח הודעות.
    """
    token = request_ctx.set(RequestContext(request_id=1, meta=None, session=None, lifespan_context=None))
    try:
        yield
    finally:
        request_ctx.reset(token)


async def _call(mcp, name="codekeeper_get_file", arguments=None, *, inside_request=True):
    with _inside_a_request() if inside_request else contextlib.nullcontext():
        result = await mcp.call_tool(name, arguments if arguments is not None else {"file_name": "x"})
    # A tool's own dict answer comes back as content blocks; a refusal comes back
    # as a whole ``CallToolResult`` (see ``AdminAwareFastMCP.call_tool``). Both
    # carry one text block with the JSON the client reads.
    content = result.content if isinstance(result, mcp_types.CallToolResult) else result
    (block,) = content
    return json.loads(block.text)


async def test_a_call_over_the_per_minute_budget_is_refused_with_the_reason_and_the_wait(monkeypatch):
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 4242)
    mcp = build_mcp(_Backend(), rate_limit_per_minute=2)

    first, second, third = await _call(mcp), await _call(mcp), await _call(mcp)

    assert first == {"found": False} and second == {"found": False}
    assert third["ok"] is False and third["error"] == "rate_limited"
    assert third["limit_per_minute"] == 2
    assert 0 < third["retry_after_seconds"] <= 60


async def test_each_identity_has_its_own_budget(monkeypatch):
    identity = {"id": 1}
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: identity["id"])
    mcp = build_mcp(_Backend(), rate_limit_per_minute=1)

    assert await _call(mcp) == {"found": False}
    assert (await _call(mcp))["error"] == "rate_limited"
    identity["id"] = 2
    assert await _call(mcp) == {"found": False}, "a second identity is not charged for the first"


async def test_outside_a_request_nothing_is_charged(monkeypatch):
    """בלי בקשה אין לקוח לחייב: הטסטים שקוראים לכלים ישירות ממשיכים כמו היום."""
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 4242)
    mcp = build_mcp(_Backend(), rate_limit_per_minute=1)
    for _ in range(3):
        assert await _call(mcp, inside_request=False) == {"found": False}


async def test_a_refused_call_does_not_run_the_body(monkeypatch):
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 9)
    calls = []

    class _Counting(_Backend):
        def get_file(self, *args, **kwargs):
            calls.append(1)
            return None

    mcp = build_mcp(_Counting(), rate_limit_per_minute=1)
    await _call(mcp)
    await _call(mcp)
    assert len(calls) == 1, "the second call was refused before the body ran"


async def test_an_async_tool_is_limited_too(monkeypatch):
    """הגוף האסינכרוני אינו עובר ב-``_offload_to_thread``, והמגביל חייב לעטוף גם אותו."""
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 3)
    mcp = build_mcp(_Backend(), rate_limit_per_minute=1)

    @mcp.tool(name="probe_async", annotations=_READ_ONLY_TOOL)
    async def probe_async(ctx: Context) -> dict:
        return {"ok": True}

    assert await _call(mcp, "probe_async", {}) == {"ok": True}
    assert (await _call(mcp, "probe_async", {}))["error"] == "rate_limited"


async def test_zero_switches_the_limiter_off_explicitly(monkeypatch):
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 5)
    mcp = build_mcp(_Backend(), rate_limit_per_minute=0)
    for _ in range(80):
        assert await _call(mcp) == {"found": False}


async def test_without_an_identity_nothing_is_charged_and_the_body_answers(monkeypatch):
    """בלי זהות (``PermissionError``) המגביל אינו מכריע — הגוף הוא שמסרב, כמו היום."""

    def _no_identity(ctx=None):
        raise PermissionError("unauthenticated")

    monkeypatch.setattr(srv, "current_user_id", _no_identity)
    mcp = build_mcp(_Backend(), rate_limit_per_minute=1)
    with pytest.raises(Exception, match="unauthenticated"):
        await _call(mcp)
    with pytest.raises(Exception, match="unauthenticated"):
        await _call(mcp)


async def test_a_refusal_is_logged_once_per_identity_per_window(caplog):
    limiter = ToolRateLimiter(per_minute=1)
    with caplog.at_level(logging.WARNING, logger="mcp_server.limits"):
        assert await limiter.admit(11) is None
        assert (await limiter.admit(11))["error"] == "rate_limited"
        assert (await limiter.admit(11))["error"] == "rate_limited"
    warnings = [r for r in caplog.records if "rate limit" in r.getMessage()]
    assert len(warnings) == 1
    assert "11" in warnings[0].getMessage()


async def test_the_once_per_window_ledger_forgets_identities_whose_window_passed(monkeypatch):
    """SUGG-011: ``_warned_at`` גדל עם כל זהות שסורבה אי פעם; הוא מנוקה במעבר שכבר כותב אליו."""
    limiter = ToolRateLimiter(per_minute=1)
    clock = {"now": 1000.0}
    monkeypatch.setattr(limits.time, "monotonic", lambda: clock["now"])

    for identity in (1, 2, 3):
        assert await limiter.admit(identity) is None
        assert (await limiter.admit(identity))["error"] == "rate_limited"
    assert set(limiter._warned_at) == {1, 2, 3}

    clock["now"] += 61.0
    assert await limiter.admit(4) is None
    assert (await limiter.admit(4))["error"] == "rate_limited"
    assert set(limiter._warned_at) == {4}, "stamps older than a window go on the write that adds a new one"


async def test_the_budget_holds_under_concurrent_calls_from_one_identity(monkeypatch):
    """SUGG-024, ‏``TESTING-PATTERNS`` T1(d): טסט סדרתי אינו מוכיח תכונת מקביליות.

    25 קריאות בו-זמנית לזהות אחת עם תקציב של 2 — בדיוק 2 עוברות ו-23 נדחות,
    כי ``RateLimiter`` מכריע ומוסיף תחת ``asyncio.Lock`` אחד בלי ``await``
    באמצע. הטסטים שמעל רצים ברצף ולא היו מוכיחים את זה.
    """
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 4242)
    mcp = build_mcp(_Backend(), rate_limit_per_minute=2)

    results = await asyncio.gather(*(_call(mcp) for _ in range(25)))

    assert sum(r == {"found": False} for r in results) == 2
    assert sum(r.get("error") == "rate_limited" for r in results) == 23


async def test_a_limiter_passed_in_is_kept_even_when_the_object_is_falsy(monkeypatch):
    """SUGG-023, ‏K12 §3: ``or`` היה מחליף מגביל כבוי בברירת המחדל ברגע שלמחלקה יש ``__len__``.

    ``ToolRateLimiter(0)`` הוא ה-kill switch המתועד. בלי ``__bool__`` ו-``__len__``
    כל מופע אמיתי היום, ולכן ``or`` עבד — עד שמישהו מוסיף ``__len__`` (למשל כמה
    זהויות נספרות), והמגביל הכבוי הופך שקט ל-60 בדקה: ברירת מחדל שמרחיבה
    בלי שאיש החליט. ``is None`` שואל את השאלה שבאמת נשאלת.
    """

    class _Measurable(ToolRateLimiter):
        def __len__(self):
            return 0

    off = _Measurable(0)
    mcp = srv.AdminAwareFastMCP("probe", tool_rate_limiter=off)
    assert mcp._tool_rate_limiter is off

    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 5)

    @mcp.tool(name="probe", annotations=_READ_ONLY_TOOL)
    def probe(ctx: Context) -> dict:
        return {"ok": True}

    for _ in range(80):
        assert await _call(mcp, "probe", {}) == {"ok": True}, "switched off means switched off"


async def test_a_refusal_does_not_depend_on_the_tools_return_type(monkeypatch):
    """SUGG-009: הסירוב הוא ``CallToolResult`` שלם, לא ערך שעובר ב-``convert_result`` של הכלי.

    ``convert_result`` מאמת את הערך מול ``outputSchema`` של הכלי — וכלי עם
    טיפוס החזרה מוצהר (``-> list[str]``) הפך את הסירוב ל-``ValidationError``
    בדיוק כשהמגביל נדלק. מטפל ה-``tools/call`` של השרת הנמוך מחזיר
    ``CallToolResult`` כמות שהוא, בלי ולידציה של הפלט (``mcp/server/lowlevel/
    server.py``, mcp 1.28.1), ולכן זו הצורה שמשרתת כל כלי — ומה שהלקוח רואה
    הוא אותו בלוק טקסט של ``{"ok": false, "error": "rate_limited", ...}``.
    """
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 8)
    mcp = build_mcp(_Backend(), rate_limit_per_minute=1)

    @mcp.tool(name="probe_typed", annotations=_READ_ONLY_TOOL)
    def probe_typed(ctx: Context) -> list[str]:
        return ["first"]

    with _inside_a_request():
        first = await mcp.call_tool("probe_typed", {})
    assert first[1] == {"result": ["first"]}, "the typed tool's own answer: content and structured content"

    refused = await _call(mcp, "probe_typed", {})
    assert refused["error"] == "rate_limited" and refused["ok"] is False


async def test_a_refusal_survives_the_low_level_handlers_output_validation(monkeypatch):
    """אותו סירוב דרך המטפל שה-SDK באמת מריץ על ``tools/call``, לכלי עם ``outputSchema``.

    רשימת בלוקים חשופה הייתה הופכת שם ל-``isError`` ("outputSchema defined but
    no structured output returned"); ``CallToolResult`` עובר כמות שהוא.
    """
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 12)
    mcp = build_mcp(_Backend(), rate_limit_per_minute=1)

    @mcp.tool(name="probe_typed", annotations=_READ_ONLY_TOOL)
    def probe_typed(ctx: Context) -> list[str]:
        return ["first"]

    handler = mcp._mcp_server.request_handlers[mcp_types.CallToolRequest]
    request = mcp_types.CallToolRequest(
        method="tools/call", params=mcp_types.CallToolRequestParams(name="probe_typed", arguments={}))
    with _inside_a_request():
        first = (await handler(request)).root
        second = (await handler(request)).root

    assert isinstance(first, mcp_types.CallToolResult) and first.isError is False
    assert first.structuredContent == {"result": ["first"]}
    assert isinstance(second, mcp_types.CallToolResult) and second.isError is False
    assert json.loads(second.content[0].text)["error"] == "rate_limited"


async def test_an_unknown_tool_over_budget_is_refused_before_the_name_is_looked_up(monkeypatch):
    """SUGG-009: שם כלי לא מוכר מעל התקציב קיבל את שגיאת ה-SDK במקום ``rate_limited``."""
    monkeypatch.setattr(srv, "current_user_id", lambda ctx=None: 9)
    mcp = build_mcp(_Backend(), rate_limit_per_minute=1)

    assert await _call(mcp) == {"found": False}
    assert (await _call(mcp, "no_such_tool", {}))["error"] == "rate_limited"


# ---------------------------------------------------------------------------
# הגדרה ממשתני סביבה: טעות תצורה לעולם אינה מרחיבה
# ---------------------------------------------------------------------------


def test_limit_from_env_never_widens_on_a_bad_value(monkeypatch, caplog):
    name = "MCP_LIMIT_UNDER_TEST"
    monkeypatch.delenv(name, raising=False)
    assert limit_from_env(name, 60, minimum=1) == 60

    with caplog.at_level(logging.WARNING, logger="mcp_server.limits"):
        monkeypatch.setenv(name, "sixty")
        assert limit_from_env(name, 60, minimum=1) == 60
        monkeypatch.setenv(name, "10")
        assert limit_from_env(name, 1_048_576, minimum=65_536) == 65_536
        monkeypatch.setenv(name, "0")
        assert limit_from_env(name, 60, minimum=1, zero_disables=True) == 0
        assert limit_from_env(name, 60, minimum=1) == 1, "0 without zero_disables is below the minimum"
    assert sum("not an integer" in r.getMessage() for r in caplog.records) == 1
    assert sum("below the minimum" in r.getMessage() for r in caplog.records) == 2
    assert sum("switched off" in r.getMessage() for r in caplog.records) == 1

    monkeypatch.setenv(name, "120")
    assert limit_from_env(name, 60, minimum=1) == 120


# ---------------------------------------------------------------------------
# ההרחבה של המגביל המשותף
# ---------------------------------------------------------------------------


async def test_seconds_until_allowed_is_zero_with_room_and_the_rest_of_the_window_without():
    limiter = RateLimiter(max_per_minute=1)
    assert await limiter.seconds_until_allowed(1) == 0.0
    assert await limiter.check_rate_limit(1) is True
    wait = await limiter.seconds_until_allowed(1)
    assert 0 < wait <= 60
    assert await limiter.check_rate_limit(1) is False


async def test_asking_about_an_identity_does_not_create_an_entry_for_it():
    """SUGG-011: ``_live_entries`` קרא ``self._requests[user_id]`` על ``defaultdict`` — ויצר רשומה קבועה למי ששאלו עליו בלבד."""
    limiter = RateLimiter(max_per_minute=1)

    assert await limiter.get_current_usage_ratio(1) == 0.0
    assert await limiter.seconds_until_allowed(1) == 0.0
    assert 1 not in limiter._requests

    assert await limiter.check_rate_limit(1) is True
    assert 1 in limiter._requests, "an admitted call is what creates the entry"


async def test_an_identity_whose_window_emptied_is_forgotten():
    limiter = RateLimiter(max_per_minute=2)
    assert await limiter.check_rate_limit(2) is True
    limiter._requests[2] = [datetime.now(timezone.utc) - timedelta(seconds=120)]

    assert await limiter.get_current_usage_ratio(2) == 0.0
    assert 2 not in limiter._requests, "nothing left in the window: the key goes with it"
    assert await limiter.check_rate_limit(2) is True
    assert len(limiter._requests[2]) == 1


# ---------------------------------------------------------------------------
# התקרה נגזרת מגודל הקובץ המותר, ולא מוקלדת לצידו
# ---------------------------------------------------------------------------


def _real_config_module(cwd):
    """המודול ``config`` האמיתי, לפי נתיב — התקדים ב-``tests/test_redis_safety.py``.

    תחת pytest התיקייה ``tests`` בראש ``sys.path`` ו-``tests/config.py`` מאפיל
    על המודול האמיתי. pydantic דורש שהמודול יהיה ב-``sys.modules`` בזמן
    הגדרת המחלקה (אחרת ``BotConfig`` "is not fully defined"), ו-``BotConfig()``
    שנבנה בייבוא קורא ``.env`` יחסית לתיקיית העבודה — לכן הטעינה רצה
    בתוך ``tmp_path``, ומה שנשמר ומשוחזר הוא ה-cwd ורשומת המודול.
    """
    import os
    import sys

    spec = importlib.util.spec_from_file_location("_real_config_for_the_cap", _REPO / "config.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    saved_cwd = os.getcwd()
    sys.modules[spec.name] = module
    try:
        os.chdir(cwd)
        spec.loader.exec_module(module)
    finally:
        os.chdir(saved_cwd)
        sys.modules.pop(spec.name, None)
    return module


def test_the_body_cap_is_derived_from_the_code_size_ceiling(tmp_path):
    """SUGG-022, ‏R6: עותק שני של כלל בלי מנגנון שתופס סחיפה הוא הצורה הפסולה.

    ‏``DEFAULT_MAX_REQUEST_BYTES`` היה מוקלד (1MiB) לצד הערה שגוזרת אותו ביד
    מ-``MAX_CODE_SIZE``; ``MAX_CODE_SIZE`` שיעלה מעל כ-170,000 תווים היה מביא
    שמירה לגיטימית של קובץ עברי ל-413. עכשיו התקרה נגזרת מהמספר, והגזירה
    מוצמדת כאן לפי התקדים של ``test_the_two_ceilings_are_the_same_number``:
    העותק ב-``handlers`` שווה לברירת המחדל של התצורה, המספר המתועד (1MiB)
    הוא הגזירה על ברירת המחדל, ותקרת קוד אחרת נותנת תקרת גוף אחרת.
    """
    assert handlers.DEFAULT_MAX_CODE_SIZE == _real_config_module(tmp_path).BotConfig.model_fields["MAX_CODE_SIZE"].default
    assert limits.DEFAULT_MAX_REQUEST_BYTES == limits.request_bytes_for(handlers.DEFAULT_MAX_CODE_SIZE) == 1_048_576
    assert limits.request_bytes_for(3 * handlers.DEFAULT_MAX_CODE_SIZE) == 2 * 1_048_576
    assert limits.request_bytes_for(handlers.DEFAULT_MAX_CODE_SIZE) % (1024 * 1024) == 0, "whole MiBs, rounded up"


def test_a_hebrew_file_at_the_size_ceiling_fits_under_the_cap_with_its_envelope():
    """הבקשה הלגיטימית הגדולה ביותר נכנסת: ``codekeeper_save_file`` על קובץ עברי בגודל המקסימלי, בקידוד היקר.

    ``json.dumps`` בברירת המחדל (``ensure_ascii=True``) כותב כל תו עברי כ-``\\uXXXX``
    — שישה בתים — וזה מה שלקוח שמקודד כך שולח. המעטפת: JSON-RPC, שם הכלי, שם
    הקובץ, שפה, ותיאור בתקרתו (``FILE_DESCRIPTION_MAX_CHARS``); לשם הקובץ אין
    תקרה בשכבה הזאת, ולכן נלקח שם ארוך מהמקובל.
    """
    from database.repository import FILE_DESCRIPTION_MAX_CHARS

    request = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {
            "name": "codekeeper_save_file",
            "arguments": {
                "file_name": "שם-קובץ-ארוך-" * 20 + ".py",
                "code": "ש" * handlers.DEFAULT_MAX_CODE_SIZE,
                "language": "python",
                "description": "ת" * FILE_DESCRIPTION_MAX_CHARS,
            },
        },
    }
    body = json.dumps(request, ensure_ascii=True).encode("ascii")

    assert len(body) > handlers.DEFAULT_MAX_CODE_SIZE * limits.JSON_BYTES_PER_CHAR, "the escape really costs six bytes a character"
    assert len(body) <= limits.DEFAULT_MAX_REQUEST_BYTES


def test_the_config_inspector_shows_the_limits_the_service_reads():
    """שני משתני הסביבה בתצוגת התצורה: אותם שמות ואותן ברירות מחדל שהקוד קורא — לא עותק שנסחף."""
    from services.config_inspector_service import ConfigService

    cap = ConfigService.CONFIG_DEFINITIONS[limits.MAX_REQUEST_BYTES_ENV]
    rate = ConfigService.CONFIG_DEFINITIONS[limits.RATE_LIMIT_ENV]
    assert cap.key == limits.MAX_REQUEST_BYTES_ENV and cap.default == str(limits.DEFAULT_MAX_REQUEST_BYTES)
    assert rate.key == limits.RATE_LIMIT_ENV and rate.default == str(limits.DEFAULT_RATE_LIMIT_PER_MINUTE)
    assert str(limits.MIN_MAX_REQUEST_BYTES) in cap.description
