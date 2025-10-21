import importlib
import pytest


@pytest.mark.asyncio
async def test_fetch_rate_limit_handles_exception(monkeypatch):
    import integrations_github_monitor as gm
    importlib.reload(gm)

    # Provide token and stub aiohttp that raises
    monkeypatch.setenv('GITHUB_TOKEN', 'x')

    class _Sess:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        def get(self, *a, **k):
            class _Resp:
                async def __aenter__(self):
                    raise RuntimeError('boom')
                async def __aexit__(self, exc_type, exc, tb):
                    return False
            return _Resp()

    monkeypatch.setattr(gm, 'aiohttp', type('Y', (), {
        'ClientSession': _Sess,
        'ClientTimeout': lambda *a, **k: None,
        'TCPConnector': lambda *a, **k: None,
    }))

    out = await gm.fetch_rate_limit()
    assert out == {}
