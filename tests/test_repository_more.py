import types
from datetime import datetime, timezone


def test_soft_delete_files_by_names_paths(monkeypatch):
    from database.repository import Repository

    class DummyCollection:
        def __init__(self, modified_count=2):
            self.modified_count = modified_count
            self.last = None
        def update_many(self, flt, upd):
            self.last = (flt, upd)
            return types.SimpleNamespace(modified_count=self.modified_count)
    class DummyManager:
        def __init__(self, coll):
            self.collection = coll
            self.large_files_collection = DummyCollection()
    # modified_count > 0
    coll = DummyCollection(modified_count=3)
    repo = Repository(DummyManager(coll))
    count = repo.soft_delete_files_by_names(7, ["a.py", "b.py", "a.py"])  # duplicates deduped in filter
    assert count == 3
    flt, upd = coll.last
    assert flt["user_id"] == 7 and "file_name" in flt and "$in" in flt["file_name"]
    assert upd["$set"]["is_active"] is False
    assert isinstance(upd["$set"]["updated_at"], datetime)

    # empty list returns 0 and does not call update_many
    coll2 = DummyCollection(modified_count=5)
    repo2 = Repository(DummyManager(coll2))
    assert repo2.soft_delete_files_by_names(1, []) == 0

    # modified_count = 0 path
    coll3 = DummyCollection(modified_count=0)
    repo3 = Repository(DummyManager(coll3))
    assert repo3.soft_delete_files_by_names(2, ["x"]) == 0


def test_get_user_stats_present_and_empty(monkeypatch):
    from database.repository import Repository

    class DummyCollection:
        def __init__(self, result_list):
            self._res = result_list
        def aggregate(self, *a, **k):
            return list(self._res)
    class DummyManager:
        def __init__(self, res):
            self.collection = DummyCollection(res)
            self.large_files_collection = DummyCollection([])

    # present result
    stats_doc = [{
        "_id": None,
        "total_files": 5,
        "total_versions": 11,
        "languages": ["python", "js"],
        "latest_activity": datetime.now(timezone.utc)
    }]
    repo = Repository(DummyManager(stats_doc))
    stats = repo.get_user_stats(42)
    assert stats.get("total_files") == 5
    assert "languages" in stats

    # empty result
    repo2 = Repository(DummyManager([]))
    stats2 = repo2.get_user_stats(42)
    assert stats2 == {"total_files": 0, "total_versions": 0, "languages": [], "latest_activity": None}


def test_delete_large_file_exception_returns_false(monkeypatch):
    from database.repository import Repository

    class BadCollection:
        def update_many(self, *a, **k):
            raise RuntimeError("boom")
    class DummyManager:
        def __init__(self):
            self.collection = types.SimpleNamespace()
            self.large_files_collection = BadCollection()

    repo = Repository(DummyManager())
    assert repo.delete_large_file(1, "big.txt") is False
