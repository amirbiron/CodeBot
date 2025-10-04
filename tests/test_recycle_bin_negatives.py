import types
import pytest


@pytest.mark.asyncio
async def test_recycle_restore_and_purge_invalid_id(monkeypatch):
    import conversation_handlers as ch

    class DummyRepo:
        def list_deleted_files(self, user_id, page=1, per_page=10):
            return ([], 0)
        def restore_file_by_id(self, user_id, fid):
            return False
        def purge_file_by_id(self, user_id, fid):
            return False

    class DummyDB:
        def __init__(self, repo):
            self._repo = repo
        def _get_repo(self):
            return self._repo

    mod = types.ModuleType("database")
    mod.db = DummyDB(DummyRepo())
    monkeypatch.setitem(__import__('sys').modules, "database", mod)

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
            return types.SimpleNamespace(id=99)

    class Ctx:
        def __init__(self):
            self.user_data = {}

    u = U("recycle_restore:")
    await ch.recycle_restore(u, Ctx())
    assert any(a.get("show_alert") for a in u.callback_query.answers)

    u2 = U("recycle_purge:")
    await ch.recycle_purge(u2, Ctx())
    assert any(a.get("show_alert") for a in u2.callback_query.answers)


def test_repository_restore_and_purge_paths(monkeypatch):
    from database.repository import Repository
    from datetime import datetime, timezone
    from bson import ObjectId

    class DummyCollection:
        def __init__(self):
            self.update_calls = []
            self.delete_calls = []
        def update_many(self, flt, upd):
            self.update_calls.append((flt, upd))
            return types.SimpleNamespace(modified_count=1)
        def delete_many(self, flt):
            self.delete_calls.append(flt)
            return types.SimpleNamespace(deleted_count=1)
        def count_documents(self, *a, **k):
            return 0
        def aggregate(self, *a, **k):
            return []

    class DummyManager:
        def __init__(self):
            self.collection = DummyCollection()
            self.large_files_collection = DummyCollection()

    repo = Repository(DummyManager())

    # restore path
    oid = str(ObjectId())
    ok = repo.restore_file_by_id(user_id=5, file_id=oid)
    assert ok is True

    # purge path
    ok2 = repo.purge_file_by_id(user_id=5, file_id=str(ObjectId()))
    assert ok2 is True
