import types
import pytest
from bson import ObjectId


def test_delete_file_by_id_invalidate_raises_but_returns_true(monkeypatch):
    from database.repository import Repository as RepoMod
    import database.repository as repo_mod

    class Coll:
        def find_one(self, *_a, **_k):
            return {"user_id": 7}
        def update_many(self, *_a, **_k):
            return types.SimpleNamespace(modified_count=1)
    class Mgr:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = types.SimpleNamespace()
    repo = RepoMod(Mgr())

    # invalidate_user_cache raises, but method should still return True
    monkeypatch.setattr(repo_mod.cache, "invalidate_user_cache", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    assert repo.delete_file_by_id("507f1f77bcf86cd799439011") is True


def test_delete_large_file_by_id_invalidate_exception(monkeypatch):
    from database.repository import Repository as RepoMod
    import database.repository as repo_mod

    class LColl:
        def find_one(self, *_a, **_k):
            return {"user_id": 5}
        def update_many(self, *_a, **_k):
            return types.SimpleNamespace(modified_count=1)
    class Mgr:
        def __init__(self):
            self.collection = types.SimpleNamespace()
            self.large_files_collection = LColl()
    repo = RepoMod(Mgr())

    monkeypatch.setattr(repo_mod.cache, "invalidate_user_cache", lambda *_: (_ for _ in ()).throw(RuntimeError("oops")))
    assert repo.delete_large_file_by_id(str(ObjectId())) is True


def test_purge_file_by_id_invalidate_exception(monkeypatch):
    from database.repository import Repository as RepoMod
    import database.repository as repo_mod

    class Coll:
        def delete_many(self, *_a, **_k):
            return types.SimpleNamespace(deleted_count=0)
    class LColl:
        def delete_many(self, *_a, **_k):
            return types.SimpleNamespace(deleted_count=1)
    class Mgr:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = LColl()
    repo = RepoMod(Mgr())

    monkeypatch.setattr(repo_mod.cache, "invalidate_user_cache", lambda *_: (_ for _ in ()).throw(RuntimeError("inv")))
    assert repo.purge_file_by_id(3, str(ObjectId())) is True


def test_get_user_large_files_list_fallback():
    from database.repository import Repository

    class LColl:
        def count_documents(self, *_a, **_k):
            return 9
        def find(self, *_a, **_k):
            # return a list to exercise list slicing branch
            return [
                {"_id": f"id{n}", "user_id": 1, "file_name": f"b{n}.bin", "is_active": True}
                for n in range(20)
            ]
    class Mgr:
        def __init__(self):
            self.collection = types.SimpleNamespace()
            self.large_files_collection = LColl()
    repo = Repository(Mgr())
    files, total = repo.get_user_large_files(1, page=2, per_page=5)
    assert total == 9 and len(files) == 5 and files[0]["_id"] == "id5"


def test_get_regular_files_paginated_exception(monkeypatch):
    from database.repository import Repository

    class Coll:
        def aggregate(self, *_a, **_k):
            raise RuntimeError("agg")
    class Mgr:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = types.SimpleNamespace()
            self.db = types.SimpleNamespace()
    repo = Repository(Mgr())
    items, total = repo.get_regular_files_paginated(1, 1, 10)
    assert items == [] and total == 0
