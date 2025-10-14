import types
import pytest
import asyncio


@pytest.mark.asyncio
async def test_favorites_answers_and_edits(monkeypatch):
    # DB returns empty favorites to hit the early path
    fake_db = types.SimpleNamespace(get_favorites=lambda uid, limit=1000: [])
    monkeypatch.setitem(__import__('sys').modules, 'database', types.SimpleNamespace(db=fake_db))

    import conversation_handlers as ch

    answered = {"ans": False}
    class _Q:
        async def answer(self, *a, **k):
            answered["ans"] = True
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _U:
        def __init__(self):
            self.callback_query = _Q()
            self.effective_user = types.SimpleNamespace(id=1)
    class _Ctx:
        def __init__(self):
            self.user_data = {}

    await asyncio.wait_for(ch.show_favorites_callback(_U(), _Ctx()), timeout=2.0)
    assert answered["ans"] is True
