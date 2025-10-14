import types
import importlib
import pytest


@pytest.mark.asyncio
async def test_by_repo_delete_to_trash_texts(monkeypatch):
    # Env for imports
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")

    ch = importlib.import_module("conversation_handlers")

    # Stub db.search_code to return 2 items
    mod = types.ModuleType("database")
    class DummyDB:
        def search_code(self, user_id, query, tags=None, limit=10000):
            return [{"file_name": "a.py"}, {"file_name": "b.py"}]
        def delete_file(self, user_id, file_name):
            return True
    mod.db = DummyDB()
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    captured = {"text": None, "reply_markup": None}

    class DummyQuery:
        def __init__(self, data):
            self.data = data
            self.message = types.SimpleNamespace(message_id=1)
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
            captured["text"] = text
            captured["reply_markup"] = reply_markup

    class DummyUpdate:
        def __init__(self, data):
            self.callback_query = DummyQuery(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=7)

    class DummyContext:
        def __init__(self):
            self.user_data = {}

    tag = "repo:me/app"

    # Step 1: open confirm
    u1 = DummyUpdate(f"byrepo_delete_confirm:{tag}")
    ctx = DummyContext()
    await ch.handle_callback_query(u1, ctx)

    assert captured["text"] is not None
    assert "להעביר" in captured["text"] and "סל" in captured["text"]

    # Step 2: second confirm text
    u2 = DummyUpdate(f"byrepo_delete_double_confirm:{tag}")
    await ch.handle_callback_query(u2, ctx)

    assert captured["text"] is not None
    assert "אישור סופי להעברה לסל" in captured["text"]

    # Step 3: perform action and final message
    u3 = DummyUpdate(f"byrepo_delete_do:{tag}")
    await ch.handle_callback_query(u3, ctx)

    assert captured["text"] is not None
    assert "הועברו לסל" in captured["text"]
