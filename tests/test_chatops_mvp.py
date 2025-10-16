import asyncio
import types
import os
import pytest

from bot_handlers import AdvancedBotHandlers


class _Msg:
    def __init__(self):
        self.texts = []
    async def reply_text(self, text, *a, **k):
        self.texts.append(text)


class _Update:
    def __init__(self):
        self.message = _Msg()
        self.effective_user = types.SimpleNamespace(id=1)


class _Context:
    def __init__(self):
        self.user_data = {}
        self.application = types.SimpleNamespace(job_queue=types.SimpleNamespace(run_once=lambda *a, **k: None))


class _App:
    def __init__(self):
        self.handlers = []
    def add_handler(self, *args, **kwargs):
        self.handlers.append((args, kwargs))


@pytest.mark.asyncio
async def test_status_command_outputs_basic_health(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()

    # Ensure Redis disabled in test unless actually configured
    import cache_manager as cm
    monkeypatch.setattr(cm.cache, "is_enabled", False, raising=False)

    await adv.status_command(upd, ctx)

    out = "\n".join(upd.message.texts)
    assert "Status" in out
    assert "DB:" in out and "Redis:" in out


@pytest.mark.asyncio
async def test_errors_command_uses_recent_errors_buffer(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()

    # Seed recent errors buffer
    import observability as obs
    try:
        buf = obs._RECENT_ERRORS  # type: ignore[attr-defined]
        buf.clear()
        buf.append({"error_code": "E_TEST", "error": "boom", "event": "x"})
    except Exception:
        pytest.skip("recent errors buffer not available")

    await adv.errors_command(upd, ctx)

    out = "\n".join(upd.message.texts)
    assert "שגיאות אחרונות" in out
    assert "E_TEST" in out


@pytest.mark.asyncio
async def test_rate_limit_command_without_token_reports_unavailable(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    await adv.rate_limit_command(upd, ctx)

    out = "\n".join(upd.message.texts)
    assert "אין GITHUB_TOKEN" in out or "לא זמין" in out
