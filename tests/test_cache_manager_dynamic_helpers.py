import importlib


def test_get_with_refresh_calls_refresh_on_miss(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    class _Dummy:
        def __init__(self):
            self.store = {}
            self.is_enabled = True
        def get(self, k):
            return self.store.get(k)
        def set(self, k, v, s):  # noqa: ARG002 - expire seconds unused in test
            self.store[k] = v
            return True

    cm.cache.is_enabled = True
    cm.cache.redis_client = None  # not used here

    mgr = cm.CacheManager()
    mgr.is_enabled = True
    mgr.redis_client = None

    # monkeypatch the instance methods to avoid real redis
    mgr.get = _Dummy().get  # type: ignore
    stored = {}
    def _fake_set(key, value, expire_seconds=300):  # noqa: ARG001
        stored[key] = value
        return True
    mgr.set = _fake_set  # type: ignore

    # refresh function
    calls = {"n": 0}
    def _refresh():
        calls["n"] += 1
        return {"v": 1}

    # Miss -> refresh called and value set
    out = mgr.get_with_refresh("k1", _refresh, content_type="user_stats", context={"user_tier": "regular"})
    assert out == {"v": 1}
    assert calls["n"] == 1
    assert stored.get("k1") == {"v": 1}
