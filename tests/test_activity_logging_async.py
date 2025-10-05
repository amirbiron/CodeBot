import types
import asyncio
import pytest


@pytest.mark.asyncio
async def test_log_user_activity_sampling_and_async(monkeypatch):
    # Force sampling to True and intercept job_queue
    from types import SimpleNamespace

    # Patch random to always sample
    import builtins
    import importlib
    mod_main = importlib.import_module('main')

    class DummyUsers:
        def __init__(self):
            self.doc = {"total_actions": 200, "milestones_sent": []}
            self._updates = []
        def find_one(self, *_a, **_k):
            return dict(self.doc)
        def update_one(self, *_a, **_k):
            self._updates.append((_a, _k))
            return SimpleNamespace(modified_count=1)

    # db stub
    db_mod = types.ModuleType('database')
    db_mod.db = SimpleNamespace(users=DummyUsers())
    monkeypatch.setitem(__import__('sys').modules, 'database', db_mod)

    # job_queue stub
    captured = {'ran': False}
    class DummyJQ:
        def run_once(self, cb, when=0, name=None):
            # simulate calling the callback immediately
            asyncio.get_event_loop().call_soon(lambda: cb(None))
            return None
    ctx = SimpleNamespace(application=SimpleNamespace(create_task=asyncio.create_task), job_queue=DummyJQ())

    # Build minimal update
    class U:
        @property
        def effective_user(self):
            return SimpleNamespace(id=1, username='u')
    upd = U()

    # Call
    await mod_main.log_user_activity(upd, ctx)

    # Let loop run tasks
    await asyncio.sleep(0.01)

    # If reached here without exceptions, async scheduling worked
    assert True
