import types
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

class InMemoryResult:
    def __init__(self, inserted_id: Any = None):
        self.inserted_id = inserted_id

class InMemoryCollection:
    def __init__(self):
        self.docs: List[Dict[str, Any]] = []
    def insert_one(self, doc: Dict[str, Any]):
        d = dict(doc)
        d.setdefault('_id', f"{d.get('file_name','doc')}-{d.get('version',1)}")
        d.setdefault('is_active', True)
        self.docs.append(d)
        return InMemoryResult(inserted_id=d['_id'])
    def aggregate(self, pipeline, allowDiskUse=False):
        # simulate unsupported/empty aggregate path
        return []

class FakeManager:
    def __init__(self):
        self.collection = InMemoryCollection()
        self.db = types.SimpleNamespace()

@pytest.fixture()
def repo():
    from database.repository import Repository
    return Repository(FakeManager())


def test_get_favorites_fallback_docs_is_used(repo):
    now = datetime.now(timezone.utc)
    # Add favorites directly to docs, aggregate returns [] so fallback must be used
    repo.manager.collection.insert_one({'_id': 'fa-1', 'user_id': 42, 'file_name': 'fav1.py', 'version': 1, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})
    repo.manager.collection.insert_one({'_id': 'fa-2', 'user_id': 42, 'file_name': 'fav2.js', 'version': 1, 'programming_language': 'javascript', 'is_favorite': True, 'favorited_at': now})
    repo.manager.collection.insert_one({'_id': 'fa-3', 'user_id': 42, 'file_name': 'old.py', 'version': 1, 'programming_language': 'python', 'is_favorite': False})

    favs = repo.get_favorites(42, sort_by='name')
    assert all('_id' in f and f['_id'] for f in favs)
    names = [f['file_name'] for f in favs]
    assert set(names) == {'fav1.py', 'fav2.js'}

    cnt = repo.get_favorites_count(42)
    assert cnt == 2
