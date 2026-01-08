import os
import pytest


class _DummyLogger:
    def __init__(self):
        self.records = []

    def warning(self, msg, extra=None):
        self.records.append(("warning", msg, extra or {}))

    def error(self, msg, extra=None):
        self.records.append(("error", msg, extra or {}))


def test_db_manager_profiler_runs_when_slow_mongo_disabled(monkeypatch):
    """
    אם DB_SLOW_MS=0 (כלומר slow_mongo מושתק), הפרופיילר עדיין צריך לעבוד
    לפי PROFILER_SLOW_THRESHOLD_MS.
    """
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/db")

    # Disable slow_mongo logs
    monkeypatch.setenv("DB_SLOW_MS", "0")

    # Enable profiler and set low threshold to trigger easily
    monkeypatch.setenv("PROFILER_ENABLED", "true")
    monkeypatch.setenv("PROFILER_SLOW_THRESHOLD_MS", "0.1")

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

    # Ensure registration block runs
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

    # Patch the module logger to capture warning/error
    dlog = _DummyLogger()
    monkeypatch.setattr(dm, "logger", dlog)

    # Patch profiler service class used by DatabaseManager (imported lazily)
    called = {"count": 0}

    class _DummyProfiler:
        def __init__(self, *args, **kwargs):
            pass

        async def record_slow_query(self, **kwargs):
            called["count"] += 1
            return None

    import services.query_profiler_service as qps

    monkeypatch.setattr(qps, "PersistentQueryProfilerService", _DummyProfiler)

    # Act: init manager to register listener
    dm.DatabaseManager()
    listener = registered.get("listener")
    assert listener is not None

    # Provide request context via started()
    class _StartedEvent:
        request_id = 123
        command_name = "find"
        database_name = "db"
        command = {"find": "users", "filter": {"user_id": 1}}

    listener.started(_StartedEvent())

    # Trigger succeeded with duration above profiler threshold
    class _SucceededEvent:
        request_id = 123
        duration_micros = 500.0  # 0.5 ms
        command_name = "find"
        database_name = "db"

    listener.succeeded(_SucceededEvent())

    # Assert: profiler ran even though slow_mongo is disabled
    assert called["count"] == 1

    # Assert: no slow_mongo warning was emitted
    assert not any(level == "warning" and msg == "slow_mongo" for level, msg, _ in dlog.records)

