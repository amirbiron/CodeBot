import importlib
import pytest


@pytest.mark.asyncio
async def test_webhook_non_200_is_handled(monkeypatch):
    import integrations as integ
    import http_async as ha
    importlib.reload(integ)

    # register a webhook that will return 500
    integ.webhook_integration.webhooks.clear()
    integ.webhook_integration.register_webhook(1, 'http://x/fail', events=['file_created'])

    class _Resp:
        def __init__(self, status=500):
            self.status = status
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Sess:
        def post(self, url, *a, **k):
            return _Resp(status=500)

    monkeypatch.setattr(ha, 'get_session', lambda: _Sess(), raising=False)

    # Should complete without raising exceptions
    await integ.webhook_integration.trigger_webhook(1, 'file_created', {'a': 1})
