import os
import importlib
import pytest


@pytest.mark.asyncio
async def test_sentry_get_recent_issues_returns_empty_on_bad_status(monkeypatch):
    import integrations_sentry as sn
    import http_async as ha
    importlib.reload(sn)

    # Configure env to enable is_configured()
    monkeypatch.setenv('SENTRY_AUTH_TOKEN', 't')
    monkeypatch.setenv('SENTRY_ORG', 'org')

    # Stub aiohttp session and response
    class _Resp:
        def __init__(self, status):
            self.status = status
        async def json(self):
            return {}
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
            return _Resp(status=500)

    monkeypatch.setattr(ha, 'get_session', lambda: _Sess(), raising=False)

    out = await sn.get_recent_issues(limit=3)
    assert out == []
