import pytest


def test_cached_does_not_cache_none(monkeypatch):
    import cache_manager as cm_mod

    # נקה פולבק מקומי כדי להתחיל נקי
    cm_mod._local_cache_store.clear()

    # ודא שקריאה מרחוק תמיד מחזירה None וששמירה תיכשל אם תיקרא
    monkeypatch.setattr(cm_mod.cache, 'get', lambda _k: None, raising=True)

    def raising_set(_k, _v, ex=None):  # noqa: ARG001
        raise AssertionError('cache.set should not be called for None results')

    monkeypatch.setattr(cm_mod.cache, 'set', raising_set, raising=True)

    calls = {'n': 0}

    @cm_mod.cached(expire_seconds=30, key_prefix='none')
    def fn(a):  # noqa: ARG001
        calls['n'] += 1
        return None

    # לא אמור להישמר בקאש — שתי קריאות מפעילות את הפונקציה
    assert fn(1) is None
    assert fn(1) is None
    assert calls['n'] == 2

    # לא נוצר מפתח בפולבק המקומי
    key = cm_mod.cache._make_key('none', 'fn', 1)
    assert key not in cm_mod._local_cache_store


@pytest.mark.asyncio
async def test_async_cached_does_not_cache_none(monkeypatch):
    import cache_manager as cm_mod

    cm_mod._local_cache_store.clear()

    monkeypatch.setattr(cm_mod.cache, 'get', lambda _k: None, raising=True)

    def raising_set(_k, _v, ex=None):  # noqa: ARG001
        raise AssertionError('cache.set should not be called for None results')

    monkeypatch.setattr(cm_mod.cache, 'set', raising_set, raising=True)

    calls = {'n': 0}

    @cm_mod.async_cached(expire_seconds=30, key_prefix='none')
    async def fn(a):  # noqa: ARG001
        calls['n'] += 1
        return None

    assert await fn(1) is None
    assert await fn(1) is None
    assert calls['n'] == 2

    key = cm_mod.cache._make_key('none', 'fn', 1)
    assert key not in cm_mod._local_cache_store
