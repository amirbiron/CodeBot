import types

def test_delete_file_by_id_true(monkeypatch):
    # collection returns modified_count=1 and find_one yields a user_id for invalidation
    class Coll:
        def find_one(self, *_a, **_k):
            return {"user_id": 3}
        def update_many(self, *_a, **_k):
            return types.SimpleNamespace(modified_count=1)
    class M:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = Coll()
            self.db = types.SimpleNamespace()
    from database.repository import Repository
    repo = Repository(M())
    # should return True
    assert repo.delete_file_by_id("507f1f77bcf86cd799439011") is True
