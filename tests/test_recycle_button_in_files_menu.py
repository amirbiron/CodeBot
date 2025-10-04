import types
import pytest


@pytest.mark.asyncio
async def test_recycle_button_present_in_files_menu_callback(monkeypatch):
    # Ensure env
    monkeypatch.setenv("BOT_TOKEN", "dummy")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    monkeypatch.setenv("DISABLE_DB", "1")

    import importlib
    ch = importlib.import_module("conversation_handlers")

    captured = {}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured["reply_markup"] = reply_markup

    from utils import TelegramUtils
    monkeypatch.setattr(TelegramUtils, "safe_edit_message_text", fake_safe_edit_message_text)

    class DummyQuery:
        def __init__(self):
            self.data = "files"
        async def answer(self):
            return None

    class DummyUpdate:
        def __init__(self):
            self.callback_query = DummyQuery()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    class DummyContext:
        def __init__(self):
            self.user_data = {}

    u = DummyUpdate()
    ctx = DummyContext()

    await ch.show_all_files_callback(u, ctx)

    rm = captured.get("reply_markup")
    assert rm is not None
    callbacks = [row[0].callback_data for row in rm.inline_keyboard]
    assert "recycle_bin" in callbacks
