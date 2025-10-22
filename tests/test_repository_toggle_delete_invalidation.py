import importlib


def test_toggle_and_delete_invalidate_properly(monkeypatch):
    import database.repository as repo_mod
    importlib.reload(repo_mod)

    # Fake collection
    class _Coll:
        def __init__(self):
            self.docs = [{"_id": 1, "user_id": 3, "file_name": "x.py", "version": 1, "is_active": True}]
        def find_one(self, q, sort=None, **kw):  # noqa: ARG002
            for d in self.docs:
                if d.get('user_id') == q.get('user_id') and d.get('file_name') == q.get('file_name'):
                    return d
            return None
        def update_many(self, q, u):  # noqa: ARG002
            return type('R', (), {'matched_count': 1, 'modified_count': 1})
    class _Mgr:
        collection = _Coll()
    mgr = _Mgr()

    calls = {"user": 0, "file": 0}
    class _SpyCache:
        def invalidate_user_cache(self, user_id):  # noqa: ARG001
            calls["user"] += 1
            return 1
        def invalidate_file_related(self, file_id, user_id=None):  # noqa: ARG002
            calls["file"] += 1
            return 1
    spy = _SpyCache()
    monkeypatch.setattr(repo_mod, 'cache', spy, raising=True)

    r = repo_mod.Repository(mgr)

    # Toggle favorite -> should invalidate user and file
    out = r.toggle_favorite(3, 'x.py')
    assert out in (True, False)
    assert calls["user"] >= 1
    assert calls["file"] >= 1

    # delete_file -> should invalidate user and file
    assert r.delete_file(3, 'x.py') in (True, False)
    assert calls["user"] >= 2
    assert calls["file"] >= 2
