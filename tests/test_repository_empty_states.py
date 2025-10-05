import types


def test_get_regular_files_paginated_empty_returns_zero():
    class Coll:
        def aggregate(self, pipeline, allowDiskUse=False):
            if any("$count" in st for st in pipeline):
                return []  # no results
            return []
    class M:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = Coll()
            self.db = types.SimpleNamespace()
    from database.repository import Repository
    repo = Repository(M())
    items, total = repo.get_regular_files_paginated(1, page=1, per_page=10)
    assert items == [] and total == 0


def test_get_user_files_by_repo_empty_returns_zero():
    class Coll:
        def aggregate(self, pipeline, allowDiskUse=False):
            return []
    class M:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = Coll()
            self.db = types.SimpleNamespace()
    from database.repository import Repository
    repo = Repository(M())
    items, total = repo.get_user_files_by_repo(1, "repo:me/app", page=1, per_page=10)
    assert items == [] and total == 0
