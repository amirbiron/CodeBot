import types
import pytest


@pytest.mark.asyncio
async def test_milestones_admin_notify_for_500(monkeypatch):
    # users collection returns total_actions=500 with no milestones sent
    class Users:
        def find_one(self, *_a, **_k):
            return {"total_actions": 500, "milestones_sent": []}
        def update_one(self, *_a, **_k):
            return types.SimpleNamespace(modified_count=1)
    db_mod = types.ModuleType("database")
    class _CodeSnippet: pass
    class _LargeFile: pass
    class _DatabaseManager: pass
    db_mod.CodeSnippet = _CodeSnippet
    db_mod.LargeFile = _LargeFile
    db_mod.DatabaseManager = _DatabaseManager
    db_mod.db = types.SimpleNamespace(db=types.SimpleNamespace(users=Users()))
    monkeypatch.setitem(__import__('sys').modules, "database", db_mod)

    import main as main_mod
    # capture admin notifications
    msgs = {"n": 0}
    async def _notify(_ctx, _msg):
        msgs["n"] += 1
    monkeypatch.setattr(main_mod, "notify_admins", _notify)

    from main import log_user_activity
    import user_stats as user_stats_mod

    # sampling on
    import random as _rnd
    monkeypatch.setattr(_rnd, "random", lambda: 0.0)
    # neutralize DB writes
    monkeypatch.setattr(user_stats_mod.user_stats, "log_user", lambda *_a, **_k: None)

    class Bot:
        async def send_message(self, **_k):
            return None
    class JQ:
        def run_once(self, cb, when=0, name=None):
            cb(None)
    class App:
        def __init__(self):
            self.coro = None
        def create_task(self, coro):
            self.coro = coro
            return types.SimpleNamespace()
    ctx = types.SimpleNamespace(job_queue=JQ(), application=App(), bot=Bot())

    class Upd:
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=7, username="user")

    await log_user_activity(Upd(), ctx)
    if getattr(ctx.application, "coro", None) is not None:
        await ctx.application.coro
    # admin message should be sent for 500
    assert msgs["n"] >= 1
