import sys
import importlib


def test_noop_db_allows_attribute_and_item_access(monkeypatch):
    # Arrange env so DatabaseManager uses no-op path without requiring a real DB
    monkeypatch.setenv("DISABLE_DB", "1")
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017")

    # Import module fresh to pick up env flags
    if "database.manager" in sys.modules:
        importlib.reload(sys.modules["database.manager"])  # pragma: no cover
    else:
        import database.manager  # noqa: F401
    import database.manager as dm

    mgr = dm.DatabaseManager()

    # __getattr__ path: attribute access should yield a NoOpCollection
    users = mgr.db.users
    assert users.find_one({}) is None
    assert getattr(users.delete_one({}), "deleted_count", 0) == 0

    # __getitem__ path: bracket access should return a collection, create_index is a no-op
    locks = mgr.db["locks"]
    assert locks.create_index("expires_at") is None


def test_noop_db_when_pymongo_unavailable(monkeypatch):
    # Simulate missing pymongo by toggling the availability flag
    monkeypatch.setenv("DISABLE_DB", "")
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017")

    if "database.manager" in sys.modules:
        dm = sys.modules["database.manager"]
    else:
        import database.manager as dm  # type: ignore

    # Force the no-op branch that checks the availability flag
    dm._PYMONGO_AVAILABLE = False  # type: ignore[attr-defined]

    mgr = dm.DatabaseManager()
    # Name property should exist on the no-op DB stub
    assert getattr(mgr.db, "name", "") == "noop_db"


def test_a_disabled_database_is_connected_but_not_real(monkeypatch):
    """``is_connected`` הוא ``True`` גם בניטרול מכוון, כי לולאת ההמתנה שב-``main()``
    נשענת על זה. לכן "האם כתיבה מגיעה למסד" נשאל דרך ``has_real_database``."""
    monkeypatch.setenv("DISABLE_DB", "1")
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017")

    import database.manager as dm

    mgr = dm.DatabaseManager()
    assert mgr.is_connected is True
    assert mgr.has_real_database is False


def test_a_connected_database_that_is_not_noop_is_real(monkeypatch):
    """הצד השני, כדי שתכונה שתמיד מחזירה ``False`` לא תעבור: המצב שהחיבור
    מחדש ברקע מציב (מסד אמיתי ודגל דלוק), ואחריו המצב ש-``close()`` משאיר."""
    monkeypatch.setenv("DISABLE_DB", "1")
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017")

    import database.manager as dm

    mgr = dm.DatabaseManager()
    mgr.db = object()  # כל מסד שאינו NoOpDB
    mgr._db_connected = True
    assert mgr.has_real_database is True

    mgr._db_connected = False
    assert mgr.has_real_database is False


def test_noop_db_private_attr_raises(monkeypatch):
    # Ensure attribute names starting with '_' raise AttributeError per stub contract
    monkeypatch.setenv("DISABLE_DB", "1")
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017")

    import database.manager as dm
    mgr = dm.DatabaseManager()

    import pytest
    with pytest.raises(AttributeError):
        _ = mgr.db._hidden_collection
