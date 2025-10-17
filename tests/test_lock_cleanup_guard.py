import importlib
import pytest


@pytest.mark.asyncio
async def test_stop_calls_cleanup_once_and_sets_flag(monkeypatch):
    # סביבה בטוחה לטעינת המודול והימנעות מחיבורים אמיתיים
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    monkeypatch.setenv('DISABLE_DB', '1')
    monkeypatch.setenv('DISABLE_ACTIVITY_REPORTER', '1')

    import main as mod
    importlib.reload(mod)

    # בנאי Application מינימלי עם updater ומטודות עצירה אסינכרוניות
    class _MiniApp:
        def __init__(self):
            class _Updater:
                def __init__(self):
                    self.stopped = False
                async def stop(self):  # noqa: D401
                    self.stopped = True
            self.updater = _Updater()
            self.stopped_called = False
            self.shutdown_called = False
        async def stop(self):  # noqa: D401
            self.stopped_called = True
        async def shutdown(self):  # noqa: D401
            self.shutdown_called = True

    class _Builder:
        def token(self, *a, **k):
            return self
        def defaults(self, *a, **k):
            return self
        def persistence(self, *a, **k):
            return self
        def post_init(self, *a, **k):
            return self
        def build(self):
            return _MiniApp()

    class _AppNS:
        def builder(self):
            return _Builder()

    monkeypatch.setattr(mod, 'Application', _AppNS())

    # Stub לניקוי הנעילה — נמדוד כמה פעמים נקרא
    calls = {'n': 0}
    def _cleanup_stub():
        calls['n'] += 1
    monkeypatch.setattr(mod, 'cleanup_mongo_lock', _cleanup_stub, raising=False)

    # החלפת db באובייקט שמכיל close
    class _DB:
        def __init__(self):
            self.closed = 0
        def close(self):
            self.closed += 1
    monkeypatch.setattr(mod, 'db', _DB(), raising=False)

    # יצירת הבוט והרצה כפולה של stop
    bot = mod.CodeKeeperBot()
    await bot.stop()
    await bot.stop()

    # ודא שהניקוי רץ פעם אחת בלבד ובוצע דגל המנע
    assert calls['n'] == 1, 'cleanup_mongo_lock should be called only once'
    assert getattr(bot, '_lock_cleanup_done', False) is True
