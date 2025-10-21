import importlib
import types


def test_cache_timer_context_calls(monkeypatch):
    # Reload module to pick latest code
    import cache_manager as cm
    importlib.reload(cm)

    # Patch prometheus Histogram.time to return a callable we can track
    called = {"stops": 0}

    class _FakeHist:
        def labels(self, **kw):
            def _time():
                def _stop():
                    called["stops"] += 1
                return _stop
            return types.SimpleNamespace(time=_time)
    monkeypatch.setattr(cm, 'cache_op_duration_seconds', _FakeHist())

    # Patch redis client and enable cache
    class _FakeRedis:
        def __init__(self):
            self.store = {}
        def get(self, k):
            return None
        def setex(self, *a, **k):
            return True
        def delete(self, *a, **k):
            return 1
        def keys(self, pattern):
            return []
        def ping(self):
            return True

    r = _FakeRedis()
    cm.cache.is_enabled = True
    cm.cache.redis_client = r

    # Exercise methods to ensure timer stop callable invoked
    cm.cache.get("k")
    cm.cache.set("k", {"a": 1})
    cm.cache.delete("k")
    cm.cache.delete_pattern("p*")

    # We called timer stop 4 times (get/set/delete/delete_pattern)
    assert called["stops"] == 4
