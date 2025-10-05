import types


def test_repo_helpers_error_paths(monkeypatch):
    from database.repository import Repository

    class BadAgg:
        def aggregate(self, *_a, **_k):
            raise RuntimeError("agg fail")
        def find(self, *_a, **_k):
            return []
        def find_one(self, *_a, **_k):
            return None

    class Mgr:
        def __init__(self):
            self.collection = BadAgg()
            self.large_files_collection = BadAgg()
            self.db = types.SimpleNamespace(users=types.SimpleNamespace(
                update_one=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("upd")),
                find_one=lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("find")),
            ))

    repo = Repository(Mgr())
    # helpers should return empty on errors
    assert repo.get_user_file_names_by_repo(1, "repo:me/x") == []
    assert repo.get_user_file_names(1, limit=5) == []
    assert repo.get_user_tags_flat(1) == []
    # list_deleted_files errors
    items, total = repo.list_deleted_files(1, page=1, per_page=10)
    assert items == [] and total == 0
    # github token helpers on errors
    assert repo.save_github_token(1, "tok") is False
    assert repo.get_github_token(1) is None
    assert repo.delete_github_token(1) is False


def test_rename_file_exception_returns_false(monkeypatch):
    from database.repository import Repository

    class Coll:
        def update_many(self, *_a, **_k):
            raise RuntimeError("boom")
    class Mgr:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = types.SimpleNamespace()
    repo = Repository(Mgr())
    assert repo.rename_file(1, "a.py", "b.py") is False


def test_save_large_file_insert_exception(monkeypatch):
    from dataclasses import dataclass
    from database.repository import Repository

    @dataclass
    class DLF:
        user_id: int
        file_name: str
        content: str

    class LColl:
        def insert_one(self, *_a, **_k):
            raise RuntimeError("ins")
    class Mgr:
        def __init__(self):
            self.collection = types.SimpleNamespace()
            self.large_files_collection = LColl()
    repo = Repository(Mgr())
    assert repo.save_large_file(DLF(2, "z.bin", "data")) is False
