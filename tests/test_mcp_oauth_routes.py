"""Consent route tests — drive the ASGI app in-process via httpx (no network)."""

import pytest

pytest.importorskip("mcp")
pytest.importorskip("httpx")

import httpx  # noqa: E402
from starlette.applications import Starlette  # noqa: E402

from mcp_server.oauth_identity import sign_identity  # noqa: E402
from mcp_server.oauth_routes import oauth_consent_routes  # noqa: E402
from mcp_server.oauth_store import OAuthStore  # noqa: E402

try:  # local `tests` pkg can be shadowed by an unrelated top-level `tests` on sys.path
    from tests._fake_mongo import FakeDB  # noqa: E402
except ImportError:  # fall back to the sibling module (tests/ is on sys.path under pytest)
    from _fake_mongo import FakeDB  # noqa: E402

SECRET = "s3cr3t"


def _app_store():
    store = OAuthStore(FakeDB())
    app = Starlette(routes=oauth_consent_routes(store, SECRET))
    return app, store


def _mk_txn(store, **over):
    data = {
        "client_id": "c1",
        "redirect_uri": "https://claude.ai/cb",
        "redirect_uri_provided_explicitly": True,
        "code_challenge": "ch",
        "scopes": ["read"],
        "state": "st",
    }
    data.update(over)
    return store.create_txn(data)


def _client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_consent_get_renders_page():
    app, store = _app_store()
    txn = _mk_txn(store)
    exp, sig = sign_identity(SECRET, 42, txn)
    async with _client(app) as c:
        r = await c.get(
            "/oauth/consent", params={"txn": txn, "user_id": 42, "exp": exp, "sig": sig}
        )
    assert r.status_code == 200
    assert "אישור וחיבור" in r.text


async def test_consent_get_bad_assertion_400():
    app, store = _app_store()
    txn = _mk_txn(store)
    async with _client(app) as c:
        r = await c.get(
            "/oauth/consent", params={"txn": txn, "user_id": 42, "exp": 9999999999, "sig": "bad"}
        )
    assert r.status_code == 400


async def test_consent_approve_mints_code_and_redirects():
    app, store = _app_store()
    txn = _mk_txn(store)
    exp, sig = sign_identity(SECRET, 42, txn)
    async with _client(app) as c:
        r = await c.post(
            "/oauth/consent",
            data={"txn": txn, "user_id": "42", "exp": str(exp), "sig": sig, "action": "approve"},
            follow_redirects=False,
        )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("https://claude.ai/cb?")
    assert "code=ckoc_" in loc and "state=st" in loc
    assert store.get_txn(txn) is None  # txn consumed


async def test_consent_deny_redirects_with_error():
    app, store = _app_store()
    txn = _mk_txn(store)
    exp, sig = sign_identity(SECRET, 42, txn)
    async with _client(app) as c:
        r = await c.post(
            "/oauth/consent",
            data={"txn": txn, "user_id": "42", "exp": str(exp), "sig": sig, "action": "deny"},
            follow_redirects=False,
        )
    assert r.status_code == 302
    assert "error=access_denied" in r.headers["location"]


async def test_consent_missing_action_fails_closed():
    # No/unknown action must be treated as denial — never mint a code by default.
    app, store = _app_store()
    txn = _mk_txn(store)
    exp, sig = sign_identity(SECRET, 42, txn)
    async with _client(app) as c:
        r = await c.post(
            "/oauth/consent",
            data={"txn": txn, "user_id": "42", "exp": str(exp), "sig": sig},
            follow_redirects=False,
        )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert "error=access_denied" in loc
    assert "code=ckoc_" not in loc
    assert store.get_txn(txn) is None  # txn consumed on denial
