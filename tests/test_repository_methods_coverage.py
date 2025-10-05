import types
import datetime as dt
import pytest


def _make_repo_with_docs(docs):
    class DummyCollection:
        def __init__(self, rows):
            self._rows = list(rows)
        def aggregate(self, pipeline, allowDiskUse=False):  # noqa: N803
            # return rows as-is for basic branches used in tests
            return list(self._rows)
        def find_one(self, *_a, **_k):
            return None
        def find(self, *_a, **_k):
            return []
        def update_many(self, *_a, **_k):
            return types.SimpleNamespace(modified_count=0)
        def insert_one(self, *_a, **_k):
            return types.SimpleNamespace(inserted_id=None)
    class DummyManager:
        def __init__(self, rows):
            self.collection = DummyCollection(rows)
            self.large_files_collection = DummyCollection([])
            self.db = types.SimpleNamespace(users=None)
    from database.repository import Repository
    return Repository(DummyManager(docs))


def test_search_code_smoke():
    now = dt.datetime.now(dt.timezone.utc)
    docs = [{
        "_id": "1", "file_name": "a.py", "code": "print(1)",
        "programming_language": "python", "updated_at": now, "is_active": True
    }]
    repo = _make_repo_with_docs(docs)
    out = repo.search_code(1, query="a", programming_language=None, tags=None, limit=5)
    assert isinstance(out, list)


def test_get_user_files_smoke():
    now = dt.datetime.now(dt.timezone.utc)
    docs = [{
        "_id": "2", "file_name": "b.py", "code": "x", "programming_language": "python", "updated_at": now, "is_active": True
    }]
    repo = _make_repo_with_docs(docs)
    out = repo.get_user_files(1, limit=1)
    assert isinstance(out, list)


def test_repo_tags_with_counts_projection_shape():
    from database.repository import Repository
    # emulate post-aggregate normalization on repo.get_repo_tags_with_counts path
    class DummyCollection:
        def aggregate(self, *_a, **_k):
            return [{"_id": "repo:me/x", "count": 3}, {"_id": "repo:me/y", "count": 2}]
    class DummyManager:
        def __init__(self):
            self.collection = DummyCollection()
            self.large_files_collection = DummyCollection()
            self.db = types.SimpleNamespace()
    repo = Repository(DummyManager())
    rows = repo.get_repo_tags_with_counts(1)
    assert {r.get('tag') for r in rows} == {"repo:me/x", "repo:me/y"}
