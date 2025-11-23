import types
import pytest

from bot_handlers import AdvancedBotHandlers


class DummyMsg:
    def __init__(self, text=""):
        self.text = text
        self.replies = []

    async def reply_text(self, text, **kwargs):
        self.replies.append(text)


class DummyUpdate:
    def __init__(self, text=""):
        self.message = DummyMsg(text=text)


class DummyCtx:
    def __init__(self, args=None):
        self.args = args or []
        self.user_data = {}


class DummyApp:
    def __init__(self):
        self.handlers = []

    def add_handler(self, h):
        self.handlers.append(h)


@pytest.mark.asyncio
async def test_lang_basic(monkeypatch):
    # Stub detect_language and internal extractor
    monkeypatch.setattr('services.code_service.detect_language', lambda code, fn: 'python', raising=False)
    app = DummyApp()
    h = AdvancedBotHandlers(app)
    h._extract_code_from_message_or_reply = lambda update: "print(1)"  # type: ignore
    upd = DummyUpdate(text="/lang Block.md\n```python\nprint(1)\n```")
    ctx = DummyCtx(args=["Block.md"])
    await h.lang_command(upd, ctx)
    assert any("שפה: python" in r for r in upd.message.replies)


@pytest.mark.asyncio
async def test_lang_debug(monkeypatch):
    monkeypatch.setattr('services.code_service.detect_language', lambda code, fn: 'bash', raising=False)
    app = DummyApp()
    h = AdvancedBotHandlers(app)
    h._extract_code_from_message_or_reply = lambda update: "#!/usr/bin/env bash\necho hi"  # type: ignore
    upd = DummyUpdate(text="/lang_debug run")
    ctx = DummyCtx(args=["run"])
    await h.lang_debug_command(upd, ctx)
    # Expect a multi-line debug with language and reason
    assert any("language: bash" in r for r in upd.message.replies)
