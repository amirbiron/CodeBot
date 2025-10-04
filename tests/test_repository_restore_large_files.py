import types
from bson import ObjectId


def test_restore_and_purge_large_files(monkeypatch):
    from database.repository import Repository

    # Collections: none in regular, present in large
    class Reg:
        def update_many(self, *a, **k):
            return types.SimpleNamespace(modified_count=0)
        def delete_many(self, *a, **k):
            return types.SimpleNamespace(deleted_count=0)
    class Large:
        def __init__(self):
            self.updated = 0
            self.deleted = 0
        def update_many(self, *a, **k):
            self.updated += 1
            return types.SimpleNamespace(modified_count=1)
        def delete_many(self, *a, **k):
            self.deleted += 1
            return types.SimpleNamespace(deleted_count=1)

    class DummyManager:
        def __init__(self):
            self.collection = Reg()
            self.large_files_collection = Large()

    repo = Repository(DummyManager())
    oid = str(ObjectId())

    # restore should succeed via large_files_collection
    assert repo.restore_file_by_id(5, oid) is True
    # purge should succeed via large_files_collection
    assert repo.purge_file_by_id(5, oid) is True
