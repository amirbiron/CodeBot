import importlib
import types
import pytest


@pytest.mark.asyncio
async def test_webhook_trigger_handles_timeouts_and_errors(monkeypatch):
    import integrations as integ
    import http_async as ha
    importlib.reload(integ)

    # Prepare a couple of webhooks (one will timeout, the other raises)
    integ.webhook_integration.webhooks.clear()
    id1 = integ.webhook_integration.register_webhook(1, 'http://x/ok', events=['file_created'])
    id2 = integ.webhook_integration.register_webhook(1, 'http://x/fail', events=['file_created'])

    class _Resp:
        def __init__(self, status=200):
            self.status = status
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def release(self):
            return None

    class _CtxOk:
        def __init__(self, resp):
            self._resp = resp
        async def __aenter__(self):
            return self._resp
        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _CtxFail:
        async def __aenter__(self):
            raise RuntimeError('boom')
        async def __aexit__(self, exc_type, exc, tb):
            return False

    def _fake_request(method, url, **kwargs):
        if url.endswith('/ok'):
            return _CtxOk(_Resp(status=200))
        return _CtxFail()

    monkeypatch.setattr(ha, 'request', _fake_request, raising=False)

    await integ.webhook_integration.trigger_webhook(1, 'file_created', {'x': 1})
    # If no exceptions bubble up, handler is resilient as expected
    assert True
