import types
import pytest


@pytest.mark.asyncio
async def test_sentry_poller_seeds_silently_then_emits_on_new_last_seen(monkeypatch):
    from services.sentry_polling import SentryPoller, SentryPollerConfig

    # Fake integrations_sentry module
    issues_round1 = [
        {"id": "1", "shortId": "ABC-1", "title": "Boom", "permalink": "https://sentry/1", "lastSeen": "2025-12-12T10:00:00Z", "firstSeen": "2025-12-12T09:00:00Z"},
    ]
    issues_round2 = [
        {"id": "1", "shortId": "ABC-1", "title": "Boom", "permalink": "https://sentry/1", "lastSeen": "2025-12-12T10:05:00Z", "firstSeen": "2025-12-12T09:00:00Z"},
    ]
    state = {"round": 1}

    async def get_recent_issues(limit=10):
        return issues_round1 if state["round"] == 1 else issues_round2

    fake_sentry = types.SimpleNamespace(is_configured=lambda: True, get_recent_issues=get_recent_issues)
    monkeypatch.setitem(__import__("sys").modules, "integrations_sentry", fake_sentry)

    # Capture internal alerts
    emitted = []

    def emit_internal_alert(name: str, severity: str = "info", summary: str = "", **details):
        emitted.append({"name": name, "severity": severity, "summary": summary, "details": details})

    monkeypatch.setitem(__import__("sys").modules, "internal_alerts", types.SimpleNamespace(emit_internal_alert=emit_internal_alert))

    poller = SentryPoller(
        SentryPollerConfig(
            enabled=True,
            limit=10,
            severity="error",
            seed_silent=True,
            dedup_seconds=0,
        )
    )

    # First tick: seed only
    res1 = await poller.tick()
    assert res1.get("ok") is True
    assert emitted == []

    # Second tick: should emit once
    state["round"] = 2
    res2 = await poller.tick()
    assert res2.get("emitted") == 1
    assert emitted and emitted[0]["details"].get("alert_type") == "sentry_issue"

