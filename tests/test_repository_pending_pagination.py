from database.repository import Repository


class _PendingColl:
    def __init__(self):
        self._rows = [
            {'_id': '1', 'status': 'pending', 'title': 'A'},
            {'_id': '2', 'status': 'pending', 'title': 'B'},
            {'_id': '3', 'status': 'pending', 'title': 'C'},
        ]
    def find(self, match=None, sort=None):
        return list(self._rows)


class _Mgr:
    def __init__(self):
        self.snippets_collection = _PendingColl()


def test_list_pending_snippets_skip_and_limit():
    repo = Repository(_Mgr())
    rows = repo.list_pending_snippets(limit=2, skip=1)
    assert [r['_id'] for r in rows] == ['2', '3'][:2]
