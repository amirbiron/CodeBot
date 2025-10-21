import importlib
import pytest


@pytest.mark.asyncio
async def test_download_file_rejects_large_content(monkeypatch):
    import utils as ut
    importlib.reload(ut)

    class _Resp:
        def __init__(self, status=200, body=b'a'* (1024*1024)):
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

    class _Sess:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        def get(self, *a, **k):
            # Return 2MB body while max_size will be set to 1MB
            return _Resp(body=b'a'*(2*1024*1024))

    monkeypatch.setattr(ut, 'aiohttp', type('B', (), {
        'ClientSession': _Sess,
        'ClientTimeout': lambda *a, **k: None,
        'TCPConnector': lambda *a, **k: None,
    }))

    out = await ut.FileUtils.download_file('http://x', max_size=1*1024*1024)
    assert out is None


@pytest.mark.asyncio
async def test_download_file_handles_http_error(monkeypatch):
    import utils as ut
    importlib.reload(ut)

    class _Resp:
        def __init__(self):
            self.status = 404
            self.headers = {}
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Sess:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        def get(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(ut, 'aiohttp', type('C', (), {
        'ClientSession': _Sess,
        'ClientTimeout': lambda *a, **k: None,
        'TCPConnector': lambda *a, **k: None,
    }))

    out = await ut.FileUtils.download_file('http://x')
    assert out is None
