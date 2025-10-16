import os
import types
import importlib


def test_forward_alerts_sends_to_sinks_and_emits(monkeypatch):
    # Prepare env for Slack and Telegram
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "tkn")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "123")

    # Capture outgoing HTTP posts
    calls = {"posts": []}

    def _post(url, json=None, timeout=5):
        calls["posts"].append((url, json))
        class _Resp:
            status_code = 200
        return _Resp()

    import requests as _requests
    monkeypatch.setattr(_requests, "post", _post)

    # Capture emitted events
    events = {"evts": []}
    fake_obs = types.SimpleNamespace(emit_event=lambda evt, severity="info", **kw: events["evts"].append((evt, severity, kw)))

    # Ensure module sees our emit_event
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)
    import alert_forwarder as af  # noqa: F401
    importlib.reload(af)

    alert = {
        "status": "firing",
        "labels": {"alertname": "HighErrorRate", "severity": "error"},
        "annotations": {"summary": "שיעור שגיאות גבוה"},
        "generatorURL": "http://example"
    }

    af.forward_alerts([alert])

    # Two sinks should be called (Slack + Telegram)
    assert len(calls["posts"]) == 2
    # Event should be emitted with error severity
    assert any(e[0] == "alert_received" and e[1] == "error" for e in events["evts"])  # severity reflects labels.severity


def test_forward_alerts_handles_sink_errors(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "tkn")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "123")

    # Make HTTP posting fail
    def _post_fail(url, json=None, timeout=5):  # noqa: ARG001
        raise RuntimeError("boom")

    import requests as _requests
    monkeypatch.setattr(_requests, "post", _post_fail)

    # Capture events
    events = {"evts": []}
    fake_obs = types.SimpleNamespace(emit_event=lambda evt, severity="info", **kw: events["evts"].append((evt, severity, kw)))
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)
    import alert_forwarder as af  # noqa: F401
    importlib.reload(af)

    alert = {
        "status": "firing",
        "labels": {"alertname": "RateLimit", "severity": "warn"},
        "annotations": {"summary": "התראת בדיקה"},
    }

    af.forward_alerts([alert])

    # Error events per sink should be reported
    assert any(e[0] == "alert_forward_slack_error" for e in events["evts"])  # Slack error
    assert any(e[0] == "alert_forward_telegram_error" for e in events["evts"])  # Telegram error
    # The base alert_received should still be logged
    assert any(e[0] == "alert_received" and e[1] == "warn" for e in events["evts"])  # warn severity


def test_format_alert_text_contains_name_and_severity(monkeypatch):
    # Reload module to access helper
    import alert_forwarder as af
    text = af._format_alert_text({  # noqa: SLF001
        "status": "firing",
        "labels": {"alertname": "DiskFull", "severity": "critical"},
        "annotations": {"summary": "Almost full"},
    })
    assert "DiskFull" in text and "CRITICAL" in text
