import importlib
import os

def test_disable_activity_reporter_env(monkeypatch):
    monkeypatch.setenv('DISABLE_ACTIVITY_REPORTER', '1')
    # reload module to apply change
    if 'bot_handlers' in list(dict(globals()).get('__builtins__', {})):
        pass
    mod = importlib.import_module('bot_handlers')
    importlib.reload(mod)
    # reporter should be noop
    assert hasattr(mod, 'reporter')
    assert mod.reporter.report_activity(1234) is None
