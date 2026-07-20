"""In-process OAuth HTTP-flow test: register -> authorize -> consent -> token.

Drives the real OAuth-mode ASGI app via httpx ASGITransport (no port, no MCP
transport). The tool-call-with-OAuth-token path is covered by the manual spike.
"""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip("mcp")
pytest.importorskip("httpx")

import httpx  # noqa: E402
from pydantic import AnyHttpUrl  # noqa: E402

from mcp.server.auth.settings import (  # noqa: E402
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp_server.oauth_identity import sign_identity  # noqa: E402
from mcp_server.oauth_provider import CodeKeeperOAuthProvider  # noqa: E402
from mcp_server.oauth_routes import oauth_consent_routes  # noqa: E402
from mcp_server.oauth_store import OAuthStore  # noqa: E402
from mcp_server.server import build_app  # noqa: E402

try:  # local `tests` pkg can be shadowed by an unrelated top-level `tests` on sys.path
    from tests._fake_mongo import FakeDB  # noqa: E402
except ImportError:  # fall back to the sibling module (tests/ is on sys.path under pytest)
    from _fake_mongo import FakeDB  # noqa: E402

SECRET = "e2e-secret"
BASE = "https://mcp.test"  # SDK requires an HTTPS issuer (or localhost)


class _FakeBackend:
    def list_files(self, *a, **k):
        return {}

    def search_code(self, *a, **k):
        return []

    def get_file(self, *a, **k):
        return None

    def list_versions(self, *a, **k):
        return []

    def list_collections(self, *a, **k):
        return {}

    def get_collection(self, *a, **k):
        return {}

    def get_collection_items(self, *a, **k):
        return {}

    def save_file(self, *a, **k):
        return {"ok": True, "created": True, "file": {}}


def _build(default_scopes=("read",)):
    store = OAuthStore(FakeDB())
    provider = CodeKeeperOAuthProvider(
        store=store,
        pat_verify=lambda t: None,
        identify_url=f"{BASE}/fake-identify",
        consent_url=f"{BASE}/oauth/consent",
    )
    settings = AuthSettings(
        issuer_url=AnyHttpUrl(BASE),
        resource_server_url=AnyHttpUrl(BASE),
        client_registration_options=ClientRegistrationOptions(
            enabled=True, valid_scopes=["read", "write"], default_scopes=list(default_scopes)
        ),
        revocation_options=RevocationOptions(enabled=True),
        required_scopes=[],
    )
    app = build_app(
        _FakeBackend(),
        auth_provider=provider,
        auth_settings=settings,
        consent_routes=oauth_consent_routes(store, SECRET),
    )
    return app


def _pkce():
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    return verifier, challenge


def _client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE, follow_redirects=False
    )


async def test_metadata_and_health_open():
    app = _build()
    async with _client(app) as c:
        assert (await c.get("/healthz")).status_code == 200
        meta = await c.get("/.well-known/oauth-authorization-server")
    assert meta.status_code == 200
    body = meta.json()
    assert body.get("registration_endpoint")
    assert "S256" in (body.get("code_challenge_methods_supported") or [])


async def test_full_oauth_http_flow_issues_access_token():
    app = _build()
    verifier, challenge = _pkce()
    async with _client(app) as c:
        reg = await c.post(
            "/register",
            json={
                "redirect_uris": [f"{BASE}/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        assert reg.status_code == 201
        client_id = reg.json()["client_id"]

        az = await c.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": f"{BASE}/callback",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "xyz",
                "scope": "read",
            },
        )
        assert az.status_code == 302
        txn = parse_qs(urlparse(az.headers["location"]).query)["txn"][0]

        exp, sig = sign_identity(SECRET, 555, txn)
        cp = await c.post(
            "/oauth/consent",
            data={"txn": txn, "user_id": "555", "exp": str(exp), "sig": sig, "action": "approve"},
        )
        assert cp.status_code == 302
        cb = parse_qs(urlparse(cp.headers["location"]).query)
        assert cb["state"][0] == "xyz"
        code = cb["code"][0]

        tok = await c.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{BASE}/callback",
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
    assert tok.status_code == 200
    payload = tok.json()
    assert payload["access_token"].startswith("ckoat_")
    assert payload["refresh_token"].startswith("ckort_")
    assert payload["token_type"].lower() == "bearer"


async def test_write_scope_survives_from_authorize_to_token():
    app = _build()
    verifier, challenge = _pkce()
    async with _client(app) as c:
        reg = await c.post(
            "/register",
            json={
                "redirect_uris": [f"{BASE}/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                "scope": "read write",
            },
        )
        assert reg.status_code == 201, reg.text
        client_id = reg.json()["client_id"]
        az = await c.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": f"{BASE}/callback",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "xyz",
                "scope": "read write",
            },
        )
        assert az.status_code == 302
        txn = parse_qs(urlparse(az.headers["location"]).query)["txn"][0]
        exp, sig = sign_identity(SECRET, 555, txn)
        cp = await c.post(
            "/oauth/consent",
            data={"txn": txn, "user_id": "555", "exp": str(exp), "sig": sig, "action": "approve"},
        )
        code = parse_qs(urlparse(cp.headers["location"]).query)["code"][0]
        tok = await c.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{BASE}/callback",
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
    assert tok.status_code == 200, tok.text
    # The write scope must survive the whole authorize→txn→consent→code→token chain.
    assert "write" in (tok.json().get("scope") or "").split()


async def test_scopeless_client_gets_write_from_registered_default():
    # Reproduces the real Claude.ai failure: the client registers AND authorizes
    # without ever naming a scope. With default_scopes=["read","write"], DCR
    # registers it for read+write and the scope-less /authorize grants that full
    # registered scope — so write reaches the token (consent still gates it).
    # Before the fix this yielded read-only because /authorize fell back to a
    # hardcoded ("read",) instead of the client's registered scope.
    app = _build(default_scopes=("read", "write"))
    verifier, challenge = _pkce()
    async with _client(app) as c:
        reg = await c.post(
            "/register",
            json={
                "redirect_uris": [f"{BASE}/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
                # NOTE: no "scope" key — mirrors Claude.ai's registration.
            },
        )
        assert reg.status_code == 201, reg.text
        client_id = reg.json()["client_id"]
        # DCR assigned the read+write default as the client's registered ceiling.
        assert set((reg.json().get("scope") or "").split()) == {"read", "write"}
        az = await c.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": f"{BASE}/callback",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "xyz",
                # NOTE: no "scope" param — mirrors Claude.ai's /authorize.
            },
        )
        assert az.status_code == 302, az.text
        txn = parse_qs(urlparse(az.headers["location"]).query)["txn"][0]
        exp, sig = sign_identity(SECRET, 555, txn)
        cp = await c.post(
            "/oauth/consent",
            data={"txn": txn, "user_id": "555", "exp": str(exp), "sig": sig, "action": "approve"},
        )
        code = parse_qs(urlparse(cp.headers["location"]).query)["code"][0]
        tok = await c.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{BASE}/callback",
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
    assert tok.status_code == 200, tok.text
    assert "write" in (tok.json().get("scope") or "").split()


async def test_token_rejects_wrong_pkce_verifier():
    app = _build()
    _, challenge = _pkce()
    async with _client(app) as c:
        reg = await c.post(
            "/register",
            json={
                "redirect_uris": [f"{BASE}/callback"],
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "none",
            },
        )
        assert reg.status_code == 201, reg.text
        client_id = reg.json()["client_id"]
        az = await c.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": f"{BASE}/callback",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "s",
                "scope": "read",
            },
        )
        txn = parse_qs(urlparse(az.headers["location"]).query)["txn"][0]
        exp, sig = sign_identity(SECRET, 555, txn)
        cp = await c.post(
            "/oauth/consent",
            data={"txn": txn, "user_id": "555", "exp": str(exp), "sig": sig, "action": "approve"},
        )
        code = parse_qs(urlparse(cp.headers["location"]).query)["code"][0]
        tok = await c.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": f"{BASE}/callback",
                "client_id": client_id,
                "code_verifier": "wrong-verifier-does-not-match-challenge",
            },
        )
    assert tok.status_code == 400  # PKCE mismatch rejected by the SDK
