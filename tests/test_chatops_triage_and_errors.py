import os
import types
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
async def test_errors_command_prefers_sentry(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    import integrations_sentry as sc

    monkeypatch.setattr(sc, "is_configured", lambda: True, raising=False)

    async def _issues(limit=10):
        return [{"shortId": "S-9", "title": "boom"}]

    monkeypatch.setattr(sc, "get_recent_issues", _issues, raising=False)

    await adv.errors_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "S-9" in out and "boom" in out


@pytest.mark.asyncio
async def test_triage_command_builds_report_and_link(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context(args=["req-xyz"])
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    # Stub investigation service result
    import services.investigation_service as inv

    async def _triage(query, limit=20):
        return {
            "query": query,
            "timeline": [
                {"timestamp": "2025-01-01T00:00:00Z", "message": "m1", "url": "https://s/e1"}
            ],
            "summary_text": "one item",
            "summary_html": "<html>report</html>",
            "grafana_links": [
                {"name": "Logs (24h)", "url": "https://grafana.example.com/explore"},
                {"name": "Latency (5m)", "url": "https://grafana.example.com/d/lat"},
            ],
        }

    monkeypatch.setattr(inv, "triage", _triage, raising=False)

    await adv.triage_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Triage" in out and "Grafana" in out and "דוח מלא:" in out
