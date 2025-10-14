import types
import pytest

class _Res:
    def __init__(self, data):
        self._data = data
    def __iter__(self):
        return iter(self._data)

class _Coll:
    def __init__(self, rows=None):
        self._rows = rows or []
    def aggregate(self, pipeline, allowDiskUse=True):
        # First call returns [], second call (fallback) returns two grouped rows
        if not hasattr(self, '_calls'):
            self._calls = 0
        self._calls += 1
        if self._calls == 1:
            return []
        return [{'_id': 'a.py'}, {'_id': 'b.js'}]

class _Mgr:
    def __init__(self):
        self.collection = _Coll()
        self.db = types.SimpleNamespace()

@pytest.fixture()
def repo():
    from database.repository import Repository
    return Repository(_Mgr())


def test_get_favorites_count_fallback_aggregate_no_count(repo):
    # Exercise the fallback path when $count not supported
    assert repo.get_favorites_count(1) == 2
