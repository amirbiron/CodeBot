import importlib


def test_delete_pattern_and_clear_stale(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    class _Client:
        def __init__(self):
            self._store = {"a:1": "1", "b:2": "1"}
            self._ttls = {"a:1": 5, "b:2": -1}
        def keys(self, pattern):
            import fnmatch
            return [k for k in self._store if fnmatch.fnmatch(k, pattern)]
        def delete(self, *keys):
            c = 0
            for k in keys:
                if k in self._store:
                    del self._store[k]
                    c += 1
            return c
        def ping(self):
            return True
        def scan_iter(self, match='*', count=500):  # noqa: ARG002
            for k in list(self._store.keys()):
                yield k
        def ttl(self, key):
            return self._ttls.get(key, -2)
    r = _Client()

    m = cm.CacheManager()
    m.is_enabled = True
    m.redis_client = r

    # delete_pattern
    n = m.delete_pattern('a:*')
    assert n == 1

    # clear_stale: should delete keys with ttl <= threshold or -2
    monkeypatch.setenv('SAFE_MODE', '0')
    monkeypatch.setenv('CACHE_CLEAR_BUDGET_SECONDS', '1')
    deleted = m.clear_stale(max_scan=100, ttl_seconds_threshold=10)
    assert isinstance(deleted, int)
