import importlib


def test_invalidate_user_cache_patterns(monkeypatch):
    import cache_manager as cm
    importlib.reload(cm)

    class _FakeRedis:
        def __init__(self):
            self.store = {
                'user_files:func:obj:42:x': '1',
                'latest_version:func:obj:42:y': '1',
                'search_code:func:obj:42:z': '1',
                'user_stats:func:obj:42': '1',
                'misc': '1',
            }
        def keys(self, pattern):
            import fnmatch
            return [k for k in list(self.store.keys()) if fnmatch.fnmatch(k, pattern)]
        def delete(self, *keys):
            cnt = 0
            for k in keys:
                if k in self.store:
                    del self.store[k]
                    cnt += 1
            return cnt
        def ping(self):
            return True
    r = _FakeRedis()

    cm.cache.is_enabled = True
    cm.cache.redis_client = r

    n = cm.cache.invalidate_user_cache(42)
    assert isinstance(n, int)
    assert n >= 3
