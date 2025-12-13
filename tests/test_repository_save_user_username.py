import types


def test_repository_save_user_omits_username_when_none_or_empty():
    from database.repository import Repository

    class Users:
        def __init__(self):
            self.calls = []

        def update_one(self, filt, update, upsert=False):
            self.calls.append((filt, update, upsert))
            return types.SimpleNamespace(acknowledged=True)

    class Mgr:
        def __init__(self):
            self.collection = types.SimpleNamespace()
            self.large_files_collection = types.SimpleNamespace()
            self.db = types.SimpleNamespace(users=Users())

    mgr = Mgr()
    repo = Repository(mgr)

    assert repo.save_user(1, None) is True
    _f, upd, _u = mgr.db.users.calls[-1]
    assert "username" not in (upd.get("$setOnInsert") or {})
    assert "username" not in (upd.get("$set") or {})

    assert repo.save_user(2, "") is True
    _f, upd, _u = mgr.db.users.calls[-1]
    assert "username" not in (upd.get("$setOnInsert") or {})
    assert "username" not in (upd.get("$set") or {})

    assert repo.save_user(3, "   ") is True
    _f, upd, _u = mgr.db.users.calls[-1]
    assert "username" not in (upd.get("$setOnInsert") or {})
    assert "username" not in (upd.get("$set") or {})


def test_repository_save_user_sets_username_when_present():
    from database.repository import Repository

    class Users:
        def __init__(self):
            self.calls = []

        def update_one(self, filt, update, upsert=False):
            self.calls.append((filt, update, upsert))
            return types.SimpleNamespace(acknowledged=True)

    class Mgr:
        def __init__(self):
            self.collection = types.SimpleNamespace()
            self.large_files_collection = types.SimpleNamespace()
            self.db = types.SimpleNamespace(users=Users())

    mgr = Mgr()
    repo = Repository(mgr)

    assert repo.save_user(7, "alice") is True
    _f, upd, _u = mgr.db.users.calls[-1]
    assert "username" not in (upd.get("$setOnInsert") or {})
    assert (upd.get("$set") or {}).get("username") == "alice"

