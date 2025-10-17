import types
import importlib
import pytest


def _reload_main(monkeypatch):
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    monkeypatch.setenv('DISABLE_DB', '1')
    import main as mod
    import importlib as _il
    _il.reload(mod)
    return mod


def test_cleanup_returns_true_when_no_client(monkeypatch):
    mod = _reload_main(monkeypatch)

    # העמדת db ללא client כדי לדלג — אמור להיחשב כהצלחה
    class _DB:
        client = None
    monkeypatch.setattr(mod, 'db', _DB(), raising=False)

    assert mod.cleanup_mongo_lock() is True


def test_cleanup_returns_true_when_no_doc_deleted(monkeypatch):
    mod = _reload_main(monkeypatch)

    class _Res:
        deleted_count = 0
    class _Coll:
        def delete_one(self, *a, **k):
            return _Res()
    monkeypatch.setattr(mod, 'get_lock_collection', lambda: _Coll(), raising=False)

    # העמדת db עם client כדי לא לדלג
    class _DB:
        client = object()
    monkeypatch.setattr(mod, 'db', _DB(), raising=False)

    assert mod.cleanup_mongo_lock() is True


def test_cleanup_returns_false_on_invalid_operation(monkeypatch):
    mod = _reload_main(monkeypatch)

    class _Coll:
        def delete_one(self, *a, **k):
            raise mod.pymongo.errors.InvalidOperation()
    monkeypatch.setattr(mod, 'get_lock_collection', lambda: _Coll(), raising=False)

    class _DB:
        client = object()
    monkeypatch.setattr(mod, 'db', _DB(), raising=False)

    assert mod.cleanup_mongo_lock() is False


def test_cleanup_returns_false_on_generic_error(monkeypatch):
    mod = _reload_main(monkeypatch)

    class _Coll:
        def delete_one(self, *a, **k):
            raise RuntimeError('boom')
    monkeypatch.setattr(mod, 'get_lock_collection', lambda: _Coll(), raising=False)

    class _DB:
        client = object()
    monkeypatch.setattr(mod, 'db', _DB(), raising=False)

    assert mod.cleanup_mongo_lock() is False
