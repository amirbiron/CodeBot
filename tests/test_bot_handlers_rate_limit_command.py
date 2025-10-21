import types
import importlib
import pytest


class _App:
    def add_handler(self, *args, **kwargs):
        pass


@pytest.mark.asyncio
async def test_rate_limit_command_handles_no_token(monkeypatch):
    import bot_handlers as bh
    importlib.reload(bh)

    # Ensure no token and mark user as admin
    monkeypatch.delenv('GITHUB_TOKEN', raising=False)

    # Stub is_admin to True
    monkeypatch.setattr(bh.AdvancedBotHandlers, '_is_admin', lambda self, uid: True)

    class _Msg:
        def __init__(self):
            self.texts = []
        async def reply_text(self, t):
            self.texts.append(t)

    update = types.SimpleNamespace(message=_Msg(), effective_user=types.SimpleNamespace(id=1))
    context = types.SimpleNamespace()

    h = bh.AdvancedBotHandlers(application=_App())
    await h.rate_limit_command(update, context)

    assert any('אין GITHUB_TOKEN' in t for t in update.message.texts)


@pytest.mark.asyncio
async def test_rate_limit_command_happy_path(monkeypatch):
    import bot_handlers as bh
    importlib.reload(bh)

    # Provide token and stub aiohttp; mark user as admin
    monkeypatch.setenv('GITHUB_TOKEN', 't')
    monkeypatch.setattr(bh.AdvancedBotHandlers, '_is_admin', lambda self, uid: True)

    class _Resp:
        def __init__(self, data):
            self.status = 200
            self._data = data
        async def json(self):
            return self._data
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
            # 80% used -> should warn in message
            return _Resp({
                "resources": {"core": {"limit": 1000, "remaining": 200}}
            })

    monkeypatch.setattr(bh, 'aiohttp', type('A', (), {
        'ClientSession': _Sess,
        'ClientTimeout': lambda *a, **k: None,
        'TCPConnector': lambda *a, **k: None,
    }))

    class _Msg:
        def __init__(self):
            self.texts = []
        async def reply_text(self, t):
            self.texts.append(t)

    update = types.SimpleNamespace(message=_Msg(), effective_user=types.SimpleNamespace(id=1))
    context = types.SimpleNamespace()

    h = bh.AdvancedBotHandlers(application=_App())
    await h.rate_limit_command(update, context)

    out = '\n'.join(update.message.texts)
    assert 'GitHub' in out and ('80%' in out or 'שימוש' in out)
