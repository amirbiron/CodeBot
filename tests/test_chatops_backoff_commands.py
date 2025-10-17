import types
import pytest

from bot_handlers import AdvancedBotHandlers


class _Msg:
    def __init__(self):
        self.texts = []
    async def reply_text(self, text, *a, **k):
        self.texts.append(text)


class _Update:
    def __init__(self, uid=1):
        self.message = _Msg()
        self.effective_user = types.SimpleNamespace(id=uid)


class _Context:
    def __init__(self, args=None):
        self.args = args or []


class _App:
    def __init__(self):
        self.handlers = []
    def add_handler(self, *a, **k):
        self.handlers.append((a, k))


@pytest.mark.asyncio
async def test_enable_disable_backoff_admin(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)

    # Admin
    import os
    os.environ["ADMIN_USER_IDS"] = "1"

    # Stub services.github_backoff_state
    class _Info:
        def __init__(self, enabled):
            self.enabled = enabled
            self.reason = "manual"
    class _State:
        def enable(self, **k):
            return _Info(True)
        def disable(self, **k):
            return _Info(False)
    import bot_handlers as bh
    monkeypatch.setattr(bh, "services", types.SimpleNamespace(github_backoff_state=_State()))

    upd = _Update(uid=1)
    ctx = _Context(args=["10"])  # ttl
    await adv.enable_backoff_command(upd, ctx)
    assert any("הופעל Backoff" in t for t in upd.message.texts)

    upd2 = _Update(uid=1)
    ctx2 = _Context()
    await adv.disable_backoff_command(upd2, ctx2)
    assert any("Backoff כובה" in t for t in upd2.message.texts)


@pytest.mark.asyncio
async def test_enable_backoff_non_admin_blocked(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update(uid=999)
    ctx = _Context()
    await adv.enable_backoff_command(upd, ctx)
    assert any("מנהלים בלבד" in t for t in upd.message.texts)
