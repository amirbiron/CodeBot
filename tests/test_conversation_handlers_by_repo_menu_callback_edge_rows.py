import types
import pytest


@pytest.mark.asyncio
async def test_by_repo_menu_callback_skips_missing_tag(monkeypatch):
    stub_db_mod = types.ModuleType("database")
    stub_db_mod.DatabaseManager = object
    stub_db_mod.db = types.SimpleNamespace(
        get_repo_tags_with_counts=lambda uid, max_tags=20: [
            {"count": 2},  # no tag
            {"tag": "repo:keep/me", "count": 1},
        ]
    )
    monkeypatch.setitem(__import__('sys').modules, "database", stub_db_mod)

    from conversation_handlers import show_by_repo_menu_callback
    from utils import TelegramUtils

    captured = {}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured["reply_markup"] = reply_markup

    monkeypatch.setattr(TelegramUtils, "safe_edit_message_text", fake_safe_edit_message_text)

    class DummyQuery:
        async def answer(self):
            return None

    class DummyUpdate:
        def __init__(self):
            self.callback_query = DummyQuery()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=77)

    class Ctx:
        def __init__(self):
            self.user_data = {}

    u = DummyUpdate()
    c = Ctx()
    await show_by_repo_menu_callback(u, c)
    rm = captured.get("reply_markup")
    assert rm is not None
    texts = [btn.text for row in rm.inline_keyboard for btn in row]
    # נוודא שהתגית התקינה נשמרה ורשומת ה-no-tag לא יצרה כפתור
    assert any("repo:keep/me" in t for t in texts)
    assert not any("(" in t and ")" in t and t.startswith(" (") for t in texts)

