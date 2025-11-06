import types
import pytest

import services.snippet_library_service as svc


class _Repo:
    def __init__(self):
        self.created = None
        self.approved = []
        self.rejected = []
        self.pending = [{'_id': '1', 'title': 't1', 'status': 'pending'}]
        self.public = ([{'title': 't', 'description': 'd', 'code': 'c', 'language': 'py'}], 1)

    def create_snippet_proposal(self, **kw):
        self.created = kw
        return 'abc'

    def approve_snippet(self, item_id, admin_id):
        self.approved.append((item_id, admin_id))
        return True

    def reject_snippet(self, item_id, admin_id, reason):
        self.rejected.append((item_id, admin_id, reason))
        return True

    def list_pending_snippets(self, **kw):
        return list(self.pending)

    def list_public_snippets(self, **kw):
        return self.public


class _DB:
    def __init__(self, repo):
        self._repo = repo

    def _get_repo(self):
        return self._repo


def test_submit_snippet_success(monkeypatch):
    repo = _Repo()
    monkeypatch.setattr(svc, '_db', _DB(repo), raising=False)
    out = svc.submit_snippet(title='abc', description='desc', code='x', language='py', user_id=1)
    assert out['ok'] is True and out['id'] == 'abc'
    assert repo.created is not None


def test_submit_snippet_validation_errors():
    bad = svc.submit_snippet(title='ab', description='d', code='', language='', user_id=1)
    assert bad['ok'] is False


def test_approve_and_reject(monkeypatch):
    repo = _Repo()
    monkeypatch.setattr(svc, '_db', _DB(repo), raising=False)
    assert svc.approve_snippet('abc', 9) is True
    assert ('abc', 9) in repo.approved
    assert svc.reject_snippet('zzz', 7, 'nope') is True
    assert ('zzz', 7, 'nope') in repo.rejected


def test_list_helpers(monkeypatch):
    repo = _Repo()
    monkeypatch.setattr(svc, '_db', _DB(repo), raising=False)
    pend = svc.list_pending_snippets(limit=5)
    assert isinstance(pend, list) and pend
    items, total = svc.list_public_snippets(q=None, language=None)
    assert total == 1 and items
