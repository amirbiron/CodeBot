import types
import pytest


@pytest.mark.asyncio
async def test_show_by_repo_menu_skips_row_with_bad_count(monkeypatch):
    # תגית עם count לא מספרי צריכה להידחות (הקוד מדלג כאשר parsing נכשל)
    stub_db_mod = types.ModuleType("database")
    stub_db_mod.DatabaseManager = object
    stub_db_mod.db = types.SimpleNamespace(
        get_repo_tags_with_counts=lambda uid, max_tags=20: [
            {"tag": "repo:bad/count", "count": "foo"},
            {"tag": "repo:good/ok", "count": 1},
        ]
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
            return types.SimpleNamespace(id=10)

    class Ctx:
        def __init__(self):
            self.user_data = {}

    u = DummyUpdate()
    c = Ctx()
    await show_by_repo_menu(u, c)
    rm = u.message.rm
    assert rm is not None
    texts = [btn.text for row in rm.inline_keyboard for btn in row]
    assert any("repo:good/ok" in t for t in texts)
    assert all("repo:bad/count" not in t for t in texts)

