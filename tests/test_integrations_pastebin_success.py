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
        async def release(self):
            return None

    class _Ctx:
        def __init__(self, resp):
            self._resp = resp
        async def __aenter__(self):
            return self._resp
        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        ha,
        'request',
        lambda *a, **k: _Ctx(_Resp(status=200, text='https://pastebin.com/abc')),
        raising=False,
    )

    out = await integ.pastebin_integration.create_paste('code', 'f.py', 'python')
    assert isinstance(out, dict) and out.get('id') == 'abc' and out.get('url', '').endswith('/abc')
