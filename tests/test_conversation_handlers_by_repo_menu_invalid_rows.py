import types
import pytest


@pytest.mark.asyncio
async def test_show_by_repo_menu_ignores_bad_rows(monkeypatch):
    # rows שמכילים מחרוזת לא תקינה ומילון עם count לא ספרתי
    bad_rows = ["oops", {"tag": "repo:good/one", "count": "x"}, {"tag": "repo:ok", "count": 2}]

    stub_db_mod = types.ModuleType("database")
    stub_db_mod.DatabaseManager = object
    stub_db_mod.db = types.SimpleNamespace(
        get_repo_tags_with_counts=lambda user_id, max_tags=20: bad_rows
    )
    monkeypatch.setitem(__import__('sys').modules, "database", stub_db_mod)

    from conversation_handlers import show_by_repo_menu

    class DummyMessage:
        def __init__(self):
            self.rm = None
        async def reply_text(self, text=None, reply_markup=None):
            self.rm = reply_markup

    class DummyUpdate:
        def __init__(self):
            self.message = DummyMessage()
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=1)

    class Ctx:
        def __init__(self):
            self.user_data = {}

    u = DummyUpdate()
    c = Ctx()
    await show_by_repo_menu(u, c)

    rm = u.message.rm
    assert rm is not None
    callbacks = [row[0].callback_data for row in rm.inline_keyboard]
    # רק הרשומה התקינה (repo:ok) אמורה להיכנס
    assert any(cd == "by_repo:repo:ok" for cd in callbacks)
    assert not any(cd == "by_repo:repo:good/one" for cd in callbacks)

