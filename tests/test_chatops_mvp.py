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

    # Make the test user an admin so the command is allowed
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    # Ensure Redis disabled in test unless actually configured
    import cache_manager as cm
    monkeypatch.setattr(cm.cache, "is_enabled", False, raising=False)

    # Force DB check to a deterministic result (False) to avoid real connections
    import bot_handlers as bh
    async def _db_false():
        return False
    monkeypatch.setattr(bh, "check_db_connection", _db_false, raising=False)

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

    # Make the test user an admin so the command is allowed
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

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

    # Make the test user an admin so the command is allowed
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    await adv.rate_limit_command(upd, ctx)

    out = "\n".join(upd.message.texts)
    assert "אין GITHUB_TOKEN" in out or "לא זמין" in out


@pytest.mark.asyncio
async def test_non_admin_denied_commands(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()

    # Ensure user is NOT admin
    if "ADMIN_USER_IDS" in os.environ:
        del os.environ["ADMIN_USER_IDS"]

    for cmd in (adv.status_command, adv.errors_command, adv.rate_limit_command):
        upd.message.texts.clear()
        await cmd(upd, ctx)
        out = "\n".join(upd.message.texts)
        assert "פקודה זמינה למנהלים בלבד" in out


@pytest.mark.asyncio
async def test_status_command_emojis_and_components(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()

    # Admin
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    # Mock DB check to succeed (new behavior uses check_db_connection)
    import bot_handlers as bh
    async def _ok():
        return True
    monkeypatch.setattr(bh, "check_db_connection", _ok)

    # Mock Redis enabled
    import cache_manager as cm
    monkeypatch.setattr(cm.cache, "is_enabled", True, raising=False)

    await adv.status_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "DB: 🟢" in out
    assert "Redis: 🟢" in out


@pytest.mark.asyncio
async def test_rate_limit_command_with_warning(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()

    # Admin + token
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)
    os.environ["GITHUB_TOKEN"] = "x"

    # Fake aiohttp client returning 85% usage
    class _Resp:
        async def json(self):
            return {"resources": {"core": {"limit": 100, "remaining": 15}}}
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Session:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, exc_type, exc, tb):
            return False
        def get(self, *a, **k):
            return _Resp()

    import http_async as ha
    monkeypatch.setattr(ha, "get_session", lambda: _Session(), raising=False)

    await adv.rate_limit_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Usage:" in out and "⚠️" in out
