"""Unit tests for the PAT auth middleware (Starlette-level, no server/port)."""

import pytest

pytest.importorskip("starlette")

from starlette.requests import Request  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402

from mcp_server.auth import PATAuthMiddleware  # noqa: E402


class _FakeStore:
    def __init__(self, mapping):
        self.mapping = mapping

    def verify(self, token):
        return self.mapping.get(token)


def _request(path="/mcp", headers=None):
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or [])]
    scope = {
        "type": "http",
        "method": "POST",
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
        "server": ("test", 80),
        "scheme": "http",
    }
    return Request(scope)


async def _call_next(request):
    return PlainTextResponse(f"ok:{getattr(request.state, 'user_id', None)}")


def _mw(store):
    return PATAuthMiddleware(app=None, token_store=store)


async def test_missing_bearer_returns_401():
    resp = await _mw(_FakeStore({})).dispatch(_request(headers=[]), _call_next)
    assert resp.status_code == 401
    assert resp.headers.get("WWW-Authenticate", "").startswith("Bearer")


async def test_invalid_token_returns_401():
    store = _FakeStore({"good": {"user_id": 5, "scopes": ["read"]}})
    resp = await _mw(store).dispatch(
        _request(headers=[("authorization", "Bearer bad")]), _call_next
    )
    assert resp.status_code == 401


async def test_valid_token_injects_user_id():
    store = _FakeStore({"good": {"user_id": 5, "scopes": ["read"]}})
    resp = await _mw(store).dispatch(
        _request(headers=[("authorization", "Bearer good")]), _call_next
    )
    assert resp.status_code == 200
    assert resp.body == b"ok:5"


async def test_healthz_is_exempt():
    resp = await _mw(_FakeStore({})).dispatch(_request(path="/healthz", headers=[]), _call_next)
    assert resp.status_code == 200
