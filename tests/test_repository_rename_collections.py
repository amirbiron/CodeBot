from types import SimpleNamespace

from database.repository import Repository


class FakeCollection:
    def __init__(self):
        self.docs = []
    def update_many(self, flt, upd):
        modified = 0
        for d in self.docs:
            if str(d.get('user_id')) == str(flt.get('user_id')) and str(d.get('file_name')) == str(flt.get('file_name')):
                for k, v in upd.get('$set', {}).items():
                    d[k] = v
                modified += 1
        return SimpleNamespace(modified_count=modified)
    def find_one(self, flt, *a, **k):
        # not needed for this isolated test
        return None


class FakeManager:
    def __init__(self):
        self.collection = FakeCollection()
        self.db = SimpleNamespace(collection_items=FakeCollection())


def test_rename_updates_collection_items(monkeypatch):
    mgr = FakeManager()
    repo = Repository(SimpleNamespace(collection=mgr.collection, large_files_collection=None, backup_ratings_collection=None, internal_shares_collection=None, db=mgr.db))
    # seed collection_items
    mgr.db.collection_items.docs.append({'user_id': 7, 'file_name': 'old.py'})
    # perform rename
    ok = repo.rename_file(7, 'old.py', 'new.py')
    # rename in main collection not simulated here, but we expect update in collection_items was attempted without error
    assert ok in (True, False)  # method may return False if nothing updated in main coll
    # assert collection_items updated
    assert mgr.db.collection_items.docs[0]['file_name'] == 'new.py'
