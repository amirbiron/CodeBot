import types
import pytest


@pytest.mark.asyncio
async def test_show_by_repo_menu_labels_include_count(monkeypatch):
    stub_db_mod = types.ModuleType("database")
    stub_db_mod.DatabaseManager = object
    stub_db_mod.db = types.SimpleNamespace(
        get_repo_tags_with_counts=lambda user_id, max_tags=20: [
            {"tag": "repo:me/app", "count": 7},
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
            return types.SimpleNamespace(id=55)

    u = DummyUpdate()
    class Ctx:
        def __init__(self):
            self.user_data = {}
    c = Ctx()

    await show_by_repo_menu(u, c)
    rm = u.message.rm
    assert rm is not None
    # ודא שה-Label כולל את הספירה בסוגריים
    texts = [btn.text for row in rm.inline_keyboard for btn in row]
    assert any("repo:me/app (7)" in t for t in texts)

