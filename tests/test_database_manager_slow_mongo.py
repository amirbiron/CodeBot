import types
import os
import pytest


class _DummyLogger:
    def __init__(self):
        self.records = []
    def warning(self, msg, extra=None):
        self.records.append((msg, extra or {}))


def test_db_manager_registers_and_logs_slow_mongo(monkeypatch):
    # Arrange
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/db")
    monkeypatch.setenv("DB_SLOW_MS", "0.1")

    # Ensure DB is not disabled
    monkeypatch.setenv("DISABLE_DB", "0")
    monkeypatch.setenv("SPHINX_MOCK_IMPORTS", "0")

    import database.manager as dm

    # Force pymongo available path and inject fake monitoring API
    monkeypatch.setattr(dm, "_PYMONGO_AVAILABLE", True)

    registered = {}
    class _Monitoring:
        class CommandListener:
            pass
        def register(self, listener):
            registered["listener"] = listener
    monkeypatch.setattr(dm, "_pymongo_monitoring", _Monitoring(), raising=False)

    # Ensure block runs
    monkeypatch.setattr(dm, "_MONGO_MONITORING_REGISTERED", False, raising=False)

    # Stub MongoClient to avoid real connections
    class _Coll:
        def create_indexes(self, *a, **k):
            return None
        def list_indexes(self, *a, **k):
            return []

    class _DB:
        def __init__(self):
            self.code_snippets = _Coll()
            self.large_files = _Coll()
            self.backup_ratings = _Coll()
            self.internal_shares = _Coll()
        def __getitem__(self, name):
            return _Coll()
        def __getattr__(self, name):
            return _Coll()

    class _Client:
        def __init__(self, *a, **k):
            pass
        def __getitem__(self, name):
            return _DB()
        @property
        def admin(self):
            class _Admin:
                def command(self, *a, **k):
                    return {"ok": 1}
            return _Admin()
    monkeypatch.setattr(dm, "MongoClient", _Client)

    # Avoid heavy index creation
    monkeypatch.setattr(dm.DatabaseManager, "_create_indexes", lambda self: None)

    # Patch the module logger to capture warnings
    dlog = _DummyLogger()
    monkeypatch.setattr(dm, "logger", dlog)

    # Act
    mgr = dm.DatabaseManager()  # triggers connect() and registration

    # Simulate a succeeded event that is slow
    listener = registered.get("listener")
    assert listener is not None
    class _Event:
        duration_micros = 500.0  # 0.5 ms
        command_name = "find"
        database_name = "db"
    listener.succeeded(_Event())

    # Assert we logged slow_mongo
    assert any(msg == "slow_mongo" for msg, _ in dlog.records)
