import os
import types
import asyncio
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
        self.user_data = {}
        self.application = types.SimpleNamespace(job_queue=types.SimpleNamespace(run_once=lambda *a, **k: None))
        self.args = args or []


class _App:
    def __init__(self):
        self.handlers = []
    def add_handler(self, *args, **kwargs):
        self.handlers.append((args, kwargs))


@pytest.mark.asyncio
async def test_errors_command_windows_and_examples(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)
    # Sentry UI env for links
    os.environ["SENTRY_DSN"] = "https://o123.ingest.sentry.io/1"
    os.environ["SENTRY_ORG_SLUG"] = "acme"

    # Stub recent errors with ISO timestamps
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    recent = [
        {"ts": (now - timedelta(minutes=1)).isoformat(), "error_signature": "sigA", "error": "boom A"},
        {"ts": (now - timedelta(minutes=2)).isoformat(), "error_signature": "sigA", "error": "boom A2"},
        {"ts": (now - timedelta(minutes=4)).isoformat(), "error_signature": "sigB", "error": "boom B"},
        {"ts": (now - timedelta(minutes=200)).isoformat(), "error_signature": "oldSig", "error": "old"},
    ]

    import observability as obs
    monkeypatch.setattr(obs, "get_recent_errors", lambda limit=200: list(recent), raising=False)

    ctx = _Context()
    await adv.errors_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Top 5m" in out and "sigA" in out and "דוגמאות: /errors examples sigA" in out
    assert "Sentry:" in out  # link attached per signature when env is set

    # Now test examples subcommand
    upd2 = _Update()
    os.environ["ADMIN_USER_IDS"] = str(upd2.effective_user.id)
    ctx2 = _Context(args=["examples", "sigA"])
    await adv.errors_command(upd2, ctx2)
    out2 = "\n".join(upd2.message.texts)
    assert "דוגמאות לשגיאות" in out2 and "sigA" in out2 and "•" in out2


@pytest.mark.asyncio
async def test_status_command_extended(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    # Ensure DB check passes
    import importlib
    mod = importlib.import_module("bot_handlers")
    monkeypatch.setattr(mod, "check_db_connection", lambda: asyncio.sleep(0, result=True), raising=False)

    # Env flags for Sentry and OTEL
    os.environ["SENTRY_DSN"] = "https://o123.ingest.sentry.io/1"
    os.environ["SENTRY_AUTH_TOKEN"] = "t"
    os.environ["SENTRY_ORG"] = "acme"
    os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] = "http://localhost:4317"

    await adv.status_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Sentry DSN:" in out and "Sentry API:" in out and "OTEL Exporter:" in out
