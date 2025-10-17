import importlib
import pytest


@pytest.mark.asyncio
async def test_stop_retries_when_first_cleanup_failed(monkeypatch):
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    monkeypatch.setenv('DISABLE_DB', '1')
    monkeypatch.setenv('DISABLE_ACTIVITY_REPORTER', '1')

    import main as mod
    importlib.reload(mod)

    # מימוש Application מינימלי כפי בשאר הטסטים
    class _MiniApp:
        def __init__(self):
            class _Updater:
                async def stop(self):
                    return None
            self.updater = _Updater()
        async def stop(self):
            return None
        async def shutdown(self):
            return None

    class _Builder:
        def token(self, *a, **k): return self
        def defaults(self, *a, **k): return self
        def persistence(self, *a, **k): return self
        def post_init(self, *a, **k): return self
        def build(self): return _MiniApp()

    class _AppNS:
        def builder(self): return _Builder()

    monkeypatch.setattr(mod, 'Application', _AppNS())

    # set db stub
    class _DB:
        def close(self):
            return None
    monkeypatch.setattr(mod, 'db', _DB(), raising=False)

    # cleanup ייכשל פעם ראשונה ויצליח שניה
    calls = {'n': 0}
    def _cleanup():
        calls['n'] += 1
        return calls['n'] > 1
    monkeypatch.setattr(mod, 'cleanup_mongo_lock', _cleanup, raising=False)

    bot = mod.CodeKeeperBot()

    # ניסיון ראשון: cleanup מחזיר False => לא מסמנים דגל
    await bot.stop()
    assert calls['n'] == 1
    assert getattr(bot, '_lock_cleanup_done', False) is False

    # ניסיון שני: cleanup מחזיר True => מסמנים דגל ולא קוראים שוב
    await bot.stop()
    assert calls['n'] == 2
    assert getattr(bot, '_lock_cleanup_done', False) is True

    # ניסיון שלישי: צריך לדלג (הדגל כבר סומן)
    await bot.stop()
    assert calls['n'] == 2
