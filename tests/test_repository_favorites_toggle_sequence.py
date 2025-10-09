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


def test_toggle_favorite_sequence(repo):
    now = datetime.now(timezone.utc)
    repo.manager.collection.insert_one({'_id': 'x-1', 'user_id': 1, 'file_name': 'x.py', 'version': 1, 'code': '1', 'programming_language': 'python', 'is_favorite': False, 'favorited_at': None, 'is_active': True})

    # on -> True
    s1 = repo.toggle_favorite(1, 'x.py')
    latest = repo.get_favorites(1)
    assert s1 in (True, None) and any(f['file_name'] == 'x.py' for f in latest)

    # off -> False
    s2 = repo.toggle_favorite(1, 'x.py')
    latest2 = repo.get_favorites(1)
    assert s2 in (False, None) and all(f['file_name'] != 'x.py' for f in latest2)

    # on again -> True
    s3 = repo.toggle_favorite(1, 'x.py')
    latest3 = repo.get_favorites(1)
    assert s3 in (True, None) and any(f['file_name'] == 'x.py' for f in latest3)
