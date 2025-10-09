import types
import os
import json
import pytest

from cache_manager import CacheManager, cached, cache

class DummyRedis:
    def __init__(self):
        self.store = {}
    def ping(self):
        return True
    def get(self, k):
        return self.store.get(k)
    def setex(self, k, ttl, v):
        self.store[k] = v
        return True
    def delete(self, *keys):
        cnt = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                cnt += 1
        return cnt
    def keys(self, pattern):
        # super naive glob: support '*' only
        if pattern == '*':
            return list(self.store.keys())
        prefix = pattern.split('*')[0]
        return [k for k in self.store.keys() if k.startswith(prefix)]
    def info(self):
        return {
            'used_memory_human': '1M',
            'connected_clients': 1,
            'keyspace_hits': 1,
            'keyspace_misses': 1,
        }
    def set(self, k, v, ex=None):
        self.store[k] = v
        return True
    def expire(self, k, ex):
        return True

@pytest.fixture(autouse=True)
def _env_redis(monkeypatch):
    # ensure cache operates in enabled mode with dummy client
    os.environ['REDIS_URL'] = 'redis://dummy'
    cm = CacheManager()
    monkeypatch.setattr(cm, 'redis_client', DummyRedis(), raising=True)
    monkeypatch.setattr(cm, 'is_enabled', True, raising=True)
    # swap global cache instance to our monkeypatched one
    import cache_manager as cm_mod
    monkeypatch.setattr(cm_mod, 'cache', cm, raising=True)
    return cm

def test_cache_set_get_delete(_env_redis):
    cm = _env_redis
    key = 'k1'
    assert cm.get(key) is None
    assert cm.set(key, {"a": 1}, expire_seconds=10) is True
    assert cm.get(key) == {"a": 1}
    assert cm.delete(key) is True
    assert cm.get(key) is None

def test_cache_delete_pattern_and_stats(_env_redis):
    cm = _env_redis
    cm.set('user_files:func:obj:1:x', json.dumps({'ok': 1}))
    cm.set('latest_version:func:obj:1:y', json.dumps({'ok': 1}))
    cm.set('misc', json.dumps({'ok': 1}))
    # invalidate user cache should delete at least the two first keys
    deleted = cm.invalidate_user_cache(1)
    assert deleted >= 2
    s = cm.get_stats()
    assert s.get('enabled') is True

def test_cached_decorator(monkeypatch):
    # use the already patched global cache from fixture
    calls = {'n': 0}
    @cached(expire_seconds=60, key_prefix='test')
    def add(a, b):
        calls['n'] += 1
        return a + b
    # first call: miss; second: hit
    assert add(1, 2) == 3
    assert add(1, 2) == 3
    assert calls['n'] == 1
