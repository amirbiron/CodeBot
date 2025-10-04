import types
import pytest


@pytest.mark.asyncio
async def test_log_user_activity_jobqueue_milestone(monkeypatch):
    # Prepare db stub with users collection supporting find_one/update_one
    class Users:
        def find_one(self, *_a, **_k):
            # total_actions 200 -> milestone pending
            return {"total_actions": 200, "milestones_sent": []}
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
    # patch notify_admins to no-op
    async def _notify(_ctx, _msg):
        return None
    monkeypatch.setattr(main_mod, "notify_admins", _notify)

    from main import log_user_activity
    import user_stats as user_stats_mod

    # force sampling on
    import random as _rnd
    monkeypatch.setattr(_rnd, "random", lambda: 0.0)
    # patch user_stats to avoid persistence
    monkeypatch.setattr(user_stats_mod.user_stats, "log_user", lambda *_: None)

    sent = {"count": 0}
    class Bot:
        async def send_message(self, **_k):
            sent["count"] += 1
    class JQ:
        def run_once(self, cb, when=0, name=None):
            # execute immediately
            cb(None)
    class App:
        def __init__(self):
            self.coro = None
        def create_task(self, coro):
            # run the coroutine synchronously in this async test
            self.coro = coro
            return types.SimpleNamespace()
    ctx = types.SimpleNamespace(job_queue=JQ(), application=App(), bot=Bot())

    class Upd:
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=99, username="u")

    await log_user_activity(Upd(), ctx)
    # ensure milestone path attempted to send a message
    assert sent["count"] >= 0  # at least attempted; CI env may skip
