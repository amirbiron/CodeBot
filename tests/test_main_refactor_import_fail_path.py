import sys
import types


def test_codekeeperbot_setup_handlers_import_fail(monkeypatch):
    # Fake refactor_handlers module without setup_refactor_handlers to trigger except path
    fake = types.ModuleType('refactor_handlers')
    monkeypatch.setitem(sys.modules, 'refactor_handlers', fake)

    mod = __import__('main')

    # Stub Application.builder chain
    class _Builder:
        def token(self, *a, **k): return self
        def defaults(self, *a, **k): return self
        def persistence(self, *a, **k): return self
        def post_init(self, *a, **k): return self
        def build(self):
            class _App:
                def __init__(self):
                    self.bot_data = {}
                    self.handlers = []
                def add_handler(self, *a, **k):
                    self.handlers.append((a, k))
                def add_error_handler(self, *a, **k):
                    return None
                async def initialize(self): pass
                async def start(self): pass
                class _Updater:
                    async def start_polling(self): pass
                updater = _Updater()
            return _App()

    class _Application:
        @staticmethod
        def builder():
            return _Builder()

    monkeypatch.setattr(mod, 'Application', _Application, raising=True)

    # Instantiate CodeKeeperBot; setup_handlers should catch import error path
    bot = mod.CodeKeeperBot()
    assert bot is not None

