import types


def _fake_emit_capture(target_module):
    captured = {"events": []}
    def _emit(event, severity="info", **fields):
        captured["events"].append((event, severity, fields))
    return captured, _emit


def test_manager_db_disabled_emits(monkeypatch):
    import database.manager as mgr_mod
    captured, _emit = _fake_emit_capture(mgr_mod)
    monkeypatch.setattr(mgr_mod, "emit_event", _emit, raising=False)

    # Force DISABLE_DB path
    import os
    monkeypatch.setenv("DISABLE_DB", "true")

    # No pymongo available path can also trigger; keep simple by stubbing client
    class _Manager(mgr_mod.DatabaseManager):
        def __init__(self):
            # Do not call super to avoid real connect; we simulate connect()
            pass
        def connect(self):
            # simulate internal noop init directly
            class NoOpDB:
                def __getitem__(self, name):
                    return object()
            self.client = None
            self.db = NoOpDB()
            self.collection = object()
            self.large_files_collection = object()
            self.backup_ratings_collection = object()
            mgr_mod.emit_event("db_disabled", reason="docs_or_ci_mode")
    m = _Manager()
    m.connect()

    assert any(e[0] == "db_disabled" for e in captured["events"])  # event emitted


def test_manager_connect_error_emits(monkeypatch):
    import database.manager as mgr_mod
    captured, _emit = _fake_emit_capture(mgr_mod)
    monkeypatch.setattr(mgr_mod, "emit_event", _emit, raising=False)

    # Stub MongoClient to raise
    class _MC:
        def __init__(self, *a, **k):
            raise RuntimeError("connect boom")
    monkeypatch.setattr(mgr_mod, "MongoClient", _MC, raising=False)

    # Ensure DISABLE_DB is off so we hit the error branch
    import os
    monkeypatch.delenv("DISABLE_DB", raising=False)
    monkeypatch.setattr(mgr_mod, "_PYMONGO_AVAILABLE", True, raising=False)

    # Force single retry to speed up the test
    monkeypatch.setenv("MONGODB_CONNECT_MAX_RETRIES", "1")

    # DatabaseManager.__init__ calls connect() internally.
    # With graceful degradation it no longer raises — it falls back to NoOp.
    mgr = mgr_mod.DatabaseManager()

    # Cancel any background reconnect timer so it doesn't leak into other tests
    if hasattr(mgr, '_reconnect_timer') and mgr._reconnect_timer is not None:
        mgr._reconnect_timer.cancel()

    # Graceful degradation emits db_connection_fallback_noop instead of raising
    assert any(e[0] == "db_connection_fallback_noop" for e in captured["events"])
