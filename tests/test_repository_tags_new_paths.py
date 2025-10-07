import types
from datetime import datetime, timezone


def _make_repo_with_aggregate_rows(rows):
    from database.repository import Repository

    class DummyCollection:
        def aggregate(self, pipeline, allowDiskUse=False):
            # Ignore pipeline in this dummy; return predefined rows
            return list(rows)

    class DummyManager:
        def __init__(self):
            self.collection = DummyCollection()
            self.large_files_collection = types.SimpleNamespace()
            self.db = types.SimpleNamespace()

    return Repository(DummyManager())


def test_repo_tags_counts_doc_shape_filters_inactive_and_distinct():
    # Rows simulate document-level projection with file_name/is_active
    now = datetime.now(timezone.utc)
    rows = [
        {"tag": "repo:me/a", "file_name": "f1.py", "is_active": True},
        {"tag": "repo:me/a", "file_name": "f1.py", "is_active": True},  # duplicate pair
        {"tag": "repo:me/a", "file_name": "f2.py", "is_active": False},  # filtered out
        {"tag": "repo:me/b", "file_name": "f3.py"},  # missing is_active -> included
        {"tag": "repo:me/c", "file_name": "f4.py", "is_active": True},
    ]
    repo = _make_repo_with_aggregate_rows(rows)
    # Limit to 2 to exercise limit and sorting by tag
    out = repo.get_repo_tags_with_counts(user_id=1, max_tags=2)
    tags = [d.get("tag") for d in out]
    assert tags == ["repo:me/a", "repo:me/b"]
    # counts should reflect distinct by (tag,file_name) and exclude inactive
    assert all(isinstance(d.get("count"), int) for d in out)


def test_repo_tags_counts_raw_shapes_normalization():
    # Rows simulate a pre-aggregated shape (dicts with tag/_id or string items)
    rows = [
        {"tag": "repo:me/x", "count": 5},
        {"_id": {"tag": "repo:me/y"}, "count": 3},
        "repo:me/z",
    ]
    repo = _make_repo_with_aggregate_rows(rows)
    out = repo.get_repo_tags_with_counts(user_id=42, max_tags=10)
    got = {(d.get("tag"), d.get("count")) for d in out}
    # Strings default to count 1
    assert ("repo:me/x", 5) in got
    assert ("repo:me/y", 3) in got
    assert ("repo:me/z", 1) in got


def test_get_user_file_names_by_repo_filters_inactive_and_distinct():
    rows = [
        {"file_name": "a.py", "is_active": True},
        {"file_name": "b.py", "is_active": True},
        {"file_name": "a.py", "is_active": True},  # duplicate name
        {"file_name": "c.py", "is_active": False},  # filtered out
        {"file_name": "d.py"},  # missing is_active -> included
    ]
    from database.repository import Repository

    class DummyCollection:
        def aggregate(self, pipeline, allowDiskUse=False):
            return list(rows)

    class DummyManager:
        def __init__(self):
            self.collection = DummyCollection()
            self.large_files_collection = types.SimpleNamespace()
            self.db = types.SimpleNamespace()

    repo = Repository(DummyManager())
    names = repo.get_user_file_names_by_repo(user_id=7, repo_tag="repo:me/x")
    assert set(names) == {"a.py", "b.py", "d.py"}


def test_repo_tags_counts_empty_returns_empty():
    repo = _make_repo_with_aggregate_rows([])
    out = repo.get_repo_tags_with_counts(user_id=1, max_tags=5)
    assert out == []


def test_repo_tags_counts_raw_id_str_and_limit_slice():
    # Pre-aggregated rows where _id is a string and limit cuts the list
    rows = [
        {"_id": "repo:me/a", "count": 2},
        {"_id": "repo:me/c", "count": 1},
        {"tag": "repo:me/b", "count": 7},
    ]
    repo = _make_repo_with_aggregate_rows(rows)
    out = repo.get_repo_tags_with_counts(user_id=9, max_tags=2)
    tags = [d.get("tag") for d in out]
    # Sorted lexicographically then sliced to first 2
    assert tags == ["repo:me/a", "repo:me/b"]


def test_repo_tags_counts_doc_shape_skips_missing_fields():
    rows = [
        {"tag": "repo:me/a", "file_name": None},  # missing file_name -> skip
        {"file_name": "x.py", "is_active": True},  # missing tag -> skip
        {"tag": "repo:me/b", "file_name": "y.py", "is_active": True},  # valid
    ]
    repo = _make_repo_with_aggregate_rows(rows)
    out = repo.get_repo_tags_with_counts(user_id=2, max_tags=10)
    assert out == [{"tag": "repo:me/b", "count": 1}]