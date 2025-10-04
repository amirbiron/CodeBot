import types
import pytest


@pytest.mark.asyncio
async def test_handle_callback_query_recycle_flow(monkeypatch):
    import conversation_handlers as ch

    calls = {"restore": [], "purge": []}

    class DummyRepo:
        def list_deleted_files(self, user_id, page=1, per_page=10):
            # create two items to ensure rows rendered
            return ([{"_id": "idA", "file_name": "a.py"}, {"_id": "idB", "file_name": "b.js"}], 2)
        def restore_file_by_id(self, user_id, fid):
            calls["restore"].append((user_id, fid))
            return True
        def purge_file_by_id(self, user_id, fid):
            calls["purge"].append((user_id, fid))
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
        captured["parse_mode"] = parse_mode
    from utils import TelegramUtils
    monkeypatch.setattr(TelegramUtils, "safe_edit_message_text", fake_safe_edit_message_text)

    class Q:
        def __init__(self, data):
            self.data = data
            self.answers = []
            self.message = types.SimpleNamespace()
        async def answer(self, *a, **k):
            self.answers.append(k)
        async def edit_message_text(self, *a, **k):
            captured["edited"] = True

    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=55)

    class Ctx:
        def __init__(self):
            self.user_data = {}

    # Navigate to recycle bin
    u = U("recycle_bin")
    c = Ctx()
    await ch.handle_callback_query(u, c)
    rm = captured.get("reply_markup")
    assert rm is not None
    # Now restore and purge via the handler
    u2 = U("recycle_restore:idA")
    await ch.handle_callback_query(u2, c)
    u3 = U("recycle_purge:idB")
    await ch.handle_callback_query(u3, c)

    assert (55, "idA") in calls["restore"]
    assert (55, "idB") in calls["purge"]
