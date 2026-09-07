import types
import pytest


def _repo_with_mutation_stubs():
    # Dummy collection with required mutation methods
    class Coll:
        def __init__(self):
            self.calls = {}
        def find_one(self, *_a, **_k):
            return {"user_id": 7}
        def update_many(self, *_a, **_k):
            return types.SimpleNamespace(modified_count=1)
        def delete_many(self, *_a, **_k):
            return types.SimpleNamespace(deleted_count=1)
        def find(self, *_a, **_k):
            return [{"_id": "507f1f77bcf86cd799439011", "file_name": "a.py"}]
        def distinct(self, *_a, **_k):
            return ["a.py"]
        def aggregate(self, *_a, **_k):
            return []
    class DummyManager:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = Coll()
            self.db = types.SimpleNamespace(users=None)
    from database.repository import Repository
    return Repository(DummyManager())


@pytest.mark.parametrize("method,args,expect_modified", [
    ("soft_delete_files_by_ids", (7, ["507f1f77bcf86cd799439011"]), 1),
    ("restore_file_by_id", (7, "507f1f77bcf86cd799439011"), True),
    ("purge_file_by_id", (7, "507f1f77bcf86cd799439011"), True),
])
def test_mutations_invalidate_cache(monkeypatch, method, args, expect_modified):
    repo = _repo_with_mutation_stubs()
    # capture cache invalidations
    calls = {"n": 0}
    from database import repository as repo_mod
    monkeypatch.setattr(repo_mod.cache, "invalidate_user_cache", lambda *_: calls.__setitem__("n", calls["n"] + 1))
    fn = getattr(repo, method)
    res = fn(*args)
    # הטענה כאן הייתה ``>= 0``, שאינה יכולה ליפול. אינוולידציה שלא רצה
    # אחרי מוטציה היא בדיוק הבאג שהבדיקה נקראת על שמו.
    assert calls["n"] >= 1, method
    assert bool(res) is True


def test_soft_delete_files_by_names_invalidate(monkeypatch):
    repo = _repo_with_mutation_stubs()
    calls = {"n": 0}
    from database import repository as repo_mod
    monkeypatch.setattr(repo_mod.cache, "invalidate_user_cache", lambda *_: calls.__setitem__("n", calls["n"] + 1))
    res = repo.soft_delete_files_by_names(7, ["a.py", "b.py"])
    assert res >= 0
    assert calls["n"] >= 1
