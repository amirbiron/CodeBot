"""Unit tests for the MCP Personal Access Token store.

Uses a tiny hand-rolled fake Mongo collection (the repo convention — no
mongomock dependency).
"""

from datetime import UTC, datetime, timedelta

from mcp_server.token_store import TOKEN_PREFIX, MCPTokenStore, hash_token


class _Result:
    def __init__(self, modified=0):
        self.modified_count = modified


class _FakeCollection:
    def __init__(self):
        self.docs = []
        self._seq = 0

    def create_index(self, *a, **k):
        return "idx"

    def insert_one(self, doc):
        self._seq += 1
        doc = dict(doc)
        doc.setdefault("_id", self._seq)
        self.docs.append(doc)
        return _Result()

    @staticmethod
    def _match(doc, query):
        for key, cond in query.items():
            if isinstance(cond, dict) and "$ne" in cond:
                if doc.get(key) == cond["$ne"]:
                    return False
            elif doc.get(key) != cond:
                return False
        return True

    def find_one(self, query):
        for d in self.docs:
            if self._match(d, query):
                return d
        return None

    def find(self, query):
        return [d for d in self.docs if self._match(d, query)]

    def update_one(self, query, update):
        for d in self.docs:
            if self._match(d, query):
                d.update(update.get("$set", {}))
                return _Result(1)
        return _Result(0)


class _FakeDB:
    def __init__(self):
        self._collections = {}

    def __getitem__(self, name):
        return self._collections.setdefault(name, _FakeCollection())


def _store():
    return MCPTokenStore(_FakeDB())


def test_issue_returns_prefixed_raw_and_stores_hash_only():
    store = _store()
    raw = store.issue(111, label="Claude")
    assert raw.startswith(TOKEN_PREFIX)
    doc = store._coll.docs[0]
    assert doc["token_hash"] == hash_token(raw)
    assert "token" not in doc  # raw value is never persisted
    assert doc["user_id"] == 111
    assert doc["scopes"] == ["read"]


def test_verify_roundtrip():
    store = _store()
    raw = store.issue(222)
    assert store.verify(raw) == {"user_id": 222, "scopes": ["read"]}


def test_verify_wrong_or_empty_token_returns_none():
    store = _store()
    store.issue(1)
    assert store.verify("ckmcp_nope") is None
    assert store.verify("") is None


def test_revoked_token_is_denied():
    store = _store()
    raw = store.issue(5)
    token_id = store._coll.docs[0]["_id"]
    assert store.revoke(5, token_id) is True
    assert store.verify(raw) is None


def test_expired_token_is_denied():
    store = _store()
    raw = store.issue(7, ttl_days=1)
    store._coll.docs[0]["expires_at"] = datetime.now(UTC) - timedelta(days=2)
    assert store.verify(raw) is None


def test_verify_updates_last_used():
    store = _store()
    raw = store.issue(8)
    assert store._coll.docs[0]["last_used_at"] is None
    store.verify(raw)
    assert store._coll.docs[0]["last_used_at"] is not None


def test_list_for_user_hides_secrets():
    store = _store()
    store.issue(9, label="A")
    rows = store.list_for_user(9)
    assert len(rows) == 1
    assert "token_hash" not in rows[0] and "token" not in rows[0]
    assert rows[0]["label"] == "A"
    assert rows[0]["token_prefix"].startswith(TOKEN_PREFIX)
    assert store.list_for_user(999) == []
