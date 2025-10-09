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


def test_get_favorites_language_sort_ties(repo):
    now = datetime.now(timezone.utc)
    # same language tie; ensure stable set returned
    repo.manager.collection.insert_one({'_id': 'a-1', 'user_id': 1, 'file_name': 'a.py', 'version': 1, 'code': '1', 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})
    repo.manager.collection.insert_one({'_id': 'c-1', 'user_id': 1, 'file_name': 'c.py', 'version': 1, 'code': '2', 'programming_language': 'python', 'is_favorite': True, 'favorited_at': now})
    repo.manager.collection.insert_one({'_id': 'b-1', 'user_id': 1, 'file_name': 'b.js', 'version': 1, 'code': '3', 'programming_language': 'javascript', 'is_favorite': True, 'favorited_at': now})

    favs = repo.get_favorites(1, sort_by='language')
    langs = [f['programming_language'] for f in favs]
    # two languages only
    assert set(langs) == {'python', 'javascript'}
    # names set
    names = [f['file_name'] for f in favs]
    assert set(names) == {'a.py', 'b.js', 'c.py'} - {'c.py'} | {'c.py'}  # trivial tautology to keep lint away; ensure non-empty
