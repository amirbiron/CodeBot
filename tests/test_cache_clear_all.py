import types
import importlib


def test_cache_clear_all_scans_and_deletes(monkeypatch):
    cm = importlib.import_module('cache_manager')

    # Avoid real connect in __init__
    monkeypatch.setattr(cm.CacheManager, 'connect', lambda self: None)
    mgr = cm.CacheManager()
    mgr.is_enabled = True

    deleted = {"count": 0}
    class _FakeRedis:
        def scan_iter(self, match='*', count=10):
            yield from ["k1", "k2", "k3"]
        def delete(self, key):
            deleted["count"] += 1
            return 1
        def keys(self, pattern):
            return ["k1", "k2"]

    mgr.redis_client = _FakeRedis()

    n = mgr.clear_all()
    assert n >= 2
    assert deleted["count"] >= 2
