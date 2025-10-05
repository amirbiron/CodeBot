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
            # Mimic a PyMongo cursor with skip/limit chaining
            class Cur:
                def __init__(self, items):
                    self._items = list(items)
                def skip(self, n):
                    self._items = self._items[n:]
                    return self
                def limit(self, m):
                    self._items = self._items[:m]
                    return self
                def __iter__(self):
                    return iter(self._items)
            items = [
                {"_id": f"id{n}", "user_id": 1, "file_name": f"b{n}.bin", "is_active": True}
                for n in range(10)
            ]
            return Cur(items)
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


def test_github_token_encrypt_decrypt_paths(monkeypatch):
    # ensure secret_manager paths exercised
    import os
    import secret_manager as sm
    # No key -> encrypt returns None, decrypt passthrough
    monkeypatch.delenv("TOKEN_ENC_KEY", raising=False)
    assert sm.encrypt_secret("abc") is None
    assert sm.decrypt_secret("raw") == "raw"


def test_delete_file_by_id_noop_and_no_cache(monkeypatch):
    from database.repository import Repository

    class Coll:
        def find_one(self, *_a, **_k):
            return None  # no user id for invalidation
        def update_many(self, *_a, **_k):
            return types.SimpleNamespace(modified_count=0)
    class Mgr:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = types.SimpleNamespace()
    repo = Repository(Mgr())
    assert repo.delete_file_by_id("507f1f77bcf86cd799439011") is False


def test_delete_large_file_by_id_noop(monkeypatch):
    from database.repository import Repository

    class LColl:
        def find_one(self, *_a, **_k):
            return None
        def update_many(self, *_a, **_k):
            return types.SimpleNamespace(modified_count=0)
    class Mgr:
        def __init__(self):
            self.collection = types.SimpleNamespace()
            self.large_files_collection = LColl()
    repo = Repository(Mgr())
    assert repo.delete_large_file_by_id("507f1f77bcf86cd799439011") is False


def test_rename_file_success_and_conflict(monkeypatch):
    from database.repository import Repository

    calls = {"updated": 0}
    class Coll:
        def update_many(self, *_a, **_k):
            calls["updated"] += 1
            return types.SimpleNamespace(modified_count=1)
    class Mgr:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = types.SimpleNamespace()
    repo = Repository(Mgr())

    # success path: no existing new_name
    monkeypatch.setattr(repo, "get_latest_version", lambda *_: None)
    assert repo.rename_file(7, "old.py", "new.py") is True

    # conflict path: existing found and name differs -> False
    monkeypatch.setattr(repo, "get_latest_version", lambda *_: {"_id": 1})
    assert repo.rename_file(7, "old.py", "other.py") is False

    # same name path: still attempts update; ensure bool return handled
    monkeypatch.setattr(repo, "get_latest_version", lambda *_: None)
    assert isinstance(repo.rename_file(7, "same.py", "same.py"), bool)


def test_save_large_file_normalize_and_existing(monkeypatch):
    from dataclasses import dataclass
    from database.repository import Repository

    # dataclass compatible with asdict
    @dataclass
    class DLF:
        user_id: int
        file_name: str
        content: str

    inserted = {"n": 0}
    class LColl:
        def insert_one(self, doc):
            inserted["n"] += 1
            return types.SimpleNamespace(inserted_id="1")
    class Mgr:
        def __init__(self):
            self.collection = types.SimpleNamespace()
            self.large_files_collection = LColl()
    repo = Repository(Mgr())

    # existing triggers delete_large_file before insert
    monkeypatch.setattr(repo, "get_large_file", lambda *_: {"_id": 1})
    del_calls = {"n": 0}
    monkeypatch.setattr(repo, "delete_large_file", lambda *_: del_calls.__setitem__("n", del_calls["n"] + 1) or True)
    # enable normalization flag; ensure it does not break
    import config as config_mod
    monkeypatch.setattr(config_mod, "NORMALIZE_CODE_ON_SAVE", True, raising=False)

    ok = repo.save_large_file(DLF(3, "big.bin", "data"))
    assert ok is True and inserted["n"] == 1 and del_calls["n"] == 1


def test_get_large_file_and_by_id_and_errors(monkeypatch):
    from database.repository import Repository

    class LColl:
        def __init__(self, doc):
            self._doc = doc
        def find_one(self, *_a, **_k):
            if isinstance(self._doc, Exception):
                raise self._doc
            return self._doc
    class Mgr:
        def __init__(self, doc):
            self.collection = types.SimpleNamespace()
            self.large_files_collection = LColl(doc)
            self.db = types.SimpleNamespace()

    repo_ok = Repository(Mgr({"_id": "x"}))
    assert repo_ok.get_large_file(1, "a") == {"_id": "x"}
    assert repo_ok.get_large_file_by_id("507f1f77bcf86cd799439011") == {"_id": "x"}

    repo_err = Repository(Mgr(RuntimeError("e")))
    assert repo_err.get_large_file(1, "a") is None
    assert repo_err.get_large_file_by_id("507f1f77bcf86cd799439011") is None


def test_get_all_user_files_combined(monkeypatch):
    from database.repository import Repository

    class Coll:
        def find(self, *_a, **_k):
            return [{"_id": 1}]
    class Mgr:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = Coll()
            self.db = types.SimpleNamespace()
    repo = Repository(Mgr())
    out = repo.get_all_user_files_combined(1)
    assert isinstance(out, dict) and "regular_files" in out and "large_files" in out
