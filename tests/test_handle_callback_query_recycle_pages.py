import types
import pytest


@pytest.mark.asyncio
async def test_handle_callback_query_recycle_pagination_first_and_last(monkeypatch):
    import conversation_handlers as ch

    PAGE_SIZE = 10

    class DummyRepo:
        def list_deleted_files(self, user_id, page=1, per_page=10):
            # total 25 items => 3 pages
            total = 25
            count = per_page if page < 3 else (total - 2 * per_page)
            items = [{"_id": f"id{page}_{i}", "file_name": f"f{page}_{i}.py"} for i in range(count)]
            return (items, total)
        def restore_file_by_id(self, *a, **k):
            return True
        def purge_file_by_id(self, *a, **k):
            return True

    class DummyDB:
        def __init__(self, repo):
            self._repo = repo
        def _get_repo(self):
            return self._repo

    mod = types.ModuleType("database")
    mod.db = DummyDB(DummyRepo())
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    captured = {}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured["reply_markup"] = reply_markup
        captured["text"] = text
    from utils import TelegramUtils
    monkeypatch.setattr(TelegramUtils, "safe_edit_message_text", fake_safe_edit_message_text)

    class Q:
        def __init__(self, data):
            self.data = data
            self.answers = []
        async def answer(self, *a, **k):
            self.answers.append(k)
        async def edit_message_text(self, *a, **k):
            return None

    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=10)

    class Ctx:
        def __init__(self):
            self.user_data = {}

    # First page
    u1 = U("recycle_page_1")
    c = Ctx()
    await ch.handle_callback_query(u1, c)
    kb1 = captured.get("reply_markup").inline_keyboard
    # Last row is Back; previous row is nav
    nav1 = kb1[-2] if len(kb1) >= 2 else []
    vals1 = [b.callback_data for b in nav1]
    assert any(v == "recycle_page_2" for v in vals1)
    # no prev on first page
    assert not any(v == "recycle_page_0" for v in vals1)

    # Last page
    u3 = U("recycle_page_3")
    await ch.handle_callback_query(u3, c)
    kb3 = captured.get("reply_markup").inline_keyboard
    nav3 = kb3[-2] if len(kb3) >= 2 else []
    vals3 = [b.callback_data for b in nav3]
    assert any(v == "recycle_page_2" for v in vals3)
    # no next after last
    assert not any(v == "recycle_page_4" for v in vals3)
