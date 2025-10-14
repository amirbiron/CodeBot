import os
import json
import pytest

from cache_manager import CacheManager

class DummyRedisNoSetEx:
    def __init__(self):
        self.store = {}
    def ping(self):
        return True
    def get(self, k):
        return self.store.get(k)
    def set(self, k, v, ex=None):
        self.store[k] = v
        return True
    def expire(self, k, ex):
        return True
    def delete(self, *keys):
        cnt = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                cnt += 1
        return cnt
    def keys(self, pattern):
        prefix = pattern.split('*')[0]
        return [k for k in self.store.keys() if k.startswith(prefix)]
    def info(self):
        return {'used_memory_human': '1M', 'connected_clients': 1, 'keyspace_hits': 0, 'keyspace_misses': 0}

@pytest.fixture
def cm(monkeypatch):
    os.environ['REDIS_URL'] = 'redis://dummy'
    cm = CacheManager()
    # אין setex -> ניפול למסלולים set(ex=)/expire
    monkeypatch.setattr(cm, 'redis_client', DummyRedisNoSetEx(), raising=True)
    monkeypatch.setattr(cm, 'is_enabled', True, raising=True)
    return cm

def test_set_without_setex_and_delete_pattern_no_match(cm):
    key = 'misc:1'
    assert cm.set(key, {"x": 1}, expire_seconds=5) is True
    # דפוס שאין לו התאמות צריך להחזיר 0
    assert cm.delete_pattern('nope:*') == 0
    # ואילו דפוס עם התאמה יחזיר 1
    assert cm.delete_pattern('misc:*') >= 1
