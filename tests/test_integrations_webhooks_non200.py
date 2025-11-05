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
        lambda *a, **k: _Ctx(_Resp(status=500)),
        raising=False,
    )

    # Should complete without raising exceptions
    await integ.webhook_integration.trigger_webhook(1, 'file_created', {'a': 1})
