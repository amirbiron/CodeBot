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


@pytest.mark.asyncio
async def test_triage_system_outputs_numbers_from_alert_manager(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context(args=["system"])
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    import alert_manager as am

    am.reset_state_for_tests()
    for _ in range(10):
        am.note_request(200, 0.05)

    await adv.triage_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Triage – System" in out
    assert "Requests: " in out


@pytest.mark.asyncio
async def test_triage_latency_outputs_percentiles(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context(args=["latency"])
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    import alert_manager as am

    am.reset_state_for_tests()
    for _ in range(15):
        am.note_request(200, 0.123)

    await adv.triage_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "Triage – Latency" in out
    assert "p50/p95/p99" in out


@pytest.mark.asyncio
async def test_errors_command_escapes_html_like_topology_description(monkeypatch):
    app = _App()
    adv = AdvancedBotHandlers(app)
    upd = _Update()
    ctx = _Context()
    os.environ["ADMIN_USER_IDS"] = str(upd.effective_user.id)

    # Ensure we hit the local-buffer path (not Sentry issues).
    import integrations_sentry as sc

    monkeypatch.setattr(sc, "is_configured", lambda: False, raising=False)

    def _fake_recent(limit=200):
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        return [
            {
                "ts": now_iso,
                "error_signature": "mongo_topology",
                "error": "<TopologyDescription id=1 topology_type=ReplicaSetNoPrimary>",
                "severity": "error",
                "service": "webapp",
                "endpoint": "/api/demo",
            }
        ]

    # Inject a lightweight stub module to avoid pulling optional deps (structlog, etc.)
    import sys
    import types as _types

    obs_stub = _types.ModuleType("observability")
    obs_stub.get_recent_errors = _fake_recent  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "observability", obs_stub)

    await adv.errors_command(upd, ctx)
    out = "\n".join(upd.message.texts)
    assert "&lt;TopologyDescription" in out
    assert "<TopologyDescription" not in out
