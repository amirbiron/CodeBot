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


def test_get_favorites_language_with_limit(repo):
    now = datetime.now(timezone.utc)
    repo.manager.collection.insert_one({'_id': 'a-1', 'user_id': 1, 'file_name': 'a.py', 'version': 1, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})
    repo.manager.collection.insert_one({'_id': 'b-1', 'user_id': 1, 'file_name': 'b.py', 'version': 1, 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})
    repo.manager.collection.insert_one({'_id': 'c-1', 'user_id': 1, 'file_name': 'c.js', 'version': 1, 'programming_language': 'javascript', 'is_favorite': True, 'favorited_at': now})

    favs = repo.get_favorites(1, language='python', limit=1)
    # expect exactly one python favorite due to limit
    assert isinstance(favs, list) and len(favs) == 1
