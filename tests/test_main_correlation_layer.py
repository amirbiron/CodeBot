import types
import pytest

import importlib


@pytest.mark.asyncio
async def test_correlation_layer_registers_typehandler(monkeypatch):
    # Minimal stubs for builder
    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}
            class _JQ:
                def run_once(self, *a, **k):
                    return None
            self.job_queue = _JQ()
        def add_handler(self, handler, group=None):
            self.handlers.append((handler, group))
        def add_error_handler(self, *a, **k):
            pass
        def remove_handler(self, *a, **k):
            pass

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

    import main as mod
    import config as cfg
    importlib.reload(cfg)
    importlib.reload(mod)

    monkeypatch.setattr(mod, 'Application', _AppNS())

    bot = mod.CodeKeeperBot()

    # verify a handler with group = -100 exists (correlation layer)
    groups = [g for h, g in bot.application.handlers]
    assert -100 in groups
