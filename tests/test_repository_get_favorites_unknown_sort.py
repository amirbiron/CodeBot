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

class FakeManager:
    def __init__(self):
        self.collection = InMemoryCollection()
        self.db = types.SimpleNamespace()

@pytest.fixture()
def repo():
    from database.repository import Repository
    return Repository(FakeManager())


def test_get_favorites_unknown_sort_defaults_to_date(repo):
    now = datetime.now(timezone.utc)
    repo.manager.collection.insert_one({'_id': 'a-1', 'user_id': 10, 'file_name': 'a.py', 'version': 1, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})
    repo.manager.collection.insert_one({'_id': 'b-1', 'user_id': 10, 'file_name': 'b.js', 'version': 1, 'programming_language': 'javascript', 'is_favorite': True, 'favorited_at': now})

    favs = repo.get_favorites(10, sort_by='unknown')
    names = [f['file_name'] for f in favs]
    assert set(names) == {'a.py', 'b.js'}
