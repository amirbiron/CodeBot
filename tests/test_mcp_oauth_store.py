"""Unit tests for the OAuth storage layer (fake Mongo, repo convention)."""

from datetime import datetime, timedelta, UTC

from mcp_server.oauth_store import ACCESS_PREFIX, OAuthStore, new_secret
from mcp_server.token_store import hash_token

try:  # local `tests` pkg can be shadowed by an unrelated top-level `tests` on sys.path
    from tests._fake_mongo import FakeDB
except ImportError:  # fall back to the sibling module (tests/ is on sys.path under pytest)
    from _fake_mongo import FakeDB


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


# ---------------------------------------------------------------------------
# האינדקסים — כל אחד נוצר לבד, וכשל של TTL או unique נרשם כ-ERROR
#
# אינדקסי ה-TTL על ``expires_at`` הם מה שמדיניות הפרטיות (``/privacy#mcp``) מתכוונת אליו ב-"Expired token records are deleted automatically". עד היום ``try`` אחד החזיק את כל שמונה הקריאות, וכשל באחת מהן דילג על כל מה שאחריה — כולל ה-TTL.
# ---------------------------------------------------------------------------

import logging  # noqa: E402

import pytest  # noqa: E402
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError  # noqa: E402


class _IndexRecordingCollection:
    """אוסף שרושם כל ``create_index`` — גם ניסיון שנכשל — ונכשל על מפתח שנבחר מראש, או על כולם (``"*"``)."""

    def __init__(self, name, fail_on, error, attempts):
        self.name, self._fail_on, self._error, self._attempts = name, fail_on, error, attempts
        self.created = []

    def create_index(self, keys, **options):
        self._attempts.append((self.name, keys))
        if self._fail_on == "*" or (self.name, keys) == self._fail_on:
            raise self._error
        self.created.append((keys, options))


class _IndexRecordingDB(dict):
    def __init__(self, fail_on=None, error=None):
        super().__init__()
        self._fail_on, self._error = fail_on, error
        self.attempts = []

    def __missing__(self, name):
        coll = self[name] = _IndexRecordingCollection(name, self._fail_on, self._error, self.attempts)
        return coll


_TTL = ("expires_at", {"expireAfterSeconds": 0})


@pytest.mark.parametrize(
    ("fail_on", "level"),
    [
        (("mcp_oauth_clients", "client_id"), logging.ERROR),  # הראשון ברשימה: unique
        (("mcp_oauth_tokens", "token_hash"), logging.ERROR),  # unique באוסף הטוקנים עצמו
        (("mcp_oauth_tokens", "subject"), logging.WARNING),  # אינדקס הביצועים היחיד
    ],
)
def test_one_failed_index_does_not_skip_the_ttl_indexes(caplog, fail_on, level):
    db = _IndexRecordingDB(fail_on=fail_on, error=OperationFailure("duplicate key", code=11000))

    with caplog.at_level(logging.WARNING, logger="mcp_server.oauth_store"):
        OAuthStore(db)

    for name in ("mcp_oauth_txns", "mcp_oauth_codes", "mcp_oauth_tokens"):
        assert _TTL in db[name].created, name
    failures = [r for r in caplog.records if r.getMessage().startswith("oauth_index_failed:")]
    assert len(failures) == 1, [r.getMessage() for r in failures]
    assert failures[0].levelno == level
    assert f"{fail_on[0]} {fail_on[1]}" in failures[0].getMessage()


def test_a_failed_ttl_index_is_logged_as_an_error(caplog):
    db = _IndexRecordingDB(fail_on=("mcp_oauth_tokens", "expires_at"), error=OperationFailure("IndexOptionsConflict", code=85))

    with caplog.at_level(logging.WARNING, logger="mcp_server.oauth_store"):
        OAuthStore(db)

    (failure,) = [r for r in caplog.records if r.getMessage().startswith("oauth_index_failed:")]
    assert failure.levelno == logging.ERROR
    assert "mcp_oauth_tokens expires_at" in failure.getMessage()
    # ושאר האינדקסים נוצרו
    assert ("token_hash", {"unique": True}) in db["mcp_oauth_tokens"].created


def test_an_error_that_is_not_from_the_database_is_not_swallowed():
    """רק ``PyMongoError`` הוא "המסד סירב או לא ענה". חריגה אחרת היא באג, והיא עולה."""
    db = _IndexRecordingDB(fail_on=("mcp_oauth_codes", "code_hash"), error=TypeError("bad index spec"))

    with pytest.raises(TypeError):
        OAuthStore(db)


def test_an_unreachable_database_is_asked_once_and_not_once_per_index(caplog):
    """כשהמסד לא עונה, כל קריאה נוספת הייתה מחכה שוב את ``serverSelectionTimeoutMS`` — פעם אחת לכל אינדקס במקום פעם אחת בעלייה.

    ``ServerSelectionTimeoutError`` הוא מה ש-pymongo זורק כשאין שרת לבחור, והוא תת-מחלקה של ``ConnectionFailure`` (נבדק ב-``__mro__``, pymongo 4.15.3). אחרי הניסיון הראשון הלולאה עוצרת, ושורת ERROR אחת נוקבת בכל האינדקסים שלא נוסו, כולל ה-TTL.
    """
    db = _IndexRecordingDB(fail_on="*", error=ServerSelectionTimeoutError("no servers"))

    with caplog.at_level(logging.WARNING, logger="mcp_server.oauth_store"):
        OAuthStore(db)

    assert db.attempts == [("mcp_oauth_clients", "client_id")]
    (failure,) = [r for r in caplog.records if r.getMessage().startswith("oauth_index_failed:")]
    assert failure.levelno == logging.ERROR
    message = failure.getMessage()
    assert "database unreachable" in message
    for declared in (
        "mcp_oauth_clients client_id",
        "mcp_oauth_txns txn_id",
        "mcp_oauth_codes code_hash",
        "mcp_oauth_tokens token_hash",
        "mcp_oauth_tokens subject",
        "mcp_oauth_txns expires_at",
        "mcp_oauth_codes expires_at",
        "mcp_oauth_tokens expires_at",
    ):
        assert declared in message, declared


_PRODUCT_DIRS_TO_SKIP = {"tests", "docs", "node_modules", "__pycache__"}


def test_nothing_outside_the_store_names_its_collections():
    """ה-docstring של ``_ensure_indexes`` אומר שכל כתיבה לארבעת האוספים היא מתודה של ``OAuthStore``, ולכן עוברת דרך הבנאי שמבקש את האינדקסים.

    כתיבה מבחוץ הייתה צריכה את שם האוסף — כמחרוזת, או דרך ``TOKENS_COLLECTION``. כאן נסרק כל קובץ פייתון של המוצר, וחוץ מ-``mcp_server/oauth_store.py`` אף אחד לא נוקב בשמות. קוד שיפנה לאוסף מבחוץ מפיל את הטסט, ואז צריך להעביר את הכתיבה לתוך המחלקה, או לעדכן את ה-docstring ואת ``mcp-privacy-page`` ב-``docs/mcp-server.rst``.
    """
    import os
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    pattern = re.compile(r"mcp_oauth_(clients|txns|codes|tokens)|\bTOKENS_COLLECTION\b")
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in _PRODUCT_DIRS_TO_SKIP]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = Path(dirpath) / filename
            if path == root / "mcp_server" / "oauth_store.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if pattern.search(text):
                hits.append(str(path.relative_to(root)))
    assert hits == [], hits
