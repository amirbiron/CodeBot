import types
import pytest
from datetime import datetime, timezone

class InMemoryResult:
    def __init__(self, inserted_id=None, matched=0, modified=0):
        self.inserted_id = inserted_id
        self.matched_count = matched
        self.modified_count = modified

class InMemoryCollection:
    def __init__(self):
        self.docs = []
    def insert_one(self, doc):
        d = dict(doc)
        d.setdefault('_id', f"id_{len(self.docs)+1}")
        d.setdefault('is_active', True)
        self.docs.append(d)
        return InMemoryResult(inserted_id=d['_id'])

class FakeManager:
    def __init__(self):
        self.collection = InMemoryCollection()
        self.db = types.SimpleNamespace()

@pytest.fixture()
def repo():
    from database.repository import Repository
    return Repository(FakeManager())


def test_get_favorites_count_empty(repo):
    assert repo.get_favorites_count(42) == 0


def test_get_favorites_count_mixed_ignores_inactive_and_duplicates(repo):
    now = datetime.now(timezone.utc)
    # a.py שתי גרסאות מועדפות פעילות
    repo.manager.collection.insert_one({'_id': 'a-1', 'user_id': 1, 'file_name': 'a.py', 'version': 1, 'is_favorite': True, 'favorited_at': now, 'is_active': True})
    repo.manager.collection.insert_one({'_id': 'a-2', 'user_id': 1, 'file_name': 'a.py', 'version': 2, 'is_favorite': True, 'favorited_at': now, 'is_active': True})
    # b.js מועדף אך לא פעיל
    repo.manager.collection.insert_one({'_id': 'b-1', 'user_id': 1, 'file_name': 'b.js', 'version': 1, 'is_favorite': True, 'favorited_at': now, 'is_active': False})
    # c.py לא מועדף
    repo.manager.collection.insert_one({'_id': 'c-1', 'user_id': 1, 'file_name': 'c.py', 'version': 1, 'is_favorite': False, 'is_active': True})
    # צפוי: רק a.py נספר (distinct לפי שם)
    assert repo.get_favorites_count(1) == 1
