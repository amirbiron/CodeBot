import types
import pytest


@pytest.mark.asyncio
async def test_log_user_activity_fallback_without_jobqueue(monkeypatch):
    # stub database first
    db_mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    db_mod.CodeSnippet = _CodeSnippet
    db_mod.LargeFile = _LargeFile
    db_mod.DatabaseManager = _DatabaseManager
    db_mod.db = types.SimpleNamespace(db=types.SimpleNamespace(users=None))
    monkeypatch.setitem(__import__('sys').modules, "database", db_mod)

    from main import log_user_activity
    import user_stats as user_stats_mod

    # force sampling
    import random as _rnd
    monkeypatch.setattr(_rnd, "random", lambda: 0.0)
    calls = {"log": 0, "task": 0}
    monkeypatch.setattr(user_stats_mod.user_stats, "log_user", lambda *_: calls.__setitem__("log", calls["log"] + 1))

    # context without job_queue triggers asyncio.create_task path
    import asyncio as _aio
    monkeypatch.setattr(_aio, "create_task", lambda *_: calls.__setitem__("task", calls["task"] + 1))

    class Ctx: pass
    ctx = Ctx()
    ctx.bot = types.SimpleNamespace(send_message=lambda **_k: None)
    ctx.application = types.SimpleNamespace()

    class Upd:
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1, username="u")

    await log_user_activity(Upd(), ctx)
    assert calls["log"] == 1
    assert calls["task"] == 1
