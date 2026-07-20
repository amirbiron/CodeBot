"""Unit tests for the OAuth provider (full lifecycle, fake Mongo)."""

import urllib.parse as up

import pytest

pytest.importorskip("mcp")

from pydantic import AnyUrl  # noqa: E402

from mcp.server.auth.provider import AuthorizationParams, TokenError  # noqa: E402
from mcp.shared.auth import OAuthClientInformationFull  # noqa: E402

from mcp_server.oauth_provider import CodeKeeperOAuthProvider  # noqa: E402
from mcp_server.oauth_store import (
    ACCESS_PREFIX,
    REFRESH_PREFIX,
    OAuthStore,
    new_secret,
)  # noqa: E402

try:  # local `tests` pkg can be shadowed by an unrelated top-level `tests` on sys.path
    from tests._fake_mongo import FakeDB  # noqa: E402
except ImportError:  # fall back to the sibling module (tests/ is on sys.path under pytest)
    from _fake_mongo import FakeDB  # noqa: E402


def _pat(tok):
    return {"user_id": 7, "scopes": ["read"]} if tok == "ckmcp_good" else None


def _provider():
    store = OAuthStore(FakeDB())
    prov = CodeKeeperOAuthProvider(
        store=store,
        pat_verify=_pat,
        identify_url="https://web/oauth/identify",
        consent_url="https://mcp/oauth/consent",
    )
    return store, prov


def _client(cid="c1"):
    return OAuthClientInformationFull(client_id=cid, redirect_uris=[AnyUrl("https://claude.ai/cb")])


def _params():
    return AuthorizationParams(
        state="st",
        scopes=["read"],
        code_challenge="chal",
        redirect_uri=AnyUrl("https://claude.ai/cb"),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )


async def test_register_and_get_client():
    _, prov = _provider()
    await prov.register_client(_client())
    got = await prov.get_client("c1")
    assert got is not None
    # Parse rather than startswith: "https://claude.ai.evil.com" would slip past a
    # prefix check, so assert scheme + host exactly (also silences CodeQL).
    parsed = up.urlparse(str(got.redirect_uris[0]))
    assert parsed.scheme == "https" and parsed.hostname == "claude.ai"
    assert await prov.get_client("nope") is None


async def test_authorize_creates_txn_and_redirect():
    store, prov = _provider()
    url = await prov.authorize(_client(), _params())
    assert url.startswith("https://web/oauth/identify?txn=")
    assert "return=" in url
    txn_id = up.parse_qs(up.urlparse(url).query)["txn"][0]
    txn = store.get_txn(txn_id)
    assert txn["code_challenge"] == "chal" and txn["state"] == "st"
    assert txn["client_id"] == "c1"


def _params_no_scope():
    return AuthorizationParams(
        state="st",
        scopes=None,  # client omitted scope at /authorize (the Claude.ai case)
        code_challenge="chal",
        redirect_uri=AnyUrl("https://claude.ai/cb"),
        redirect_uri_provided_explicitly=True,
        resource=None,
    )


async def test_authorize_without_scope_falls_back_to_registered_scope():
    # No scope at /authorize ⇒ grant the client's full *registered* scope, not a
    # hardcoded read-only default. This is what lets Claude.ai (which never names
    # a scope) reach write once it is registered for it.
    store, prov = _provider()
    client = OAuthClientInformationFull(
        client_id="c1", redirect_uris=[AnyUrl("https://claude.ai/cb")], scope="read write"
    )
    url = await prov.authorize(client, _params_no_scope())
    txn_id = up.parse_qs(up.urlparse(url).query)["txn"][0]
    assert store.get_txn(txn_id)["scopes"] == ["read", "write"]


async def test_authorize_without_scope_and_no_registration_uses_read_default():
    # Defensive fallback: a client with no registered scope at all (shouldn't
    # happen via DCR) stays read-only rather than silently widening.
    store, prov = _provider()
    client = OAuthClientInformationFull(
        client_id="c1", redirect_uris=[AnyUrl("https://claude.ai/cb")]
    )
    url = await prov.authorize(client, _params_no_scope())
    txn_id = up.parse_qs(up.urlparse(url).query)["txn"][0]
    assert store.get_txn(txn_id)["scopes"] == ["read"]


async def test_code_exchange_issues_tokens_and_consumes():
    store, prov = _provider()
    code = new_secret("ckoc_")
    store.save_code(
        code,
        {
            "client_id": "c1",
            "subject": "42",
            "code_challenge": "chal",
            "redirect_uri": "https://claude.ai/cb",
            "redirect_uri_provided_explicitly": True,
            "scopes": ["read"],
        },
    )
    loaded = await prov.load_authorization_code(_client(), code)
    assert loaded is not None and loaded.subject == "42" and loaded.code_challenge == "chal"
    tok = await prov.exchange_authorization_code(_client(), loaded)
    assert tok.access_token.startswith(ACCESS_PREFIX)
    assert tok.refresh_token.startswith(REFRESH_PREFIX)
    # code is single-use
    assert await prov.load_authorization_code(_client(), code) is None
    # issued access token resolves to the subject
    at = await prov.load_access_token(tok.access_token)
    assert at is not None and at.subject == "42"


async def test_wrong_client_cannot_load_code():
    store, prov = _provider()
    code = new_secret("ckoc_")
    store.save_code(
        code, {"client_id": "c1", "subject": "42", "redirect_uri": "https://claude.ai/cb"}
    )
    assert await prov.load_authorization_code(_client("other"), code) is None


async def test_load_access_token_pat_and_invalid():
    _, prov = _provider()
    at = await prov.load_access_token("ckmcp_good")
    assert at is not None and at.subject == "7" and at.client_id == "pat"
    assert await prov.load_access_token("ckmcp_bad") is None
    assert await prov.load_access_token("ckoat_nonexistent") is None


async def test_refresh_token_rotation():
    store, prov = _provider()
    code = new_secret("ckoc_")
    store.save_code(
        code,
        {
            "client_id": "c1",
            "subject": "42",
            "code_challenge": "c",
            "redirect_uri": "https://claude.ai/cb",
            "scopes": ["read"],
        },
    )
    loaded = await prov.load_authorization_code(_client(), code)
    tok = await prov.exchange_authorization_code(_client(), loaded)
    old_refresh = tok.refresh_token

    rt = await prov.load_refresh_token(_client(), old_refresh)
    assert rt is not None and rt.subject == "42"
    new_tok = await prov.exchange_refresh_token(_client(), rt, ["read"])
    assert new_tok.refresh_token != old_refresh  # rotated
    assert await prov.load_refresh_token(_client(), old_refresh) is None  # old revoked
    at = await prov.load_access_token(new_tok.access_token)
    assert at is not None and at.subject == "42"


def _saved_code(store, **over):
    code = new_secret("ckoc_")
    data = {
        "client_id": "c1",
        "subject": "42",
        "code_challenge": "c",
        "redirect_uri": "https://claude.ai/cb",
        "scopes": ["read"],
    }
    data.update(over)
    store.save_code(code, data)
    return code


async def test_authorization_code_replay_is_rejected():
    store, prov = _provider()
    code = _saved_code(store)
    loaded = await prov.load_authorization_code(_client(), code)
    await prov.exchange_authorization_code(_client(), loaded)  # first use consumes it
    with pytest.raises(TokenError) as ei:  # replaying the same code must not mint again
        await prov.exchange_authorization_code(_client(), loaded)
    assert ei.value.error == "invalid_grant"


async def test_refresh_token_replay_is_rejected():
    store, prov = _provider()
    code = _saved_code(store)
    loaded = await prov.load_authorization_code(_client(), code)
    tok = await prov.exchange_authorization_code(_client(), loaded)
    rt = await prov.load_refresh_token(_client(), tok.refresh_token)
    await prov.exchange_refresh_token(_client(), rt, ["read"])  # rotates + revokes rt
    with pytest.raises(TokenError) as ei:  # reusing the rotated refresh token
        await prov.exchange_refresh_token(_client(), rt, ["read"])
    assert ei.value.error == "invalid_grant"


async def test_refresh_cannot_widen_scope():
    store, prov = _provider()
    code = _saved_code(store, scopes=["read"])
    loaded = await prov.load_authorization_code(_client(), code)
    tok = await prov.exchange_authorization_code(_client(), loaded)
    rt = await prov.load_refresh_token(_client(), tok.refresh_token)
    with pytest.raises(TokenError) as ei:  # asking for a scope the grant never had
        await prov.exchange_refresh_token(_client(), rt, ["read", "write"])
    assert ei.value.error == "invalid_scope"
    # the failed attempt must not have consumed/revoked the still-valid token
    assert await prov.load_refresh_token(_client(), tok.refresh_token) is not None
