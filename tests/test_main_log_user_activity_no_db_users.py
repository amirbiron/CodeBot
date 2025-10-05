import types
import pytest


@pytest.mark.asyncio
async def test_log_user_activity_no_users_collection(monkeypatch):
    # stub database without db.users
    db_mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    db_mod.CodeSnippet = _CodeSnippet
    db_mod.LargeFile = _LargeFile
    db_mod.DatabaseManager = _DatabaseManager
    db_mod.db = types.SimpleNamespace(db=None)
    monkeypatch.setitem(__import__('sys').modules, "database", db_mod)

    from main import log_user_activity
    import user_stats as user_stats_mod

    # force sampling path
    import random as _rnd
    monkeypatch.setattr(_rnd, "random", lambda: 0.0)
    monkeypatch.setattr(user_stats_mod.user_stats, "log_user", lambda *_a, **_k: None)

    class Ctx:
        bot = types.SimpleNamespace(send_message=lambda **_k: None)
        application = types.SimpleNamespace(job_queue=None)

    class Upd:
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1, username="u")

    # should not raise even without users collection
    await log_user_activity(Upd(), Ctx())
