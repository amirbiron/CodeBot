import types
import pytest


@pytest.mark.asyncio
async def test_recycle_menu_shows_items_and_actions(monkeypatch):
    # Arrange minimal db and handlers
    import conversation_handlers as ch

    # Fake repo with deleted files listing
    class DummyRepo:
        def __init__(self):
            self.calls = []
        def list_deleted_files(self, user_id, page=1, per_page=10):
            return ([{"_id": "aaa", "file_name": "x.py"}, {"_id": "bbb", "file_name": "y.js"}], 2)
        def restore_file_by_id(self, user_id, fid):
            self.calls.append(("restore", user_id, fid))
            return True
        def purge_file_by_id(self, user_id, fid):
            self.calls.append(("purge", user_id, fid))
            return True

    # Monkeypatch database.db to expose _get_repo
    class DummyDB:
        def __init__(self, repo):
            self._repo = repo
        def _get_repo(self):
            return self._repo

    repo = DummyRepo()
    mod = types.ModuleType("database")
    mod.db = DummyDB(repo)
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    captured = {}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured["text"] = text
        captured["reply_markup"] = reply_markup
    from utils import TelegramUtils
    monkeypatch.setattr(TelegramUtils, "safe_edit_message_text", fake_safe_edit_message_text)

    class Q:
        def __init__(self, data):
            self.data = data
            self.answered = False
        async def answer(self, *a, **k):
            self.answered = True

    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=123)

    class Ctx:
        def __init__(self):
            self.user_data = {}

    # Act: open recycle bin
    u = U("recycle_bin")
    c = Ctx()
    await ch.show_recycle_bin(u, c)

    # Assert menu contains two rows with restore/purge actions
    rm = captured.get("reply_markup")
    assert rm is not None
    rows = rm.inline_keyboard
    # two file rows + maybe nav/back; ensure first two are our actions
    assert rows[0][0].callback_data.startswith("recycle_restore:")
    assert rows[0][1].callback_data.startswith("recycle_purge:")
    assert rows[1][0].callback_data.startswith("recycle_restore:")
    assert rows[1][1].callback_data.startswith("recycle_purge:")

    # Act: restore and purge
    u2 = U("recycle_restore:aaa")
    await ch.recycle_restore(u2, c)
    u3 = U("recycle_purge:bbb")
    await ch.recycle_purge(u3, c)

    # Assert repo calls
    assert ("restore", 123, "aaa") in repo.calls
    assert ("purge", 123, "bbb") in repo.calls


def test_repository_soft_delete_and_ttl(monkeypatch):
    from database.repository import Repository
    from datetime import datetime, timezone

    class DummyCollection:
        def __init__(self):
            self.updated = None
        def update_many(self, filter, update):
            self.updated = (filter, update)
            return types.SimpleNamespace(modified_count=1)
        def count_documents(self, *a, **k):
            return 0
        def aggregate(self, *a, **k):
            return []
    class DummyManager:
        def __init__(self):
            self.collection = DummyCollection()
            self.large_files_collection = DummyCollection()
    repo = Repository(DummyManager())

    # Soft delete by name sets deleted_at and deleted_expires_at
    ok = repo.delete_file(user_id=1, file_name="a.py")
    assert ok is True
    f, upd = repo.manager.collection.updated
    assert f["user_id"] == 1 and f["file_name"] == "a.py"
    sets = upd["$set"]
    assert sets["is_active"] is False
    assert isinstance(sets["deleted_at"], datetime)
    assert isinstance(sets["deleted_expires_at"], datetime)
    assert sets["deleted_expires_at"] > sets["deleted_at"]
