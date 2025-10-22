import importlib


def test_repository_invalidation_on_save_and_toggle(monkeypatch):
    import database.repository as repo_mod
    importlib.reload(repo_mod)

    # Fake manager and collection
    class _Coll:
        def __init__(self):
            self.docs = []
        def insert_one(self, doc):
            self.docs.append(dict(doc))
            return type('R', (), {'inserted_id': '1'})
        def find_one(self, q, sort=None):  # noqa: ARG002
            # Return last matching doc
            cand = [d for d in self.docs if d.get('user_id') == q.get('user_id') and d.get('file_name') == q.get('file_name')]
            return cand[-1] if cand else None
        def update_many(self, q, u):  # noqa: ARG002
            return type('R', (), {'matched_count': 1, 'modified_count': 1})
    class _Mgr:
        collection = _Coll()
    mgr = _Mgr()

    # Spy cache to record invalidations
    calls = {"user": 0, "file": 0}
    class _SpyCache:
        def invalidate_user_cache(self, user_id):  # noqa: ARG001
            calls["user"] += 1
            return 1
        def invalidate_file_related(self, file_id, user_id=None):  # noqa: ARG002
            calls["file"] += 1
            return 1
    spy = _SpyCache()

    # Patch cache into module
    monkeypatch.setattr(repo_mod, 'cache', spy, raising=True)

    r = repo_mod.Repository(mgr)

    # Save snippet
    from database.models import CodeSnippet
    s = CodeSnippet(user_id=5, file_name='a.py', code='print(1)', programming_language='python')
    assert r.save_code_snippet(s) is True

    # Toggle favorite
    assert r.toggle_favorite(5, 'a.py') in (True, False)

    # Verify invalidations occurred
    assert calls["user"] >= 1
    assert calls["file"] >= 1
