import types
from bson import ObjectId

def test_restore_file_by_id_modified_count_zero(monkeypatch):
    from database.repository import Repository

    class DummyCollection:
        def update_many(self, flt, upd):
            return types.SimpleNamespace(modified_count=0)
    class DummyManager:
        def __init__(self):
            self.collection = DummyCollection()
            self.large_files_collection = DummyCollection()

    repo = Repository(DummyManager())
    oid = str(ObjectId())
    ok = repo.restore_file_by_id(user_id=9, file_id=oid)
    assert ok is False
