from database.repository import Repository


class _MgrNone:
    def __init__(self):
        self.snippets_collection = None


def test_repo_handles_missing_collection():
    repo = Repository(_MgrNone())
    sid = repo.create_snippet_proposal(title='t', description='d', code='x', language='py', user_id=1)
    assert sid is None
    assert repo.approve_snippet('', admin_id=1) is True  # no-op path
    assert repo.reject_snippet('', admin_id=1, reason='r') is True
    assert repo.list_pending_snippets() == []
    items, total = repo.list_public_snippets()
    assert items == [] and total == 0
