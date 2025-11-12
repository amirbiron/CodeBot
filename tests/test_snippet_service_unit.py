import types
from typing import Dict, Optional
import pytest

import services.snippet_library_service as svc


class _Repo:
    include_builtin_snippets = False

    def __init__(self):
        self.created = None
        self.approved = []
        self.rejected = []
        self.pending = [{'_id': '1', 'title': 't1', 'status': 'pending'}]
        self.public = ([{'title': 't', 'description': 'd', 'code': 'c', 'language': 'py'}], 1)
        self._duplicate: Optional[Dict[str, str]] = None

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

    def find_snippet_duplicate(self, **_kw):
        return self._duplicate


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


def test_submit_snippet_duplicate_title(monkeypatch):
    repo = _Repo()
    repo._duplicate = {"matched": "title", "title": "קיים", "status": "approved"}
    monkeypatch.setattr(svc, '_db', _DB(repo), raising=False)
    out = svc.submit_snippet(title='קיים', description='desc', code='print(1)', language='python', user_id=10)
    assert out['ok'] is False
    assert "כבר קיים סניפט" in out['error']


def test_submit_snippet_duplicate_code(monkeypatch):
    repo = _Repo()
    repo._duplicate = {"matched": "code", "title": "Example", "status": "pending"}
    monkeypatch.setattr(svc, '_db', _DB(repo), raising=False)
    out = svc.submit_snippet(title='חדש', description='desc', code='print(1)', language='python', user_id=10)
    assert out['ok'] is False
    assert "כבר נמצא בספריית הסניפטים" in out['error']


def test_submit_snippet_builtin_duplicate(monkeypatch):
    repo = _Repo()
    repo._duplicate = None
    monkeypatch.setattr(svc, '_db', _DB(repo), raising=False)
    builtin = svc.BUILTIN_SNIPPETS[0]
    out = svc.submit_snippet(
        title=builtin['title'],
        description='desc',
        code=builtin['code'],
        language=builtin['language'],
        user_id=77,
    )
    assert out['ok'] is False
    assert "קיימת בספריית הסניפטים" in out['error'] or "קיים כבר סניפט עם קוד זהה" in out['error']
