import importlib
import types


def test_integrations_client_session_uses_timeout_and_connector(monkeypatch):
    import http_async as ha
    import integrations as integ
    importlib.reload(integ)

    # Ensure fresh shared session and patch aiohttp classes to capture kwargs
    captured = {}

    class _DummyResp:
        def __init__(self, status=200, body='ok'):
            self.status = status
            self._body = body
        async def text(self):
            return self._body
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _DummySession:
        def __init__(self, *a, **k):
            captured['kwargs'] = k
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        async def post(self, *a, **k):
            return _DummyResp(status=200, body='https://pastebin.com/abc')
        async def get(self, *a, **k):
            return _DummyResp(status=200, body='ok')

    class _FakeConnector:
        def __init__(self, *a, **k):
            self.limit = k.get('limit')

    class _FakeTimeout:
        def __init__(self, *a, **k):
            self.total = k.get('total')

    # Reset and patch http_async to use our stubs
    monkeypatch.setattr(ha, '_session', None, raising=False)
    monkeypatch.setattr(ha, 'aiohttp', types.SimpleNamespace(
        ClientSession=_DummySession,
        TCPConnector=_FakeConnector,
        ClientTimeout=_FakeTimeout,
    ), raising=False)

    import asyncio
    async def _run():
        svc = integ.PastebinIntegration()
        svc.api_key = 'k'
        await svc.create_paste('code', 'fn.py', 'python')
        await svc.get_paste_content('xyz')
        await integ.webhook_integration.trigger_webhook(1, 'file_created', {'x': 1})

    asyncio.run(_run())

    assert 'timeout' in captured['kwargs'] and 'connector' in captured['kwargs']
