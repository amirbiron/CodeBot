import types
from datetime import datetime, timezone
import pytest


def test_repository_id_operations_invalid_objectid(monkeypatch):
    from database.repository import Repository

    class DummyCollection:
        def __init__(self):
            self.updated = None
            self.deleted = None
        def update_many(self, flt, upd):
            self.updated = (flt, upd)
            return types.SimpleNamespace(modified_count=0)
        def delete_many(self, flt):
            self.deleted = flt
            return types.SimpleNamespace(deleted_count=0)
        def count_documents(self, *a, **k):
            return 0
        def aggregate(self, *a, **k):
            return []

    class DummyManager:
        def __init__(self):
            self.collection = DummyCollection()
            self.large_files_collection = DummyCollection()

    repo = Repository(DummyManager())

    # invalid ids should safely return False paths via exception handler
    assert repo.delete_file_by_id("not_an_object_id") is False
    assert repo.restore_file_by_id(user_id=1, file_id="bad") is False
    assert repo.purge_file_by_id(user_id=1, file_id="bad") is False


@pytest.mark.asyncio
async def test_handle_callback_query_direct_restore_and_purge(monkeypatch):
    import conversation_handlers as ch

    class Repo:
        def list_deleted_files(self, *a, **k):
            return ([], 0)
        def restore_file_by_id(self, user_id, fid):
            return True
        def purge_file_by_id(self, user_id, fid):
            return True

    class DummyDB:
        def __init__(self, repo):
            self._repo = repo
        def _get_repo(self):
            return self._repo

    mod = types.ModuleType("database")
    mod.db = DummyDB(Repo())
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

    # capture safe edits
    async def fake_safe_edit_message_text(*a, **k):
        return None
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
            return types.SimpleNamespace(id=11)

    ctx = types.SimpleNamespace(user_data={})
    # direct restore/purge hits specific branches
    await ch.handle_callback_query(U("recycle_restore:someid"), ctx)
    await ch.handle_callback_query(U("recycle_purge:someid"), ctx)
