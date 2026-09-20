"""גבולות הבקשה של שרת ה-MCP (#3431): תקרת גוף במידלוור, והגבלת קצב לפי זהות בנקודת השיגור.

שני הגבולות נבדקים בשכבה שבה הם חיים — המידלוור מול הודעות ASGI ממש, והמגביל
דרך ``call_tool`` של ה-``FastMCP`` האמיתי — ואז על האפליקציה המלאה דרך
``TestClient``, כי הפטור לנתיבי הדופק והסדר מול האימות הם תכונות של ההרכבה
ולא של אף רכיב לבדו. בלי ``sleep``: התקרה והחלון מוקטנים במקום להמתין להם.
"""

from __future__ import annotations

import contextlib
import json
import logging

import pytest

pytest.importorskip("mcp")

from mcp.server.fastmcp import Context  # noqa: E402
from mcp.server.lowlevel.server import request_ctx  # noqa: E402
from mcp.shared.context import RequestContext  # noqa: E402
from starlette.requests import ClientDisconnect, Request  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

import mcp_server.server as srv  # noqa: E402
from mcp_server import limits  # noqa: E402
from mcp_server.limits import BodySizeLimitMiddleware, ToolRateLimiter, limit_from_env  # noqa: E402
from mcp_server.server import _READ_ONLY_TOOL, build_app, build_mcp  # noqa: E402
from rate_limiter import RateLimiter  # noqa: E402


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
    return {
        "type": "http",
        "method": method,
        "path": path,
        "headers": [(k.encode(), v.encode()) for k, v in headers],
        "query_string": b"",
        "server": ("test", 80),
        "scheme": "http",
    }


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


def _status(sent):
    return next(m["status"] for m in sent if m["type"] == "http.response.start")


def _json_body(sent):
    return json.loads(b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body"))


async def test_a_declared_length_over_the_cap_is_refused_before_a_byte_is_read():
    echo = _Echo()
    mw = BodySizeLimitMiddleware(echo, max_bytes=100)

    sent = await _drive(mw, _scope(headers=[("content-length", "101")]), messages=[])

    assert _status(sent) == 413
    assert _json_body(sent) == {"error": "body_too_large", "max_bytes": 100, "content_length": 101}
    assert echo.calls == 0


async def test_a_streamed_body_over_the_cap_is_refused_and_the_app_never_runs():
    """בלי ``Content-Length`` (או עם אחת שמכזבת) — הספירה של מה שבאמת מגיע היא שעוצרת."""
    echo = _Echo()
    mw = BodySizeLimitMiddleware(echo, max_bytes=100)
    chunks = [
        {"type": "http.request", "body": b"x" * 60, "more_body": True},
        {"type": "http.request", "body": b"y" * 60, "more_body": False},
    ]

    sent = await _drive(mw, _scope(headers=[("content-length", "90")]), chunks)

    assert _status(sent) == 413
    assert _json_body(sent) == {"error": "body_too_large", "max_bytes": 100, "received_bytes": 120}
    assert echo.calls == 0


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
# האפליקציה המלאה: הסדר מול האימות, והפטור המבני לנתיב הדופק
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


def test_health_is_never_counted_or_capped():
    """הפטור של ``blanket-policy-silent-block`` §7 — מבני: ``/healthz`` אינו קריאת כלי ואין לו גוף."""
    app = build_app(_Backend(), _Store(), max_request_bytes=limits.MIN_MAX_REQUEST_BYTES, rate_limit_per_minute=1)
    with TestClient(app) as client:
        statuses = {client.get("/healthz").status_code for _ in range(100)}
    assert statuses == {200}


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
        blocks = await mcp.call_tool(name, arguments if arguments is not None else {"file_name": "x"})
    (block,) = blocks
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
