import types
import pytest


@pytest.mark.asyncio
async def test_show_by_repo_menu_aggregation(monkeypatch):
    # הזרקת מודול database מזויף לפני import של ה-handler כדי למנוע side-effects
    stub_db_mod = types.ModuleType("database")
    stub_db_mod.DatabaseManager = object  # רק כדי לספק את ה-import בקובץ
    stub_db_mod.db = types.SimpleNamespace(
        get_repo_tags_with_counts=lambda user_id, max_tags=20: [
            {"tag": "repo:me/app", "count": 3},
            {"tag": "repo:me/other", "count": 1},
        ]
    )
    monkeypatch.setitem(__import__('sys').modules, "database", stub_db_mod)

    from conversation_handlers import show_by_repo_menu

    class DummyMessage:
        def __init__(self):
            self.sent_text = None
            self.sent_reply_markup = None
        async def reply_text(self, text=None, reply_markup=None):
            self.sent_text = text
            self.sent_reply_markup = reply_markup

    class DummyUpdate:
        def __init__(self):
            self.message = DummyMessage()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=123)

    class DummyContext:
        def __init__(self):
            self.user_data = {}

    u = DummyUpdate()
    c = DummyContext()
    await show_by_repo_menu(u, c)

    # וידוא שבוצעה בניית מקלדת מתגיות
    rm = u.message.sent_reply_markup
    assert rm is not None
    rows = rm.inline_keyboard
    # מצפים לפחות לשורה אחת עם by_repo:repo:me/app ועוד כפתור חזרה
    callbacks = [row[0].callback_data for row in rows]
    assert any(cd == "by_repo:repo:me/app" for cd in callbacks)
    assert any(row[0].callback_data == "files" for row in rows if len(row) == 1)


@pytest.mark.asyncio
async def test_show_by_repo_menu_callback_aggregation(monkeypatch):
    # הזרקת database מזויף (עם תגיות)
    stub_db_mod = types.ModuleType("database")
    stub_db_mod.DatabaseManager = object
    stub_db_mod.db = types.SimpleNamespace(
        get_repo_tags_with_counts=lambda uid, max_tags=20: [
            {"tag": "repo:foo/bar", "count": 2},
        ]
    )
    monkeypatch.setitem(__import__('sys').modules, "database", stub_db_mod)

    from conversation_handlers import show_by_repo_menu_callback
    from utils import TelegramUtils

    captured = {}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured["reply_markup"] = reply_markup
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
            return types.SimpleNamespace(id=99)

    class DummyContext:
        def __init__(self):
            self.user_data = {}

    u = DummyUpdate()
    c = DummyContext()
    await show_by_repo_menu_callback(u, c)

    rm = captured.get("reply_markup")
    assert rm is not None
    rows = rm.inline_keyboard
    callbacks = [row[0].callback_data for row in rows]
    assert any(cd == "by_repo:repo:foo/bar" for cd in callbacks)
