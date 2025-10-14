import types


def test_manager_wrappers_smoke():
    from database.manager import DatabaseManager

    class DummyCollection:
        def aggregate(self, *_a, **_k):
            return []
        def find(self, *_a, **_k):
            return []
        def create_indexes(self, *_a, **_k):
            return None
        def list_indexes(self, *_a, **_k):
            return []
        def drop_index(self, *_a, **_k):
            return None
    class DummyDB:
        def __init__(self):
            self.code_snippets = DummyCollection()
            self.large_files = DummyCollection()
            self.backup_ratings = DummyCollection()
    m = DatabaseManager()
    # monkeypatch into instance
    m.db = DummyDB()
    m.collection = m.db.code_snippets
    m.large_files_collection = m.db.large_files
    m.backup_ratings_collection = m.db.backup_ratings

    # wrappers shouldn't crash
    assert isinstance(m.get_user_files_by_repo(1, "repo:me/x", 1, 10), tuple)
    assert isinstance(m.get_regular_files_paginated(1, 1, 10), tuple)
