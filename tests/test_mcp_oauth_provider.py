"""Unit tests for the OAuth provider (full lifecycle, fake Mongo)."""

import urllib.parse as up

import pytest

pytest.importorskip("mcp")

from pydantic import AnyUrl  # noqa: E402

from mcp.server.auth.provider import AuthorizationParams  # noqa: E402
from mcp.shared.auth import OAuthClientInformationFull  # noqa: E402

from mcp_server.oauth_provider import CodeKeeperOAuthProvider  # noqa: E402
from mcp_server.oauth_store import (
    ACCESS_PREFIX,
    REFRESH_PREFIX,
    OAuthStore,
    new_secret,
)  # noqa: E402


class _Res:
    def __init__(self, modified=0, upserted=None):
        self.modified_count = modified
        self.upserted_id = upserted


class _Coll:
    def __init__(self):
        self.docs = []
        self._id = 0

    def create_index(self, *a, **k):
        return "i"

    def insert_one(self, d):
        self._id += 1
        d = dict(d)
        d.setdefault("_id", self._id)
        self.docs.append(d)
        return _Res()

    @staticmethod
    def _match(doc, q):
        for k, v in q.items():
            if isinstance(v, dict) and "$ne" in v:
                if doc.get(k) == v["$ne"]:
                    return False
            elif doc.get(k) != v:
                return False
        return True

    def find_one(self, q):
        return next((d for d in self.docs if self._match(d, q)), None)

    def update_one(self, q, u, upsert=False):
        for d in self.docs:
            if self._match(d, q):
                d.update(u.get("$set", {}))
                return _Res(1)
        if upsert:
            self._id += 1
            nd = {"_id": self._id}
            for k, v in q.items():
                if not isinstance(v, dict):
                    nd[k] = v
            nd.update(u.get("$set", {}))
            self.docs.append(nd)
            return _Res(0, self._id)
        return _Res(0)

    def delete_one(self, q):
        for i, d in enumerate(self.docs):
            if self._match(d, q):
                self.docs.pop(i)
                return _Res(1)
        return _Res(0)


class _DB:
    def __init__(self):
        self.c = {}

    def __getitem__(self, name):
        return self.c.setdefault(name, _Coll())


def _pat(tok):
    return {"user_id": 7, "scopes": ["read"]} if tok == "ckmcp_good" else None


def _provider():
    store = OAuthStore(_DB())
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
    assert got is not None and str(got.redirect_uris[0]).startswith("https://claude.ai")
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
