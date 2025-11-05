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
        lambda *a, **k: _Ctx(_Resp(status=500)),
        raising=False,
    )

    out = await sn.get_recent_issues(limit=3)
    assert out == []
