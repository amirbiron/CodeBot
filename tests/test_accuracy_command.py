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
    def __init__(self, uid=1):
        self.message = _Msg()
        self.effective_user = types.SimpleNamespace(id=uid)


class _Context:
    def __init__(self):
        self.user_data = {}
        self.application = types.SimpleNamespace(job_queue=types.SimpleNamespace(run_once=lambda *a, **k: None))


@pytest.mark.asyncio
async def test_accuracy_command_shows_values(monkeypatch):
    app = types.SimpleNamespace(add_handler=lambda *a, **k: None)
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()

    # Allow admin
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    # Seed metrics: simulate accuracy gauge and prevented counter where available
    import importlib
    m = importlib.import_module('metrics')

    if m.Counter is None or m.Gauge is None:
        # Environment without prometheus_client: command should still respond
        await adv.accuracy_command(upd, ctx)
        out = "\n".join(upd.message.texts)
        assert "Prediction Accuracy" in out
        return

    # When prometheus_client is available, set values on gauge/counters
    if m.prediction_accuracy_percent is not None:
        m.prediction_accuracy_percent.set(87.5)
    if m.prevented_incidents_total is not None:
        m.prevented_incidents_total.labels(metric="latency_seconds").inc()
        m.prevented_incidents_total.labels(metric="error_rate_percent").inc(2)

    await adv.accuracy_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Prediction Accuracy" in out
    assert "%" in out
    assert "Prevented Incidents" in out
