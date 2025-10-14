import json
import types
import pytest

from cache_manager import CacheManager

class _FakeClientSetEx:
    def __init__(self):
        self.store = {}
    def setex(self, key, ttl, val):
        self.store[key] = (val, ttl)
        return True
    def get(self, key):
        v = self.store.get(key)
        if isinstance(v, tuple):
            return v[0]
        return v
    def delete(self, *keys):
        c = 0
        for k in keys:
            if k in self.store:
                del self.store[k]
                c += 1
        return c
    def keys(self, pattern):
        # naive: return all keys
        return list(self.store.keys())

class _FakeClientSetWithEx:
    def __init__(self):
        self.store = {}
        self.expired = {}
    def set(self, key, val, ex=None):
        self.store[key] = val
        if ex is not None:
            self.expired[key] = ex
        return True
    def get(self, key):
        return self.store.get(key)
    def delete(self, *keys):
        c = 0
        for k in keys:
            c += 1 if self.store.pop(k, None) is not None else 0
        return c
    def keys(self, pattern):
        return list(self.store.keys())

class _FakeClientSetThenExpire:
    def __init__(self):
        self.store = {}
        self.expired = {}
    def set(self, key, val):
        self.store[key] = val
        return True
    def expire(self, key, sec):
        self.expired[key] = sec
        return True
    def get(self, key):
        return self.store.get(key)
    def delete(self, *keys):
        c = 0
        for k in keys:
            c += 1 if self.store.pop(k, None) is not None else 0
        return c
    def keys(self, pattern):
        return list(self.store.keys())


def _new_manager_with(client):
    m = CacheManager()
    m.is_enabled = True
    m.redis_client = client
    return m


def test_cache_set_with_setex_client():
    cm = _new_manager_with(_FakeClientSetEx())
    ok = cm.set("k", {"x": 1}, expire_seconds=10)
    assert ok is True
    assert cm.get("k") == {"x": 1}


def test_cache_set_fallback_set_with_ex():
    cm = _new_manager_with(_FakeClientSetWithEx())
    ok = cm.set("k2", {"y": 2}, expire_seconds=7)
    assert ok is True
    assert cm.get("k2") == {"y": 2}


def test_cache_set_fallback_set_then_expire_and_delete_pattern():
    cm = _new_manager_with(_FakeClientSetThenExpire())
    ok = cm.set("pref:1", [1, 2, 3], expire_seconds=5)
    assert ok is True
    # delete_pattern should delete stored key
    count = cm.delete_pattern("pref:*")
    assert count >= 1
