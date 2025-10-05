import types
import pytest


@pytest.mark.asyncio
async def test_log_user_activity_ignores_when_no_user(monkeypatch):
    # minimal stubs
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

    class Upd:
        @property
        def effective_user(self):
            return None

    class Ctx:
        bot = types.SimpleNamespace(send_message=lambda **_k: None)
        application = types.SimpleNamespace(job_queue=None)

    # should not raise
    await log_user_activity(Upd(), Ctx())
