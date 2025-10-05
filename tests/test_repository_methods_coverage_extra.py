import types


def _repo_with_aggregate_returning(items):
    from database.repository import Repository
    class Coll:
        def aggregate(self, *_a, **_k):
            return items
        def find_one(self, *a, **k):
            return None
        def find(self, *a, **k):
            return []
    class Mgr:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = Coll()
            self.db = types.SimpleNamespace()
    return Repository(Mgr())


def test_repo_tags_normalizes_when_tag_field_present():
    repo = _repo_with_aggregate_returning([{"tag": "repo:me/x", "count": 3}, {"tag": "repo:me/y", "count": 2}])
    rows = repo.get_repo_tags_with_counts(1)
    assert {r.get('tag') for r in rows} == {"repo:me/x", "repo:me/y"}


def test_repo_tags_normalizes_when_id_dict_present():
    repo = _repo_with_aggregate_returning([{"_id": {"tag": "repo:me/x"}, "count": 1}])
    rows = repo.get_repo_tags_with_counts(1)
    assert rows and rows[0]['tag'] == "repo:me/x"


def test_repo_tags_normalizes_when_item_is_string():
    repo = _repo_with_aggregate_returning(["repo:me/x", "repo:me/y"])
    rows = repo.get_repo_tags_with_counts(1)
    assert {r.get('tag') for r in rows} == {"repo:me/x", "repo:me/y"}


def test_get_user_large_files_paging_and_errors(monkeypatch):
    from database.repository import Repository

    class Coll:
        def __init__(self, total=5):
            self._total = total
        def count_documents(self, *_a, **_k):
            return self._total
        def find(self, *_a, **_k):
            return [
                {"_id": f"id{n}", "user_id": 1, "file_name": f"b{n}.bin", "is_active": True}
                for n in range(10)
            ]
    class Mgr:
        def __init__(self, coll):
            self.collection = types.SimpleNamespace()
            self.large_files_collection = coll
            self.db = types.SimpleNamespace()

    # normal path
    repo = Repository(Mgr(Coll(total=7)))
    files, total = repo.get_user_large_files(1, page=1, per_page=8)
    assert isinstance(files, list) and total == 7

    # error path
    class Bad:
        def count_documents(self, *_a, **_k):
            raise RuntimeError("x")
        def find(self, *_a, **_k):
            raise RuntimeError("y")
    repo2 = Repository(Mgr(Bad()))
    files2, total2 = repo2.get_user_large_files(1, page=1, per_page=8)
    assert files2 == [] and total2 == 0
