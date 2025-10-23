import importlib
import sys
import types
from datetime import datetime, timezone


def _install_fake_pymongo(monkeypatch, docs):
    class _Coll:
        def __init__(self):
            self._docs = list(docs)

        def create_index(self, *a, **k):  # noqa: D401
            return None

        def find(self, *a, **k):  # noqa: D401
            class _Cursor:
                def __init__(self, docs):
                    self._docs = docs

                def sort(self, *_a, **_k):
                    return self

                def limit(self, *_a, **_k):
                    return self

                def __iter__(self):
                    return iter(self._docs)

            return _Cursor(self._docs)

        def count_documents(self, *a, **k):  # noqa: D401
            return len(self._docs)

        def update_one(self, *a, **k):  # noqa: D401
            return types.SimpleNamespace(matched_count=1)

        def insert_one(self, *a, **k):  # noqa: D401
            return types.SimpleNamespace(inserted_id=1)

    class _DB:
        def __getitem__(self, name):
            return _Coll()

    class _Client:
        def __init__(self, *a, **k):
            self.admin = types.SimpleNamespace(command=lambda *a, **k: {"ok": 1})

        def __getitem__(self, name):
            return _DB()

    monkeypatch.setitem(sys.modules, "pymongo", types.SimpleNamespace(MongoClient=_Client, ASCENDING=1))


def _import_fresh(monkeypatch):
    sys.modules.pop("monitoring.alerts_storage", None)
    return importlib.import_module("monitoring.alerts_storage")


def test_list_recent_alert_ids_prefers_alert_id(monkeypatch):
    docs = [
        {"ts_dt": datetime.now(timezone.utc), "alert_id": "id-xyz", "_key": "h:1"},
        {"ts_dt": datetime.now(timezone.utc), "_key": "h:2"},
    ]
    _install_fake_pymongo(monkeypatch, docs)

    # Enable DB and URL
    monkeypatch.setenv("ALERTS_DB_ENABLED", "1")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017")

    mod = _import_fresh(monkeypatch)
    ids = mod.list_recent_alert_ids(limit=10)
    assert isinstance(ids, list)
    # Prefer explicit alert_id when present
    assert "id-xyz" in ids
    # Fallback to _key when alert_id missing
    assert any(i.startswith("h:") for i in ids)


def test_list_recent_alert_ids_handles_errors(monkeypatch):
    # pymongo import ok, but collection returns cursor that raises
    class _BadCursor:
        def sort(self, *a, **k):
            return self
        def limit(self, *a, **k):
            return self
        def __iter__(self):
            raise RuntimeError("boom")

    class _BadColl:
        def find(self, *a, **k):
            return _BadCursor()

    class _BadDB:
        def __getitem__(self, name):
            return _BadColl()

    class _Client:
        def __init__(self, *a, **k):
            self.admin = types.SimpleNamespace(command=lambda *a, **k: {"ok": 1})
        def __getitem__(self, name):
            return _BadDB()

    monkeypatch.setitem(sys.modules, "pymongo", types.SimpleNamespace(MongoClient=_Client, ASCENDING=1))
    # Enable
    monkeypatch.setenv("ALERTS_DB_ENABLED", "1")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017")

    mod = _import_fresh(monkeypatch)
    ids = mod.list_recent_alert_ids(limit=10)
    # Fail-open: return [] on errors
    assert ids == []


def test_list_recent_alert_ids_limit_zero_or_disabled(monkeypatch):
    # Disabled DB -> should return []
    monkeypatch.setenv("ALERTS_DB_ENABLED", "0")
    monkeypatch.delenv("MONGODB_URL", raising=False)
    mod = _import_fresh(monkeypatch)
    assert mod.list_recent_alert_ids(limit=0) == []
