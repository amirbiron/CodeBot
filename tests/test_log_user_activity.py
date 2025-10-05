import types
import pytest


@pytest.mark.asyncio
async def test_log_user_activity_schedules_and_samples(monkeypatch):
    # Patch random to ensure sampling path always true
    import builtins
    import importlib
    import sys

    # Ensure database stub is present before importing main
    db_mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    db_mod.CodeSnippet = _CodeSnippet
    db_mod.LargeFile = _LargeFile
    db_mod.DatabaseManager = _DatabaseManager
    # Provide minimal db attr to satisfy references if executed
    db_mod.db = types.SimpleNamespace(db=types.SimpleNamespace(users=None))
    monkeypatch.setitem(sys.modules, "database", db_mod)

    # Import target after stubbing
    from main import log_user_activity
    import user_stats as user_stats_mod

    calls = {"log": 0}
    def _log_user(uid, uname=None):
        calls["log"] += 1
    # patch the instance method on the module-level singleton
    monkeypatch.setattr(user_stats_mod.user_stats, "log_user", _log_user)

    # Force random to return 0.0
    import random as _rnd
    monkeypatch.setattr(_rnd, "random", lambda: 0.0)

    # Build context with job_queue capturing run_once and application.create_task
    class _JQ:
        def __init__(self):
            self.captured = None
        def run_once(self, cb, when=0, name=None):
            self.captured = {"cb": cb, "when": when, "name": name}
            return types.SimpleNamespace()
    class _App:
        def __init__(self):
            self.coro = None
        def create_task(self, coro):
            self.coro = coro
            return types.SimpleNamespace()

    ctx = types.SimpleNamespace(
        user_data={},
        job_queue=_JQ(),
        application=_App(),
        bot=types.SimpleNamespace(send_message=lambda **_k: None),
    )

    class _EU:
        def __init__(self):
            self.id = 42
            self.username = "tester"
    class _Upd:
        def __init__(self):
            self._eu = _EU()
        @property
        def effective_user(self):
            return self._eu

    await log_user_activity(_Upd(), ctx)
    # user_stats.log_user called due to sampling
    assert calls["log"] == 1
    # scheduled a background milestone job
    assert ctx.job_queue.captured is not None
    assert ctx.job_queue.captured["when"] == 0
