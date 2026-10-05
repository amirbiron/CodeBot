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


def test_noop_update_results_carry_every_property_of_pymongo_update_result():
    """קוראים של ``update_one`` / ``update_many`` בודקים ``matched_count`` ו-``upserted_id`` כדי לדעת אם משהו נכתב. תוצאה של מצב ה-no-op בלי השדות האלה הפילה אותם ב-``AttributeError`` — למשל "חבר ל-Drive" בוובאפ כשמונגו לא היה זמין בעלייה — במקום תשובת השגיאה שהם מחזירים כשלא נכתב כלום.

    הרשימה נגזרת מ-``UpdateResult`` של הגרסה המותקנת, כך ששדרוג שמוסיף תכונה מפיל את הטסט הזה ולא את הקוראים.
    """
    import inspect

    from pymongo.results import UpdateResult

    import database.manager as dm

    properties = sorted(name for name, value in inspect.getmembers(UpdateResult) if isinstance(value, property) and not name.startswith("_"))
    assert {"acknowledged", "matched_count", "modified_count", "upserted_id"} <= set(properties)
    for collection in (dm.NoOpCollection(), dm._StubCollection()):
        for result in (collection.update_one({"a": 1}, {"$set": {"b": 2}}, upsert=True), collection.update_many({"a": 1}, {"$set": {"b": 2}})):
            assert [name for name in properties if not hasattr(result, name)] == [], type(collection).__name__
            assert result.acknowledged is True
            assert (result.matched_count, result.modified_count, result.upserted_id) == (0, 0, None)
