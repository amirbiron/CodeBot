import types
from database.manager import DatabaseManager


class _Coll:
    def __init__(self):
        self.called = False

    def create_indexes(self, indexes):
        self.called = True

    def list_indexes(self):
        return []


class _DB:
    def __init__(self):
        self.users = _Coll()

    def __getitem__(self, name):
        return _Coll()


def test_create_indexes_calls_snippets_indexes():
    # Build a minimal self to run DatabaseManager._create_indexes on
    self = types.SimpleNamespace(
        collection=_Coll(),
        large_files_collection=_Coll(),
        db=_DB(),
        backup_ratings_collection=_Coll(),
        internal_shares_collection=_Coll(),
        community_library_collection=_Coll(),
        snippets_collection=_Coll(),
    )
    DatabaseManager._create_indexes(self)
    assert self.snippets_collection.called is True
