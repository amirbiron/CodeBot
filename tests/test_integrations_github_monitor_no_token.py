import os
import pytest


@pytest.mark.asyncio
async def test_fetch_rate_limit_no_token(monkeypatch):
    import integrations_github_monitor as gm
    import http_async as ha

    # Ensure no token
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)

    # If called erroneously, fail the test
    def _boom(*a, **k):
        raise AssertionError('request should not be called without token')
    monkeypatch.setattr(ha, 'request', _boom, raising=False)

    data = await gm.fetch_rate_limit()
    assert data == {}
