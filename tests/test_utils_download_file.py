import importlib
import pytest


@pytest.mark.asyncio
async def test_download_file_rejects_large_content(monkeypatch):
    import utils as ut
    import http_async as ha
    importlib.reload(ut)

    class _Resp:
        def __init__(self, status=200, body=b'a' * (1024 * 1024)):
            self.status = status
            self.headers = {'content-length': str(len(body))}
            self._body = body
            self.content = self

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def text(self):
            return self._body.decode('utf-8')

        async def iter_chunked(self, n):
            yield self._body

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
        lambda *a, **k: _Ctx(_Resp(body=b'a' * (2 * 1024 * 1024))),
        raising=False,
    )

    out = await ut.FileUtils.download_file('http://x', max_size=1*1024*1024)
    assert out is None


@pytest.mark.asyncio
async def test_download_file_handles_http_error(monkeypatch):
    import utils as ut
    import http_async as ha
    importlib.reload(ut)

    class _Resp:
        def __init__(self):
            self.status = 404
            self.headers = {}

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
        lambda *a, **k: _Ctx(_Resp()),
        raising=False,
    )

    out = await ut.FileUtils.download_file('http://x')
    assert out is None
