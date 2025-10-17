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
async def test_observe_outputs_basic(monkeypatch):
    app = types.SimpleNamespace(add_handler=lambda *a, **k: None)
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()

    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    # Seed uptime computation counters, if available
    import metrics as m
    if m.codebot_requests_total is not None and m.codebot_failed_requests_total is not None:
        m.codebot_requests_total._value.set(100)  # type: ignore[attr-defined]
        m.codebot_failed_requests_total._value.set(0)  # type: ignore[attr-defined]

    # Seed alert manager with a few requests so error rate calc is stable
    try:
        import alert_manager as am
        am.reset_state_for_tests()
        for i in range(60):
            am.note_request(200, 0.1)
    except Exception:
        pass

    await adv.observe_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Observability Overview" in out
    assert "Uptime:" in out
    assert "Error Rate:" in out
    assert "Alerts (24h):" in out
