import types
import pytest


@pytest.mark.asyncio
async def test_log_user_activity_weight_typeerror_fallback(monkeypatch):
    # Stub database module for import side-effects
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

    # Force sampling so the logging path is executed
    import random as _rnd
    monkeypatch.setattr(_rnd, "random", lambda: 0.0)

    calls = {"n": 0}

    def _log_user(uid, uname=None, **kwargs):
        # Simulate legacy function without weight support: raise on unexpected kw
        if "weight" in kwargs:
            raise TypeError("unexpected kw 'weight'")
        calls["n"] += 1

    monkeypatch.setattr(user_stats_mod.user_stats, "log_user", _log_user)

    class Ctx:
        bot = types.SimpleNamespace(send_message=lambda **_k: None)
        application = types.SimpleNamespace(job_queue=None)

    class Upd:
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1, username="u")

    await log_user_activity(Upd(), Ctx())
    # Fallback without weight should have been called exactly once
    assert calls["n"] == 1
