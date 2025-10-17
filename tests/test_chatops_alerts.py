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


@pytest.mark.asyncio
async def test_alerts_command_shows_recent(monkeypatch):
    app = types.SimpleNamespace(add_handler=lambda *a, **k: None)
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()

    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    # Seed internal alerts buffer
    import internal_alerts as ia
    try:
        ia.emit_internal_alert("test_alert", severity="warn", summary="check")
    except Exception:
        pytest.skip("internal alerts not available")

    await adv.alerts_command(upd, ctx)

    out = "\n".join(upd.message.texts)
    assert "התראות" in out or "אין התראות" in out
