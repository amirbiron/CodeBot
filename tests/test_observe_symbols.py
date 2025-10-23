import os
import sys
import types
import pytest

from bot_handlers import AdvancedBotHandlers


class _Msg:
    def __init__(self):
        self.texts = []

    async def reply_text(self, text, *a, **k):  # noqa: D401
        self.texts.append(text)


class _Update:
    def __init__(self):
        self.message = _Msg()
        self.effective_user = types.SimpleNamespace(id=1)


class _Context:
    def __init__(self, args=None):
        self.user_data = {}
        self.args = list(args or [])
        self.application = types.SimpleNamespace(job_queue=types.SimpleNamespace(run_once=lambda *a, **k: None))


@pytest.mark.asyncio
async def test_observe_verbose_recent_errors_header_symbol(monkeypatch):
    app = types.SimpleNamespace(add_handler=lambda *a, **k: None)
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context(args=["-v"])  # default source=all, window=24h

    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    # Ensure recent errors exist so the header is printed
    import observability as obs

    monkeypatch.setattr(
        obs,
        "get_recent_errors",
        lambda limit=5: [
            {"error_code": "E1", "event": "evt1", "ts": "2025-10-23T03:00:00+00:00"}
        ],
        raising=False,
    )

    await adv.observe_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Recent Errors (memory, N≤5):" in out


@pytest.mark.asyncio
async def test_observe_very_verbose_recent_ids_header_symbol(monkeypatch):
    app = types.SimpleNamespace(add_handler=lambda *a, **k: None)
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context(args=["-vv", "source=db"])  # force DB path

    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    # Provide a lightweight alerts_storage stub so DB path is considered ok
    fake_storage = types.SimpleNamespace(
        count_alerts_since=lambda since: (1, 0),
        list_recent_alert_ids=lambda limit=10: ["id-xyz"],
    )
    sys.modules["monitoring.alerts_storage"] = fake_storage

    await adv.observe_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Recent Alert IDs (DB, N≤10):" in out
