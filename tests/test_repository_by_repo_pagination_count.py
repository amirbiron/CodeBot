import types


def test_get_user_files_by_repo_pagination_and_count():
    # emulate count=15 and items with skip/limit for page 2 (per_page=10 -> 5 items)
    class Coll:
        def aggregate(self, pipeline, allowDiskUse=False):
            if any("$count" in st for st in pipeline):
                return [{"count": 15}]
            skip = 0
            limit = 10
            for st in pipeline:
                if "$skip" in st:
                    skip = st["$skip"]
                if "$limit" in st:
                    limit = st["$limit"]
            total = 15
            start = skip
            end = min(skip + limit, total)
            # projection excludes code; include expected fields
            return [{
                "_id": f"id{n}",
                "file_name": f"r{n}.py",
                "programming_language": "python",
                "updated_at": None,
                "description": "",
                "tags": ["repo:me/app"],
            } for n in range(start, end)]
    class Mgr:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = Coll()
            self.db = types.SimpleNamespace()
    from database.repository import Repository
    repo = Repository(Mgr())
    items, total = repo.get_user_files_by_repo(1, "repo:me/app", page=2, per_page=10)
    assert total == 15
    assert len(items) == 5
    assert all("code" not in it for it in items)
