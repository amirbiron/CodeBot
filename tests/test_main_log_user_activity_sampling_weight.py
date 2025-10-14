import types
import pytest


@pytest.mark.asyncio
async def test_log_user_activity_sampling_weight(monkeypatch):
    # stub database module for main import
    db_mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    db_mod.CodeSnippet = _CodeSnippet
    db_mod.LargeFile = _LargeFile
    db_mod.DatabaseManager = _DatabaseManager
    # minimal users collection not used in this test path
    db_mod.db = types.SimpleNamespace(db=types.SimpleNamespace(users=None))
    monkeypatch.setitem(__import__('sys').modules, "database", db_mod)

    from main import log_user_activity
    import user_stats as user_stats_mod

    # force sampled=True and capture weight
    import random as _rnd
    monkeypatch.setattr(_rnd, "random", lambda: 0.0)

    captured = {"weight": None}
    def _log_user(uid, uname=None, weight: int = 1):
        captured["weight"] = weight
    monkeypatch.setattr(user_stats_mod.user_stats, "log_user", _log_user)

    # prevent milestone scheduling
    import asyncio as _aio
    monkeypatch.setattr(_aio, "create_task", lambda *_: None)

    class Ctx:
        bot = types.SimpleNamespace(send_message=lambda **_k: None)
        application = types.SimpleNamespace(job_queue=None)
    class Upd:
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1, username="u")

    await log_user_activity(Upd(), Ctx())
    assert captured["weight"] == 4
