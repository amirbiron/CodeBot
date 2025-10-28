import importlib
import types
import pytest


def _reload_with_disabled_redis(monkeypatch):
    monkeypatch.setenv('REDIS_URL', '')  # מבטל Redis לחלוטין
    import cache_manager as cm
    importlib.reload(cm)
    return cm


def test_cached_fallback_local_hit(monkeypatch):
    cm = _reload_with_disabled_redis(monkeypatch)
    # נקה זיכרון פולבק כדי להתחיל ממפתח ריק
    cm._local_cache_store.clear()

    calls = {'n': 0}

    @cm.cached(expire_seconds=60, key_prefix='t')
    def add(a, b):
        calls['n'] += 1
        return a + b

    # first: miss -> חישוב ושמירה בזיכרון מקומי
    assert add(1, 2) == 3
    # second: hit מהזיכרון המקומי
    assert add(1, 2) == 3
    assert calls['n'] == 1

    # ודא שהמפתח קיים בפולבק המקומי
    key = cm.cache._make_key('t', 'add', 1, 2)
    assert key in cm._local_cache_store


def test_cached_fallback_local_ttl_expiry(monkeypatch):
    cm = _reload_with_disabled_redis(monkeypatch)
    cm._local_cache_store.clear()

    # שליטה בזמן עבור בדיקת TTL
    current = {'t': 1_000_000.0}

    def fake_time():
        return current['t']

    monkeypatch.setattr(cm.time, 'time', fake_time, raising=False)

    calls = {'n': 0}

    @cm.cached(expire_seconds=5, key_prefix='t')
    def add(a, b):
        calls['n'] += 1
        return a + b

    assert add(1, 2) == 3  # חישוב ראשון
    assert add(1, 2) == 3  # פגיעה בקאש המקומי
    assert calls['n'] == 1

    # הקדמת הזמן מעבר ל-TTL המקומי
    current['t'] += 10

    # צריך להתרחש חישוב מחדש
    assert add(1, 2) == 3
    assert calls['n'] == 2


@pytest.mark.asyncio
async def test_async_cached_fallback_local_hit(monkeypatch):
    cm = _reload_with_disabled_redis(monkeypatch)
    cm._local_cache_store.clear()

    calls = {'n': 0}

    @cm.async_cached(expire_seconds=60, key_prefix='t')
    async def add(a, b):
        calls['n'] += 1
        return a + b

    assert await add(1, 2) == 3
    assert await add(1, 2) == 3
    assert calls['n'] == 1


def test_cached_remote_success_uses_remote_not_local(monkeypatch):
    cm = _reload_with_disabled_redis(monkeypatch)
    cm._local_cache_store.clear()

    # מדמה "Redis" מרוחק בזיכרון כדי לבדוק נתיב wrote_remote=True
    remote: dict = {}

    def remote_get(key: str):
        return remote.get(key)

    def remote_set(key: str, value, ex: int):  # noqa: ARG001
        remote[key] = value
        return True

    monkeypatch.setattr(cm.cache, 'get', remote_get, raising=True)
    monkeypatch.setattr(cm.cache, 'set', remote_set, raising=True)

    calls = {'n': 0}

    @cm.cached(expire_seconds=60, key_prefix='r')
    def add(a, b):
        calls['n'] += 1
        return a + b

    assert add(1, 2) == 3
    assert add(1, 2) == 3
    # רק חישוב אחד התבצע
    assert calls['n'] == 1

    # המפתח נשמר ב"מרוחק" ולא בפולבק המקומי
    key = cm.cache._make_key('r', 'add', 1, 2)
    assert key in remote
    assert key not in cm._local_cache_store


def test_cached_fallback_when_remote_set_raises(monkeypatch):
    cm = _reload_with_disabled_redis(monkeypatch)
    cm._local_cache_store.clear()

    # remote get תמיד מחזיר None כדי להכריח שמירה
    monkeypatch.setattr(cm.cache, 'get', lambda _k: None, raising=True)

    def raising_set(key, value, ex):  # noqa: ARG001
        raise RuntimeError('boom')

    monkeypatch.setattr(cm.cache, 'set', raising_set, raising=True)

    calls = {'n': 0}

    @cm.cached(expire_seconds=30, key_prefix='e')
    def add(a, b):
        calls['n'] += 1
        return a + b

    # קריאה ראשונה שומרת לפולבק המקומי עקב חריגה
    assert add(1, 2) == 3
    key = cm.cache._make_key('e', 'add', 1, 2)
    assert key in cm._local_cache_store

    # קריאה שנייה נפגעת מהקאש המקומי — אין חישוב נוסף
    assert add(1, 2) == 3
    assert calls['n'] == 1


@pytest.mark.asyncio
async def test_async_cached_remote_success_uses_remote_not_local(monkeypatch):
    cm = _reload_with_disabled_redis(monkeypatch)
    cm._local_cache_store.clear()

    remote: dict = {}

    def remote_get(key: str):
        return remote.get(key)

    def remote_set(key: str, value, ex: int):  # noqa: ARG001
        remote[key] = value
        return True

    monkeypatch.setattr(cm.cache, 'get', remote_get, raising=True)
    monkeypatch.setattr(cm.cache, 'set', remote_set, raising=True)

    calls = {'n': 0}

    @cm.async_cached(expire_seconds=60, key_prefix='r')
    async def add(a, b):
        calls['n'] += 1
        return a + b

    assert await add(1, 2) == 3
    assert await add(1, 2) == 3
    assert calls['n'] == 1

    key = cm.cache._make_key('r', 'add', 1, 2)
    assert key in remote
    assert key not in cm._local_cache_store


def test_fallback_returns_copy_not_same_object(monkeypatch):
    cm = _reload_with_disabled_redis(monkeypatch)
    cm._local_cache_store.clear()

    @cm.cached(expire_seconds=60, key_prefix='copy')
    def build_obj():
        return {"a": [1, 2]}

    first = build_obj()
    # שינוי באובייקט שהוחזר לא צריך להשפיע על הקאש
    first["a"].append(3)

    second = build_obj()
    assert second == {"a": [1, 2]}  # עותק נקי
    assert second is not first


@pytest.mark.asyncio
async def test_async_fallback_returns_copy_not_same_object(monkeypatch):
    cm = _reload_with_disabled_redis(monkeypatch)
    cm._local_cache_store.clear()

    @cm.async_cached(expire_seconds=60, key_prefix='copy')
    async def build_obj():
        return {"a": [1, 2]}

    first = await build_obj()
    first["a"].append(3)

    second = await build_obj()
    assert second == {"a": [1, 2]}
    assert second is not first
