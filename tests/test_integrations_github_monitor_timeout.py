import importlib
import pytest


@pytest.mark.asyncio
async def test_fetch_rate_limit_handles_exception(monkeypatch):
    import integrations_github_monitor as gm
    import http_async as ha
    importlib.reload(gm)

    # Provide token and stub aiohttp that raises
    monkeypatch.setenv('GITHUB_TOKEN', 'x')

    class _Ctx:
        async def __aenter__(self):
            raise RuntimeError('boom')
        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(ha, 'request', lambda *a, **k: _Ctx(), raising=False)

    out = await gm.fetch_rate_limit()
    assert out == {}
