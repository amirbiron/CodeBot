import types
import pytest
from datetime import datetime, timezone

class _Res:
    def __init__(self, matched=0, modified=0):
        self.matched_count = matched
        self.modified_count = modified

class _Coll:
    # No 'docs' attribute to force non-inmemory path
    def find_one(self, query, sort=None):
        # Return a latest snippet
        return {
            '_id': 'oid-1',
            'user_id': 7,
            'file_name': 'x.py',
            'version': 3,
            'is_active': True,
            'is_favorite': False,
            'favorited_at': None,
        }
    def update_many(self, query, update):
        # Simulate zero matches for both primary and fallback queries
        return _Res(matched=0, modified=0)

class _Mgr:
    def __init__(self):
        self.collection = _Coll()
        self.db = types.SimpleNamespace()

@pytest.fixture()
def repo():
    from database.repository import Repository
    return Repository(_Mgr())


def test_toggle_favorite_returns_none_when_no_matches_and_no_docs(repo):
    # With no matches and no docs list, function should return None
    assert repo.toggle_favorite(7, 'x.py') is None
