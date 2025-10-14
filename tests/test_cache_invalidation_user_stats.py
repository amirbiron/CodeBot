import types
import pytest


def test_invalidate_user_cache_removes_user_stats(monkeypatch):
    import cache_manager as cm

    # מזייף redis client עם keys/delete
    class _FakeRedis:
        def __init__(self):
            self.store = {}
        def set(self, key, value, ex=None):
            self.store[key] = value
            return True
        def expire(self, key, seconds):
            # לא נדרש לזמן קצר בטסט; נחזיר True
            return True
        def keys(self, pattern):
            import fnmatch
            return [k for k in list(self.store.keys()) if fnmatch.fnmatch(k, pattern)]
        def delete(self, *keys):
            deleted = 0
            for k in keys:
                if k in self.store:
                    del self.store[k]
                    deleted += 1
            return deleted
        def get(self, key):
            return self.store.get(key)

    fake = _FakeRedis()

    # הזרקת הלקוח המזויף
    cm.cache.redis_client = fake
    cm.cache.is_enabled = True

    user_id = 42
    # מפתחות לדוגמה כפי שנוצרים ע"י decorator
    keys = [
        f"user_stats:get_user_stats:<self>:{user_id}",
        f"latest_version:get_latest_version:<self>:{user_id}:main.py",
        f"user_files:get_user_files:<self>:{user_id}:50",
    ]
    for k in keys:
        fake.store[k] = '1'

    # ודא שהמפתח של user_stats קיים
    assert fake.get(keys[0]) == '1'

    # הפעל אינוולידציה
    cm.cache.invalidate_user_cache(user_id)

    # צריך להימחק
    assert fake.get(keys[0]) is None
    # אחרים עשויים להימחק גם — לא נדרש במדויק כאן
