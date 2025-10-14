import types
import importlib
import pytest


@pytest.mark.asyncio
async def test_single_delete_to_trash_flow(monkeypatch):
    # Env for imports
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")

    ch = importlib.import_module("conversation_handlers")

    # Prepare files cache and DB stub
    class DummyDB:
        def delete_file(self, user_id, file_name):
            DummyDB.last = (user_id, file_name)
            return True

    mod = types.ModuleType("database")
    mod.db = DummyDB()
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    captured = {"text": None}

    class DummyQuery:
        def __init__(self, data):
            self.data = data
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
            captured["text"] = text

    class DummyUpdate:
        def __init__(self, data):
            self.callback_query = DummyQuery(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=42)

    class DummyContext:
        def __init__(self):
            self.user_data = {"files_cache": {"0": {"file_name": "a.py"}}}

    # Step 1: open confirm dialog
    u1 = DummyUpdate("del_0")
    ctx = DummyContext()
    await ch.handle_callback_query(u1, ctx)
    assert captured["text"] is not None
    assert "אישור העברה לסל" in captured["text"]

    # Step 2: confirm and perform deletion (move to bin)
    u2 = DummyUpdate("confirm_del_0")
    await ch.handle_callback_query(u2, ctx)
    assert captured["text"] is not None
    assert "הועבר לסל המיחזור" in captured["text"]
