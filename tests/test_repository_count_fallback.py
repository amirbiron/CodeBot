from database.repository import Repository


class _Coll:
    def count_documents(self, match):
        raise RuntimeError("count fail")

    def find(self, match=None, sort=None):
        return []


class _Mgr:
    def __init__(self):
        self.snippets_collection = _Coll()


def test_repo_list_public_snippets_count_fallback():
    items, total = Repository(_Mgr()).list_public_snippets(q='x', language=None, page=1, per_page=10)
    assert items == [] and total == 0
