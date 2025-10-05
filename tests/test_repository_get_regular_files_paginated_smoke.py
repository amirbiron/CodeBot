import types

def test_get_regular_files_paginated_count_then_page():
    # emulate two pages with total=13 and per_page=10
    class Coll:
        def __init__(self):
            self.calls = []
        def aggregate(self, pipeline, allowDiskUse=False):
            # detect count pipeline by presence of $count
            if any("$count" in st for st in pipeline):
                return [{"count": 13}]
            # items pipeline: return 10 docs for page 1 (skip=0) or 3 docs for page 2 (skip=10)
            skip = 0
            limit = 10
            for st in pipeline:
                if "$skip" in st:
                    skip = st["$skip"]
                if "$limit" in st:
                    limit = st["$limit"]
            start = skip
            end = skip + limit
            total = 13
            docs = [{"_id": f"i{n}", "file_name": f"f{n}.py", "programming_language": "python"} for n in range(start, min(end, total))]
            return docs
    class Mgr:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = Coll()
            self.db = types.SimpleNamespace()
    from database.repository import Repository
    repo = Repository(Mgr())
    # request invalid high page; repo should clamp internally and return last page
    items, total = repo.get_regular_files_paginated(1, page=9, per_page=10)
    assert total == 13
    assert len(items) == 3
