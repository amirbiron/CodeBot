import importlib
import types
import pytest


def _reload_main(monkeypatch):
    # Minimal env
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    monkeypatch.setenv('DISABLE_DB', '1')
    import main as mod
    importlib.reload(mod)
    return mod


def test_main_exits_when_lock_not_acquired(monkeypatch):
    mod = _reload_main(monkeypatch)

    # manage_mongo_lock returns False -> main should sys.exit(0)
    monkeypatch.setattr(mod, 'manage_mongo_lock', lambda: False)

    # Capture sys.exit
    class Exit(Exception):
        pass
    def _exit(_code=0):
        raise Exit()
    monkeypatch.setattr(mod.sys, 'exit', _exit)

    with pytest.raises(Exit):
        mod.main()


def test_main_calls_cleanup_in_finally(monkeypatch):
    mod = _reload_main(monkeypatch)

    # manage_mongo_lock succeeds
    monkeypatch.setattr(mod, 'manage_mongo_lock', lambda: True)

    # Fake bot with run_polling that returns immediately
    class _MiniApp:
        def __init__(self):
            self.job_queue = types.SimpleNamespace(run_once=lambda *a, **k: None)
    class _FakeBot:
        def __init__(self):
            self.application = _MiniApp()
        def __call__(self):
            return self
        def run_polling(self, *a, **k):
            return None

    monkeypatch.setattr(mod, 'CodeKeeperBot', _FakeBot)

    called = {'cleanup': 0}
    def _cleanup():
        called['cleanup'] += 1
        return True
    monkeypatch.setattr(mod, 'cleanup_mongo_lock', _cleanup)

    mod.main()
    assert called['cleanup'] == 1
