"""Unit tests for the OAuth storage layer (fake Mongo, repo convention)."""

from datetime import datetime, timedelta, UTC

from mcp_server.oauth_store import ACCESS_PREFIX, OAuthStore, new_secret
from mcp_server.token_store import hash_token
from tests._fake_mongo import FakeDB


def _store():
    return OAuthStore(FakeDB())


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
    assert s.delete_code(code) is True  # first consume wins
    assert s.delete_code(code) is False  # replay: nothing left to delete
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
    assert s.revoke_token(at) is True  # first revoke flips a live row
    assert s.revoke_token(at) is False  # replay: already revoked
    assert s.get_token(at, kind="access") is None


def test_access_token_expiry():
    s = _store()
    at = new_secret(ACCESS_PREFIX)
    s.save_token(at, kind="access", data={"client_id": "c1", "subject": "42"})
    _past(s._tokens)
    assert s.get_token(at, kind="access") is None
