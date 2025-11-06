import services.snippet_library_service as svc


def test_submit_snippet_minimal_valid(monkeypatch):
    class _Repo:
        def __init__(self):
            self.created = None
        def create_snippet_proposal(self, **kw):
            self.created = kw
            return 'id'
    class _DB:
        def __init__(self, r):
            self._repo = r
        def _get_repo(self):
            return self._repo
    r = _Repo()
    monkeypatch.setattr(svc, '_db', _DB(r), raising=False)
    out = svc.submit_snippet(title='Title', description='desc!!', code='x', language='py', user_id=2)
    assert out['ok'] is True and r.created['user_id'] == 2
