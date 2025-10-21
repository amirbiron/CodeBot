import types
import importlib
import pytest


@pytest.mark.asyncio
async def test_cache_warming_job_is_scheduled(monkeypatch):
    # Set required environment and reload config
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    monkeypatch.setenv('DISABLE_DB', '1')

    import config as cfg
    importlib.reload(cfg)
    import main as mod
    importlib.reload(mod)

    # Fake JobQueue to capture run_once call
    class _JobQ:
        def __init__(self):
            self.calls = []
        def run_once(self, cb, when=None, name=None):
            self.calls.append((cb, when, name))
            return None

    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}
            self.job_queue = _JobQ()
        def add_handler(self, handler, group=None):
            self.handlers.append((handler, group))
        def add_error_handler(self, handler, group=None):
            pass
        def run_polling(self, *a, **k):
            # No-op polling to avoid blocking test
            return None

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

    # Patch Application.builder used inside CodeKeeperBot
    monkeypatch.setattr(mod, 'Application', _AppNS())

    # Instantiate bot
    bot = mod.CodeKeeperBot()

    # Provide a stub manage_mongo_lock that succeeds
    monkeypatch.setattr(mod, 'manage_mongo_lock', lambda: True)

    # Run main() to execute scheduling logic (run_polling is a no-op in our stub MiniApp)
    mod.main()

    # Inspect scheduled jobs
    calls = bot.application.job_queue.calls
    assert calls, 'expected at least one scheduled job'
    # Find the warming job by delay (we schedule with when=2)
    assert any((c[1] == 2) for c in calls), 'expected a warm job scheduled with when=2'

    # Validate the warming callback is callable and safe to invoke
    # Invoke the last scheduled callback to ensure it does not raise
    cb, when, name = calls[-1]
    assert callable(cb)
    # The warming job ignores its context; pass a simple namespace
    await cb(types.SimpleNamespace())
