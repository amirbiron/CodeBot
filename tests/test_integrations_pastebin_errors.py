import importlib
import types
import pytest


@pytest.mark.asyncio
async def test_pastebin_create_and_get_handle_errors(monkeypatch):
    import integrations as integ
    import http_async as ha
    importlib.reload(integ)

    # Ensure pastebin is available
    integ.pastebin_integration.api_key = 'k'

    class _Resp:
        def __init__(self, status=500, text='err'):
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

    def _fake_request(method, url, **kwargs):
        if str(method).upper() == 'POST':
            resp = _Resp(status=500, text='error')
        else:
            resp = _Resp(status=404, text='not found')
        return _Ctx(resp)

    monkeypatch.setattr(ha, 'request', _fake_request, raising=False)

    out = await integ.pastebin_integration.create_paste('code', 'f.py', 'python')
    assert out is None

    content = await integ.pastebin_integration.get_paste_content('abc')
    assert content is None
