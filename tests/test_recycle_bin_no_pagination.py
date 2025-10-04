import types
import pytest


@pytest.mark.asyncio
async def test_show_recycle_bin_no_pagination(monkeypatch):
    import conversation_handlers as ch

    class Repo:
        def list_deleted_files(self, user_id, page=1, per_page=10):
            # total less than page size
            items = [{"_id": "i", "file_name": "f.py"} for _ in range(5)]
            return (items, 5)

    class DummyDB:
        def __init__(self, repo):
            self._repo = repo
        def _get_repo(self):
            return self._repo

    mod = types.ModuleType("database")
    mod.db = DummyDB(Repo())
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
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None

    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=77)

    # invoke
    await ch.show_recycle_bin(U("recycle_bin"), types.SimpleNamespace(user_data={}))

    kb = captured.get("reply_markup").inline_keyboard
    # last row is Back, there should be no nav row before it when total < page size
    assert len(kb) >= 1
    if len(kb) >= 2:
        nav = kb[-2]
        vals = [b.callback_data for b in nav]
        # no recycle_page_* buttons should exist
        assert not any(v.startswith("recycle_page_") for v in vals)
