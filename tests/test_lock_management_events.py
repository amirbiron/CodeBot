import types
import pytest
from datetime import datetime, timezone, timedelta


def test_ensure_lock_indexes_emits_on_failure(monkeypatch):
    import main as mod

    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)

    class _Coll:
        def create_index(self, *a, **k):
            raise RuntimeError("index fail")
    monkeypatch.setattr(mod, "get_lock_collection", lambda: _Coll(), raising=False)

    mod.ensure_lock_indexes()

    assert any(e[0] == "lock_ttl_index_failed" for e in captured.get("events", []))


def test_cleanup_mongo_lock_emits_released(monkeypatch):
    import main as mod

    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)

    class _Res:
        deleted_count = 1
    class _Coll:
        def delete_one(self, *a, **k):
            return _Res()
    # ensure we don't early-return due to missing client
    monkeypatch.setattr(mod, "db", types.SimpleNamespace(client=object()), raising=False)
    monkeypatch.setattr(mod, "get_lock_collection", lambda: _Coll(), raising=False)

    mod.cleanup_mongo_lock()

    assert any(e[0] == "lock_released" for e in captured.get("events", []))


def test_cleanup_mongo_lock_client_closed_emits(monkeypatch):
    import main as mod

    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)

    class _Coll:
        def delete_one(self, *a, **k):
            raise mod.pymongo.errors.InvalidOperation()
    monkeypatch.setattr(mod, "db", types.SimpleNamespace(client=object()), raising=False)
    monkeypatch.setattr(mod, "get_lock_collection", lambda: _Coll(), raising=False)

    mod.cleanup_mongo_lock()

    assert any(e[0] == "lock_cleanup_skipped_client_closed" for e in captured.get("events", []))


def test_cleanup_mongo_lock_generic_error_emits(monkeypatch):
    import main as mod

    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)

    class _Coll:
        def delete_one(self, *a, **k):
            raise RuntimeError("boom")
    monkeypatch.setattr(mod, "db", types.SimpleNamespace(client=object()), raising=False)
    monkeypatch.setattr(mod, "get_lock_collection", lambda: _Coll(), raising=False)

    mod.cleanup_mongo_lock()

    assert any(e[0] == "lock_release_error" for e in captured.get("events", []))


def test_manage_mongo_lock_acquired_emits(monkeypatch):
    import main as mod

    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)

    # skip ttl indexing to focus on acquire branch
    monkeypatch.setattr(mod, "ensure_lock_indexes", lambda: None, raising=False)

    class _Coll:
        def insert_one(self, *a, **k):
            return None
    monkeypatch.setattr(mod, "get_lock_collection", lambda: _Coll(), raising=False)

    ok = mod.manage_mongo_lock()
    assert ok is True
    assert any(e[0] == "lock_acquired" for e in captured.get("events", []))


def test_manage_mongo_lock_reacquired_emits(monkeypatch):
    import main as mod

    captured = {}
    def _emit(event, severity="info", **fields):
        captured.setdefault("events", []).append((event, severity, fields))
    monkeypatch.setattr(mod, "emit_event", _emit, raising=False)

    monkeypatch.setattr(mod, "ensure_lock_indexes", lambda: None, raising=False)

    class _Coll:
        def insert_one(self, *a, **k):
            raise mod.DuplicateKeyError()
        def find_one(self, *a, **k):
            # not expired if expires in future; to trigger takeover need expired
            return {"expires_at": datetime.now(timezone.utc) - timedelta(minutes=10)}
        def find_one_and_update(self, *a, **k):
            return {"_id": "ok"}
    monkeypatch.setattr(mod, "get_lock_collection", lambda: _Coll(), raising=False)

    ok = mod.manage_mongo_lock()
    assert ok is True
    assert any(e[0] == "lock_reacquired" for e in captured.get("events", []))
