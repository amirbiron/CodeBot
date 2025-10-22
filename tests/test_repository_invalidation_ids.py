import importlib


def test_invalidate_uses_unique_id_when_available(monkeypatch):
    import database.repository as repo_mod
    import database.models as models
    importlib.reload(repo_mod)

    # Fake collection that records inserts
    class _Coll:
        def __init__(self):
            self.inserted = []
            self.docs = []
        def insert_one(self, doc):
            self.inserted.append(doc)
            self.docs.append(dict(doc))
            return type('R', (), {'inserted_id': 'xyz'})
        def find_one(self, q, sort=None):  # noqa: ARG002
            return None
    class _Mgr:
        collection = _Coll()
    mgr = _Mgr()

    # Spy cache to assert ID vs file_name
    seen = {"file_ids": []}
    class _SpyCache:
        def invalidate_user_cache(self, user_id):  # noqa: ARG001
            return 1
        def invalidate_file_related(self, file_id, user_id=None):  # noqa: ARG002
            seen["file_ids"].append(str(file_id))
            return 1
    spy = _SpyCache()
    monkeypatch.setattr(repo_mod, 'cache', spy, raising=True)

    r = repo_mod.Repository(mgr)
    s = models.CodeSnippet(user_id=9, file_name='readme.md', code='# T', programming_language='markdown')

    # Simulate presence of unique id on object before save
    setattr(s, 'id', 'ABC123')
    assert r.save_code_snippet(s) is True

    # Expect invalidate_file_related called with the unique id, not file_name
    assert 'ABC123' in seen["file_ids"]
