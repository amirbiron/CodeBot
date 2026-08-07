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


# ---------------------------------------------------------------------------
# authenticate_bearer — אותו נתיב ולידציה, לשימוש ראוטים שאינם /mcp
# ---------------------------------------------------------------------------
async def test_extract_bearer_token_variants():
    from mcp_server.auth import extract_bearer_token

    assert extract_bearer_token(_request(headers=[])) is None
    assert extract_bearer_token(_request(headers=[("authorization", "Basic x")])) is None
    assert extract_bearer_token(_request(headers=[("authorization", "Bearer   ")])) is None
    # הסכימה עצמה אינה case-sensitive לפי RFC 7235
    assert extract_bearer_token(_request(headers=[("authorization", "bearer abc")])) == "abc"


async def test_authenticate_bearer_uses_the_token_store():
    from mcp_server.auth import authenticate_bearer

    store = _FakeStore({"good": {"user_id": 5, "scopes": ["read"]}})
    ok = await authenticate_bearer(
        _request(headers=[("authorization", "Bearer good")]), token_store=store
    )
    assert ok == {"user_id": 5, "scopes": ["read"]}

    bad = await authenticate_bearer(
        _request(headers=[("authorization", "Bearer bad")]), token_store=store
    )
    assert bad is None


async def test_authenticate_bearer_uses_the_oauth_provider_when_present():
    """במצב OAuth האימות עובר דרך load_access_token — שמקבל גם PAT וגם ckoat_."""
    from mcp_server.auth import authenticate_bearer

    class _Token:
        subject = "42"
        scopes = ["read", "write"]

    class _Provider:
        async def load_access_token(self, token):
            return _Token() if token == "ckoat_valid" else None

    ok = await authenticate_bearer(
        _request(headers=[("authorization", "Bearer ckoat_valid")]), auth_provider=_Provider()
    )
    assert ok == {"user_id": 42, "scopes": ["read", "write"]}

    bad = await authenticate_bearer(
        _request(headers=[("authorization", "Bearer nope")]), auth_provider=_Provider()
    )
    assert bad is None


async def test_authenticate_bearer_fails_closed_with_no_verifier():
    """בלי מאמת מוגדר — דחייה, לא מעבר חופשי."""
    from mcp_server.auth import authenticate_bearer

    assert await authenticate_bearer(_request(headers=[("authorization", "Bearer x")])) is None


async def test_authenticate_bearer_fails_closed_when_the_store_raises():
    from mcp_server.auth import authenticate_bearer

    class _Broken:
        def verify(self, token):
            raise RuntimeError("mongo down")

    got = await authenticate_bearer(
        _request(headers=[("authorization", "Bearer x")]), token_store=_Broken()
    )
    assert got is None
