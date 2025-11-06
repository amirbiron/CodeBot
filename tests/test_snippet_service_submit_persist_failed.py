import services.snippet_library_service as svc


def test_submit_snippet_persist_failed(monkeypatch):
    class _Repo:
        def create_snippet_proposal(self, **kw):
            return None
    class _DB:
        def __init__(self):
            self._repo = _Repo()
        def _get_repo(self):
            return self._repo
    monkeypatch.setattr(svc, '_db', _DB(), raising=False)
    out = svc.submit_snippet(title='Title', description='desc', code='x', language='py', user_id=1)
    assert out['ok'] is False and out['error'] == 'persist_failed'
