import types
import pytest


@pytest.mark.asyncio
async def test_show_by_repo_menu_no_tags(monkeypatch):
    # Stub database module with no tags
    stub_db_mod = types.ModuleType("database")
    stub_db_mod.DatabaseManager = object
    stub_db_mod.db = types.SimpleNamespace(
        get_repo_tags_with_counts=lambda user_id, max_tags=20: []
    )
    monkeypatch.setitem(__import__('sys').modules, "database", stub_db_mod)

    from conversation_handlers import show_by_repo_menu

    class DummyMessage:
        def __init__(self):
            self.text = None
        async def reply_text(self, text=None, reply_markup=None):
            self.text = text

    class DummyUpdate:
        def __init__(self):
            self.message = DummyMessage()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=11)

    class DummyContext:
        def __init__(self):
            self.user_data = {}

    u = DummyUpdate()
    c = DummyContext()
    await show_by_repo_menu(u, c)
    assert u.message.text and "אין קבצים עם תגית ריפו" in u.message.text


@pytest.mark.asyncio
async def test_show_by_repo_menu_callback_no_tags(monkeypatch):
    # Stub database module with no tags
    stub_db_mod = types.ModuleType("database")
    stub_db_mod.DatabaseManager = object
    stub_db_mod.db = types.SimpleNamespace(
        get_repo_tags_with_counts=lambda user_id, max_tags=20: []
    )
    monkeypatch.setitem(__import__('sys').modules, "database", stub_db_mod)

    from conversation_handlers import show_by_repo_menu_callback
    from utils import TelegramUtils

    captured = {}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured["text"] = text

    monkeypatch.setattr(TelegramUtils, "safe_edit_message_text", fake_safe_edit_message_text)

    class DummyQuery:
        async def answer(self):
            return None

    class DummyUpdate:
        def __init__(self):
            self.callback_query = DummyQuery()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=12)

    class DummyContext:
        def __init__(self):
            self.user_data = {}

    u = DummyUpdate()
    c = DummyContext()
    await show_by_repo_menu_callback(u, c)
    assert captured.get("text") and "אין קבצים עם תגית ריפו" in captured.get("text")

