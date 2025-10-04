import types


def _repo_with_aggregate_returning(items):
    from database.repository import Repository
    class Coll:
        def aggregate(self, *_a, **_k):
            return items
    class Mgr:
        def __init__(self):
            self.collection = Coll()
            self.large_files_collection = Coll()
            self.db = types.SimpleNamespace()
    return Repository(Mgr())


def test_repo_tags_normalizes_when_tag_field_present():
    repo = _repo_with_aggregate_returning([{"tag": "repo:me/x", "count": 3}, {"tag": "repo:me/y", "count": 2}])
    rows = repo.get_repo_tags_with_counts(1)
    assert {r.get('tag') for r in rows} == {"repo:me/x", "repo:me/y"}


def test_repo_tags_normalizes_when_id_dict_present():
    repo = _repo_with_aggregate_returning([{"_id": {"tag": "repo:me/x"}, "count": 1}])
    rows = repo.get_repo_tags_with_counts(1)
    assert rows and rows[0]['tag'] == "repo:me/x"


def test_repo_tags_normalizes_when_item_is_string():
    repo = _repo_with_aggregate_returning(["repo:me/x", "repo:me/y"])
    rows = repo.get_repo_tags_with_counts(1)
    assert {r.get('tag') for r in rows} == {"repo:me/x", "repo:me/y"}
