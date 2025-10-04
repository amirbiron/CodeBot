import types
import pytest


@pytest.mark.asyncio
async def test_bulk_move_to_trash_texts(monkeypatch):
    # Ensure env for importing
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")

    import importlib
    ch = importlib.import_module("conversation_handlers")

    captured = {"text": None, "kb": None}

    class DummyQuery:
        def __init__(self, data):
            self.data = data
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
            captured["text"] = text
            captured["kb"] = reply_markup

    class DummyUpdate:
        def __init__(self, data):
            self.callback_query = DummyQuery(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=7)

    class DummyContext:
        def __init__(self):
            self.user_data = {"rf_selected_ids": ["id1", "id2"], "files_last_page": 1}

    # First confirm step
    u = DummyUpdate("rf_delete_confirm")
    ctx = DummyContext()
    await ch.handle_callback_query(u, ctx)

    assert captured["text"] is not None
    assert "להעביר" in captured["text"] and "סל" in captured["text"]

    # Second confirm step
    u2 = DummyUpdate("rf_delete_double_confirm")
    await ch.handle_callback_query(u2, ctx)

    assert captured["text"] is not None
    assert "אישור סופי להעברה לסל" in captured["text"]
    # keyboard contains the proceed button with the new label
    kb = captured["kb"]
    assert kb is not None
    btn_texts = [btn.text for row in kb.inline_keyboard for btn in row]
    assert any("כן, העבר לסל" in t for t in btn_texts)
