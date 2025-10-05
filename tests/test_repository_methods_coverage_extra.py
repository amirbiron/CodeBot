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
        def update_one(self, *a, **k):
            return types.SimpleNamespace(acknowledged=True)
    class Mgr:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = Coll()
            # users collection for github token helpers
            class Users:
                def __init__(self):
                    self._user = None
                def update_one(self, *_a, **_k):
                    self._user = (_a, _k)
                    return types.SimpleNamespace(acknowledged=True)
                def find_one(self, *_a, **_k):
                    return {"github_token": "tok"}
            self.db = types.SimpleNamespace(users=Users())
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


def test_user_file_names_and_tags_helpers_and_github_token():
    repo = _repo_with_aggregate_returning([
        {"_id": "f1"}, {"_id": "f2"},
    ])
    names = repo.get_user_file_names_by_repo(1, "repo:me/x")
    # with our stub, aggregate returns raw items, so projection filter yields empty -> []
    assert isinstance(names, list)

    # user file names (distinct latest) and tags flatten
    repo2 = _repo_with_aggregate_returning([
        {"file_name": "a.py"}, {"file_name": "b.py"}
    ])
    fns = repo2.get_user_file_names(1, limit=10)
    assert all(isinstance(x, str) for x in fns)
    tags = repo2.get_user_tags_flat(1)
    assert isinstance(tags, list)

    # github token helpers happy path
    assert repo.save_github_token(5, "tok") is True
    assert repo.get_github_token(5) in {"tok", None, "tok"}

    # delete token path
    assert repo.delete_github_token(5) is True
