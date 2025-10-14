import types
import pytest


@pytest.mark.asyncio
async def test_recycle_pagination_and_invalid_actions(monkeypatch):
    import conversation_handlers as ch

    class DummyRepo:
        def list_deleted_files(self, user_id, page=1, per_page=10):
            # Return different items per page to exercise nav
            if page == 1:
                items = [{"_id": "id1", "file_name": "a.py"}] * per_page
            else:
                items = [{"_id": "id2", "file_name": "b.js"}] * 5
            total = per_page + 5  # 2 pages
            return (items, total)
        def restore_file_by_id(self, user_id, fid):
            return True
        def purge_file_by_id(self, user_id, fid):
            return True

    class DummyDB:
        def __init__(self, repo):
            self._repo = repo
        def _get_repo(self):
            return self._repo

    repo = DummyRepo()
    mod = types.ModuleType("database")
    mod.db = DummyDB(repo)
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    captured = {"reply_markup": None}
    async def fake_safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
        captured["reply_markup"] = reply_markup
    from utils import TelegramUtils
    monkeypatch.setattr(TelegramUtils, "safe_edit_message_text", fake_safe_edit_message_text)

    class Q:
        def __init__(self, data):
            self.data = data
            self.answers = []
        async def answer(self, *a, **k):
            self.answers.append(k)

    class U:
        def __init__(self, data):
            self.callback_query = Q(data)
        @property
        def effective_user(self):
            return types.SimpleNamespace(id=7)

    class Ctx:
        def __init__(self):
            self.user_data = {}

    # Page 2 triggers nav "previous" button existence
    u = U("recycle_page_2")
    c = Ctx()
    await ch.show_recycle_bin(u, c)
    rm = captured.get("reply_markup")
    assert rm is not None
    nav_row = rm.inline_keyboard[-2] if len(rm.inline_keyboard) >= 2 else []
    # Expect at least one nav button present
    assert any(btn.callback_data.startswith("recycle_page_") for btn in nav_row)

    # Invalid restore (missing id) answers with alert
    u2 = U("recycle_restore:")
    await ch.recycle_restore(u2, c)
    assert any(k.get("show_alert") for k in u2.callback_query.answers)

    # Invalid purge (missing id) answers with alert
    u3 = U("recycle_purge:")
    await ch.recycle_purge(u3, c)
    assert any(k.get("show_alert") for k in u3.callback_query.answers)


def test_repository_delete_by_id_and_large_files(monkeypatch):
    from database.repository import Repository
    from datetime import datetime
    from bson import ObjectId

    class DummyCollection:
        def __init__(self):
            self.updated = None
            self.deleted = None
        def update_many(self, flt, upd):
            self.updated = (flt, upd)
            return types.SimpleNamespace(modified_count=1)
        def delete_many(self, flt):
            self.deleted = flt
            return types.SimpleNamespace(deleted_count=1)
        def count_documents(self, *a, **k):
            return 1
        def aggregate(self, *a, **k):
            return [{"_id": "z", "file_name": "z.py"}]

    class DummyManager:
        def __init__(self):
            self.collection = DummyCollection()
            self.large_files_collection = DummyCollection()

    repo = Repository(DummyManager())

    # delete_file_by_id with a valid ObjectId
    valid_id = str(ObjectId())
    rc = repo.delete_file_by_id(valid_id)
    # repository now returns bool for delete_file_by_id
    assert rc is True
    _flt, _upd = repo.manager.collection.updated
    assert _flt["_id"] is not None
    assert _upd["$set"]["is_active"] is False
    assert isinstance(_upd["$set"]["deleted_at"], datetime)
    assert isinstance(_upd["$set"]["deleted_expires_at"], datetime)

    # large files delete (by name and by id)
    ok1 = repo.delete_large_file(user_id=3, file_name="big.txt")
    from bson import ObjectId as _OID
    ok2 = repo.delete_large_file_by_id(str(_OID()))
    assert ok1 and ok2

    # list_deleted_files
    items, total = repo.list_deleted_files(user_id=1, page=1, per_page=10)
    assert isinstance(items, list) and isinstance(total, int)

    # restore and purge with valid ObjectId
    oid2 = str(ObjectId())
    assert repo.restore_file_by_id(user_id=1, file_id=oid2) is True
    assert repo.purge_file_by_id(user_id=1, file_id=oid2) is True
