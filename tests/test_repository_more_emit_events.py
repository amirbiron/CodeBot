import types
import pytest


def _capture_emit(mod):
    captured = {"events": []}
    def _emit(event, severity="info", **fields):
        captured["events"].append((event, severity, fields))
    return captured, _emit


def _repo_with_collections(coll=None, lcoll=None, brcoll=None):
    import database.repository as repo_mod
    mgr = types.SimpleNamespace(
        collection=coll or types.SimpleNamespace(),
        large_files_collection=lcoll or types.SimpleNamespace(),
        back_up=None,
        backupratings=None,
        back_up_ratings=None,
        back_up_ratings_collection=None,
        backup_ratings_collection=brcoll,
        db=types.SimpleNamespace(users=types.SimpleNamespace())
    )
    return repo_mod.Repository(mgr)


def test_many_repository_errors_emit_events(monkeypatch):
    import database.repository as repo_mod
    cap, _emit = _capture_emit(repo_mod)
    monkeypatch.setattr(repo_mod, "emit_event", _emit, raising=False)

    # 1) get_file error
    class _FindOneBoom:
        def find_one(self, *a, **k):
            raise RuntimeError("boom")
    r = _repo_with_collections(coll=_FindOneBoom())
    assert r.get_file(1, "a.py") is None
    assert any(e[0] == "db_get_file_error" for e in cap["events"]) 

    # 2) get_all_versions error
    class _FindBoom:
        def find(self, *a, **k):
            raise RuntimeError("boom")
    r = _repo_with_collections(coll=_FindBoom())
    assert r.get_all_versions(1, "a.py") == []
    assert any(e[0] == "db_get_all_versions_error" for e in cap["events"]) 

    # 3) get_version error
    class _FindOneBoom2:
        def find_one(self, *a, **k):
            raise RuntimeError("boom")
    r = _repo_with_collections(coll=_FindOneBoom2())
    assert r.get_version(1, "a.py", 2) is None
    assert any(e[0] == "db_get_version_error" for e in cap["events"]) 

    # 4) get_user_files error
    class _AggBoom:
        def aggregate(self, *a, **k):
            raise RuntimeError("boom")
    r = _repo_with_collections(coll=_AggBoom())
    assert r.get_user_files(1) == []
    assert any(e[0] == "db_get_user_files_error" for e in cap["events"]) 

    # 5) search_code error
    r = _repo_with_collections(coll=_AggBoom())
    assert r.search_code(1, "q") == []
    assert any(e[0] == "db_search_code_error" for e in cap["events"]) 

    # 6) get_user_files_by_repo error
    r = _repo_with_collections(coll=_AggBoom())
    items, total = r.get_user_files_by_repo(1, "repo:x/y")
    assert (items, total) == ([], 0)
    assert any(e[0] == "db_get_user_files_by_repo_error" for e in cap["events"]) 

    # 7) get_regular_files_paginated error
    r = _repo_with_collections(coll=_AggBoom())
    items, total = r.get_regular_files_paginated(1)
    assert (items, total) == ([], 0)
    assert any(e[0] == "db_get_regular_files_paginated_error" for e in cap["events"]) 

    # 8) delete_file error
    class _UpdBoom:
        def update_many(self, *a, **k):
            raise RuntimeError("upd")
    r = _repo_with_collections(coll=_UpdBoom())
    assert r.delete_file(1, "a.py") is False
    assert any(e[0] == "db_delete_file_error" for e in cap["events"]) 

    # 9) soft_delete_files_by_names error
    r = _repo_with_collections(coll=_UpdBoom())
    assert r.soft_delete_files_by_names(1, ["a.py"]) == 0
    assert any(e[0] == "db_soft_delete_files_by_names_error" for e in cap["events"]) 

    # 10) delete_file_by_id error
    r = _repo_with_collections(coll=_UpdBoom())
    assert r.delete_file_by_id("507f1f77bcf86cd799439011") is False
    assert any(e[0] == "db_delete_file_by_id_error" for e in cap["events"]) 

    # 11) get_file_by_id error
    class _FindOneBoom3:
        def find_one(self, *a, **k):
            raise RuntimeError("boom")
    r = _repo_with_collections(coll=_FindOneBoom3())
    assert r.get_file_by_id("507f1f77bcf86cd799439011") is None
    assert any(e[0] == "db_get_file_by_id_error" for e in cap["events"]) 

    # 12) get_user_stats error
    r = _repo_with_collections(coll=_AggBoom())
    assert r.get_user_stats(1) == {}
    assert any(e[0] == "db_get_user_stats_error" for e in cap["events"]) 

    # 13) save_large_file error
    class _LargeInsBoom:
        def insert_one(self, *a, **k):
            raise RuntimeError("ins")
    r = _repo_with_collections(lcoll=_LargeInsBoom())
    from database.models import LargeFile
    lf = LargeFile(user_id=1, file_name="a.bin", content="x", programming_language="txt", file_size=1, lines_count=1)
    assert r.save_large_file(lf) is False
    assert any(e[0] == "db_save_large_file_error" for e in cap["events"]) 

    # 14) get_large_file error
    class _LargeFindOneBoom:
        def find_one(self, *a, **k):
            raise RuntimeError("boom")
    r = _repo_with_collections(lcoll=_LargeFindOneBoom())
    assert r.get_large_file(1, "a") is None
    assert any(e[0] == "db_get_large_file_error" for e in cap["events"]) 

    # 15) get_large_file_by_id error
    r = _repo_with_collections(lcoll=_LargeFindOneBoom())
    assert r.get_large_file_by_id("id") is None
    assert any(e[0] == "db_get_large_file_by_id_error" for e in cap["events"]) 

    # 16) get_user_large_files error
    class _LargeCountBoom:
        def count_documents(self, *a, **k):
            raise RuntimeError("cnt")
    r = _repo_with_collections(lcoll=_LargeCountBoom())
    files, total = r.get_user_large_files(1)
    assert files == [] and total == 0
    assert any(e[0] == "db_get_user_large_files_error" for e in cap["events"]) 

    # 17) delete_large_file error
    class _LargeUpdBoom:
        def update_many(self, *a, **k):
            raise RuntimeError("upd")
    r = _repo_with_collections(lcoll=_LargeUpdBoom())
    assert r.delete_large_file(1, "a") is False
    assert any(e[0] == "db_delete_large_file_error" for e in cap["events"]) 

    # 18) delete_large_file_by_id error
    r = _repo_with_collections(lcoll=_LargeUpdBoom())
    assert r.delete_large_file_by_id("id") is False
    assert any(e[0] == "db_delete_large_file_by_id_error" for e in cap["events"]) 

    # 19) list_deleted_files error
    class _ListBoom:
        def find(self, *a, **k):
            raise RuntimeError("find fail")
    r = _repo_with_collections(coll=_ListBoom(), lcoll=_ListBoom())
    files, total = r.list_deleted_files(1)
    assert files == [] and total == 0
    # Verify the structured event is emitted on failure
    assert any(e[0] == "db_list_deleted_files_error" for e in cap["events"]) 

    # 20) restore_file_by_id error
    class _UpdBoom2:
        def update_many(self, *a, **k):
            raise RuntimeError("upd")
    r = _repo_with_collections(coll=_UpdBoom2(), lcoll=_UpdBoom2())
    assert r.restore_file_by_id(1, "id") is False
    assert any(e[0] == "db_restore_file_by_id_error" for e in cap["events"]) 

    # 21) purge_file_by_id error
    class _DelBoom:
        def delete_many(self, *a, **k):
            raise RuntimeError("del")
    r = _repo_with_collections(coll=_DelBoom(), lcoll=_DelBoom())
    assert r.purge_file_by_id(1, "id") is False
    assert any(e[0] == "db_purge_file_by_id_error" for e in cap["events"]) 

    # 22) repo tags/user file names/user tags errors
    r = _repo_with_collections(coll=_AggBoom())
    assert r.get_repo_tags_with_counts(1) == []
    assert any(e[0] == "db_get_repo_tags_with_counts_error" for e in cap["events"]) 
    r = _repo_with_collections(coll=_AggBoom())
    assert r.get_user_file_names_by_repo(1, "repo:x/y") == []
    assert any(e[0] == "db_get_user_file_names_by_repo_error" for e in cap["events"]) 
    r = _repo_with_collections(coll=_AggBoom())
    assert r.get_user_file_names(1) == []
    assert any(e[0] == "db_get_user_file_names_error" for e in cap["events"]) 
    r = _repo_with_collections(coll=_AggBoom())
    assert r.get_user_tags_flat(1) == []
    assert any(e[0] == "db_get_user_tags_flat_error" for e in cap["events"]) 

    # 23) github token ops
    class _Users:
        def update_one(self, *a, **k):
            raise RuntimeError("upd")
        def find_one(self, *a, **k):
            raise RuntimeError("find")
    mgr = types.SimpleNamespace(
        collection=types.SimpleNamespace(),
        large_files_collection=types.SimpleNamespace(),
        backup_ratings_collection=types.SimpleNamespace(),
        db=types.SimpleNamespace(users=_Users())
    )
    r = repo_mod.Repository(mgr)
    assert r.save_github_token(1, "t") is False
    assert any(e[0] == "db_save_github_token_error" for e in cap["events"]) 
    assert r.get_github_token(1) is None
    assert any(e[0] == "db_get_github_token_error" for e in cap["events"]) 
    assert r.delete_github_token(1) is False
    assert any(e[0] == "db_delete_github_token_error" for e in cap["events"]) 

    # 24) drive tokens/prefs
    class _Users2:
        def update_one(self, *a, **k):
            raise RuntimeError("upd")
        def find_one(self, *a, **k):
            raise RuntimeError("find")
    mgr2 = types.SimpleNamespace(
        collection=types.SimpleNamespace(),
        large_files_collection=types.SimpleNamespace(),
        backup_ratings_collection=types.SimpleNamespace(),
        db=types.SimpleNamespace(users=_Users2())
    )
    r = repo_mod.Repository(mgr2)
    assert r.save_drive_tokens(1, {"access_token": "x"}) is False
    assert any(e[0] == "db_save_drive_tokens_error" for e in cap["events"]) 
    assert r.get_drive_tokens(1) is None
    assert any(e[0] == "db_get_drive_tokens_error" for e in cap["events"]) 
    assert r.delete_drive_tokens(1) is False
    assert any(e[0] == "db_delete_drive_tokens_error" for e in cap["events"]) 
    assert r.save_drive_prefs(1, {"a": 1}) is False
    assert any(e[0] == "db_save_drive_prefs_error" for e in cap["events"]) 
    assert r.get_drive_prefs(1) is None
    assert any(e[0] == "db_get_drive_prefs_error" for e in cap["events"]) 

    # 25) backup ratings/notes
    class _BRColl:
        def update_one(self, *a, **k):
            raise RuntimeError("upd")
        def find_one(self, *a, **k):
            raise RuntimeError("find")
        def delete_many(self, *a, **k):
            raise RuntimeError("del")
    mgr3 = types.SimpleNamespace(
        collection=types.SimpleNamespace(),
        large_files_collection=types.SimpleNamespace(),
        backup_ratings_collection=_BRColl(),
        db=types.SimpleNamespace(users=types.SimpleNamespace())
    )
    r = repo_mod.Repository(mgr3)
    assert r.save_backup_rating(1, "b1", "good") is False
    assert any(e[0] == "db_save_backup_rating_error" for e in cap["events"]) 
    assert r.get_backup_rating(1, "b1") is None
    assert any(e[0] == "db_get_backup_rating_error" for e in cap["events"]) 
    assert r.delete_backup_ratings(1, ["b1"]) == 0
    assert any(e[0] == "db_delete_backup_ratings_error" for e in cap["events"]) 
    assert r.save_backup_note(1, "b1", "n") is False
    assert any(e[0] == "db_save_backup_note_error" for e in cap["events"]) 
    assert r.get_backup_note(1, "b1") is None
    assert any(e[0] == "db_get_backup_note_error" for e in cap["events"]) 
