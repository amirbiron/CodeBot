import importlib
import pytest


@pytest.mark.asyncio
async def test_pastebin_create_success(monkeypatch):
    import integrations as integ
    import http_async as ha
    importlib.reload(integ)

    integ.pastebin_integration.api_key = 'k'

    class _Resp:
        def __init__(self, status=200, text='https://pastebin.com/abc'):
            self.status = status
            self._text = text
        async def text(self):
            return self._text
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Sess:
        def __init__(self, *a, **k):
            pass
        def post(self, *a, **k):
            return _Resp(status=200, text='https://pastebin.com/abc')

    monkeypatch.setattr(ha, 'get_session', lambda: _Sess(), raising=False)

    out = await integ.pastebin_integration.create_paste('code', 'f.py', 'python')
    assert isinstance(out, dict) and out.get('id') == 'abc' and out.get('url', '').endswith('/abc')
