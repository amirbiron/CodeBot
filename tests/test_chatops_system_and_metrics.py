import os
import types
import pytest

from bot_handlers import AdvancedBotHandlers


class _Msg:
    def __init__(self):
        self.texts = []
        self.docs = []  # (document, caption)

    async def reply_text(self, text, *a, **k):
        self.texts.append(text)

    async def reply_document(self, document, *a, **k):
        caption = k.get("caption")
        self.docs.append((document, caption))


class _Update:
    def __init__(self):
        self.message = _Msg()
        self.effective_user = types.SimpleNamespace(id=1)


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
async def test_system_info_admin_success(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    # Stable loadavg and psutil memory path
    monkeypatch.setattr(os, "getloadavg", lambda: (0.1, 0.2, 0.3), raising=False)

    # Stub psutil to ensure RSS branch runs
    ps = types.SimpleNamespace(
        Process=lambda pid: types.SimpleNamespace(
            memory_info=lambda: types.SimpleNamespace(rss=2048)
        )
    )
    monkeypatch.setitem(__import__("sys").modules, "psutil", ps)

    await adv.system_info_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "System Info" in out and "Sentry" in out


@pytest.mark.asyncio
async def test_system_info_non_admin_denied(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()
    os.environ["ADMIN_USER_IDS"] = ""  # no admins

    await adv.system_info_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "למנהלים בלבד" in out


@pytest.mark.asyncio
async def test_metrics_with_payload_attaches_document(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    import metrics as m

    monkeypatch.setattr(m, "metrics_endpoint_bytes", lambda: b"metric_x 1\n", raising=False)
    monkeypatch.setattr(m, "get_uptime_percentage", lambda: 98.76, raising=False)

    await adv.metrics_command(upd, ctx)
    # Should send a document with caption containing the uptime
    assert len(upd.message.docs) == 1
    _, caption = upd.message.docs[0]
    assert "98.76%" in (caption or "")


@pytest.mark.asyncio
async def test_metrics_without_payload_falls_back_to_text(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    import metrics as m

    monkeypatch.setattr(m, "metrics_endpoint_bytes", lambda: b"", raising=False)
    monkeypatch.setattr(m, "get_uptime_percentage", lambda: 99.99, raising=False)

    await adv.metrics_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "metrics unavailable" in out
