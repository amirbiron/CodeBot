import importlib
import types


def test_integrations_client_session_uses_timeout_and_connector(monkeypatch):
    # Reload modules
    import integrations as integ
    importlib.reload(integ)

    # Monkeypatch aiohttp.ClientSession to capture args
    captured = {}

    class _DummySession:
        def __init__(self, *a, **k):
            captured['kwargs'] = k
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        # Minimal API used by code
        async def post(self, *a, **k):
            class _Resp:
                status = 200
                async def text(self):
                    return 'https://pastebin.com/abc'
            return _Resp()
        async def get(self, *a, **k):
            class _Resp:
                status = 200
                async def text(self):
                    return 'ok'
            return _Resp()

    # Provide a fake TCPConnector and ClientTimeout types for isinstance checks if any
    class _FakeConnector:
        def __init__(self, *a, **k):
            self.limit = k.get('limit')

    class _FakeTimeout:
        def __init__(self, *a, **k):
            self.total = k.get('total')

    monkeypatch.setattr(integ, 'aiohttp', types.SimpleNamespace(
        ClientSession=_DummySession,
        TCPConnector=_FakeConnector,
        ClientTimeout=_FakeTimeout,
    ))

    # Call functions that open sessions
    import asyncio
    async def _run():
        svc = integ.PastebinIntegration()
        svc.api_key = 'k'
        await svc.create_paste('code', 'fn.py', 'python')
        await svc.get_paste_content('xyz')
        await integ.webhook_integration.trigger_webhook(1, 'file_created', {'x': 1})

    asyncio.run(_run())

    # Verify that timeout and connector were passed to ClientSession
    assert 'timeout' in captured['kwargs'] and 'connector' in captured['kwargs']
