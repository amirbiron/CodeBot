import types
import os
import pytest


class _App:
    def add_handler(self, *a, **k):
        pass


@pytest.mark.asyncio
async def test_status_command_includes_github_rate_limit(monkeypatch):
    import bot_handlers as bh

    # Admin + token
    os.environ["ADMIN_USER_IDS"] = "1"
    os.environ["GITHUB_TOKEN"] = "t"

    # Stub DB check to avoid external calls
    async def _ok():
        return True
    monkeypatch.setattr(bh, "check_db_connection", _ok, raising=False)

    # Stub Redis
    import cache_manager as cm
    monkeypatch.setattr(cm.cache, "is_enabled", True, raising=False)

    # Stub http_async session get -> JSON
    class _Resp:
        async def json(self):
            return {"resources": {"core": {"limit": 100, "remaining": 75}}}
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Sess:
        def __init__(self, *a, **k):
            pass
        def get(self, *a, **k):
            return _Resp()

    import http_async as ha
    monkeypatch.setattr(ha, "get_session", lambda: _Sess(), raising=False)

    # Stubs for Update/Context
    class _Msg:
        def __init__(self):
            self.texts = []
        async def reply_text(self, t):
            self.texts.append(t)

    update = types.SimpleNamespace(message=_Msg(), effective_user=types.SimpleNamespace(id=1))
    context = types.SimpleNamespace()

    adv = bh.AdvancedBotHandlers(_App())
    await adv.status_command(update, context)

    out = "\n".join(update.message.texts)
    assert "GitHub:" in out and "75/100" in out and "25%" in out
