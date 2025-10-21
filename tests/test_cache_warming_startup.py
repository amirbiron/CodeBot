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

    # Instantiate bot and start polling (which schedules the warm job)
    bot = mod.CodeKeeperBot()

    # Call the section that triggers run_polling path but we won't actually block
    # We simulate the call path up to scheduling by invoking the same logic
    # present in main(). Here we directly inspect job_queue
    # Ensure a job named 'maintenance_clear_handlers' didn't collide; we expect our warming job
    calls = bot.application.job_queue.calls
    # find our warming job by name; it does not have a fixed name in code, so validate by callback signature
    assert any(call[1] is not None for call in calls), 'expected at least one scheduled job with a delay'

    # Validate the warming callback is callable and safe to invoke
    # Invoke the last scheduled callback to ensure it does not raise
    cb, when, name = calls[-1]
    assert callable(cb)
    # The warming job ignores its context; pass a simple namespace
    await cb(types.SimpleNamespace())
