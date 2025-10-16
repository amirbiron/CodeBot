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
async def test_uptime_reports_value(monkeypatch):
    app = types.SimpleNamespace(add_handler=lambda *a, **k: None)
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()

    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    # Seed metrics counters to a known state
    import metrics as m
    # If counters are missing (prometheus_client not installed), skip
    if m.codebot_requests_total is None or m.codebot_failed_requests_total is None:
        pytest.skip("prometheus_client not available")

    # Set values: total=100, failed=2 => uptime=98%
    m.codebot_requests_total._value.set(100)  # type: ignore[attr-defined]
    m.codebot_failed_requests_total._value.set(2)  # type: ignore[attr-defined]

    await adv.uptime_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Uptime" in out and "%" in out

