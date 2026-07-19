"""Unit tests for the OAuth storage layer (fake Mongo, repo convention)."""

from datetime import datetime, timedelta, UTC

from mcp_server.oauth_store import ACCESS_PREFIX, OAuthStore, new_secret
from mcp_server.token_store import hash_token


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


def _store():
    return OAuthStore(_DB())


def _past(store_coll):
    store_coll.docs[0]["expires_at"] = datetime.now(UTC) - timedelta(hours=1)


def test_client_roundtrip():
    s = _store()
    s.save_client({"client_id": "c1", "redirect_uris": ["https://x/cb"], "client_secret": "sec"})
    got = s.get_client("c1")
    assert got["redirect_uris"] == ["https://x/cb"]
    assert "_id" not in got
    assert s.get_client("nope") is None


def test_txn_lifecycle_and_expiry():
    s = _store()
    txn_id = s.create_txn({"client_id": "c1", "redirect_uri": "https://x/cb", "state": "st"})
    assert s.get_txn(txn_id)["state"] == "st"
    s.delete_txn(txn_id)
    assert s.get_txn(txn_id) is None
    # expiry
    tid2 = s.create_txn({"client_id": "c1"})
    _past(s._txns)
    assert s.get_txn(tid2) is None


def test_code_peek_then_consume():
    s = _store()
    code = new_secret("ckoc_")
    s.save_code(code, {"client_id": "c1", "subject": "42", "code_challenge": "abc"})
    peek = s.get_code(code)
    assert peek["subject"] == "42" and peek["code_challenge"] == "abc"
    assert "_id" not in peek
    # peek does not consume
    assert s.get_code(code) is not None
    s.delete_code(code)
    assert s.get_code(code) is None  # consumed
    assert s._codes.find_one({"code_hash": hash_token(code)}) is None


def test_code_expiry():
    s = _store()
    code = new_secret("ckoc_")
    s.save_code(code, {"client_id": "c1", "subject": "42"})
    _past(s._codes)
    assert s.get_code(code) is None


def test_token_kind_isolation_and_revoke():
    s = _store()
    at = new_secret(ACCESS_PREFIX)
    s.save_token(at, kind="access", data={"client_id": "c1", "subject": "42", "scopes": ["read"]})
    assert s.get_token(at, kind="access")["subject"] == "42"
    assert s.get_token(at, kind="refresh") is None  # wrong kind
    s.revoke_token(at)
    assert s.get_token(at, kind="access") is None


def test_access_token_expiry():
    s = _store()
    at = new_secret(ACCESS_PREFIX)
    s.save_token(at, kind="access", data={"client_id": "c1", "subject": "42"})
    _past(s._tokens)
    assert s.get_token(at, kind="access") is None
