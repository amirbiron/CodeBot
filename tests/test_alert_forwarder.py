import os
import time
import types
import importlib
from urllib.parse import urlparse


def test_forward_alerts_sends_to_sinks_and_emits(monkeypatch):
    # Prepare env for Slack and Telegram
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "tkn")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("PUBLIC_URL", "https://public.example")

    # Capture outgoing HTTP posts via pooled client
    calls = {"posts": []}

    # Capture emitted events
    events = {"evts": []}
    fake_obs = types.SimpleNamespace(emit_event=lambda evt, severity="info", **kw: events["evts"].append((evt, severity, kw)))

    # Ensure module sees our emit_event
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)
    import alert_forwarder as af
    importlib.reload(af)

    # Stub pooled HTTP client so we don't perform real network calls
    def _pooled(method, url, json=None, timeout=5):  # noqa: ARG001
        calls["posts"].append((url, json))
        return types.SimpleNamespace(status_code=200, json=lambda: {"ok": True})

    monkeypatch.setattr(af, "_pooled_request", _pooled)

    alert = {
        "status": "firing",
        "labels": {"alertname": "HighErrorRate", "severity": "error"},
        "annotations": {"summary": "שיעור שגיאות גבוה"},
        "generatorURL": "http://example"
    }

    af.forward_alerts([alert])

    # Two sinks should be called (Slack + Telegram)
    assert len(calls["posts"]) == 2
    # Event should be emitted as anomaly severity
    assert any(e[0] == "alert_received" and e[1] == "anomaly" for e in events["evts"])  # anomaly severity

    tg_calls = [c for c in calls["posts"] if urlparse(c[0]).hostname == "api.telegram.org"]
    assert len(tg_calls) == 1
    tg_payload = tg_calls[0][1] or {}
    # We do not include generatorURL in the text; instead we attach a public dashboard button.
    assert "http://example" not in str(tg_payload.get("text") or "")
    kb = tg_payload.get("reply_markup") or {}
    rows = kb.get("inline_keyboard") or []
    assert rows and rows[0] and rows[0][0]["text"] == "Open Dashboard"
    assert rows[0][0]["url"] == "https://public.example/admin/observability"


def test_forward_alerts_handles_sink_errors(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "tkn")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "123")

    # Make HTTP posting fail via pooled client
    def _pooled_fail(method, url, json=None, timeout=5):  # noqa: ARG001
        raise RuntimeError("boom")

    # Capture events
    events = {"evts": []}
    fake_obs = types.SimpleNamespace(emit_event=lambda evt, severity="info", **kw: events["evts"].append((evt, severity, kw)))
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)
    import alert_forwarder as af
    importlib.reload(af)

    # Route pooled requests to failing stub
    monkeypatch.setattr(af, "_pooled_request", _pooled_fail)

    alert = {
        "status": "firing",
        "labels": {"alertname": "RateLimit", "severity": "warn"},
        "annotations": {"summary": "התראת בדיקה"},
    }

    af.forward_alerts([alert])

    # Error events per sink should be reported
    assert any(e[0] == "alert_forward_slack_error" for e in events["evts"])  # Slack error
    assert any(e[0] == "alert_forward_telegram_error" for e in events["evts"])  # Telegram error
    # The base alert_received should still be logged as anomaly
    assert any(e[0] == "alert_received" and e[1] == "anomaly" for e in events["evts"])  # anomaly severity


def test_format_alert_text_contains_name_and_severity(monkeypatch):
    # Reload module to access helper
    import alert_forwarder as af
    text = af._format_alert_text({  # noqa: SLF001
        "status": "firing",
        "labels": {"alertname": "DiskFull", "severity": "critical"},
        "annotations": {"summary": "Almost full"},
    })
    assert "DiskFull" in text and "CRITICAL" in text


def test_anomaly_alerts_are_batched_before_telegram(monkeypatch):
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setenv("ALERT_TELEGRAM_MIN_SEVERITY", "info")
    monkeypatch.setenv("ALERT_ANOMALY_BATCH_WINDOW_SECONDS", "0.05")

    import alert_forwarder as af
    importlib.reload(af)

    sent = []

    def _fake_slack(text):
        sent.append(("slack", text))

    def _fake_tg(text):
        sent.append(("telegram", text))

    monkeypatch.setattr(af, "_post_to_slack", _fake_slack)
    monkeypatch.setattr(af, "_post_to_telegram", _fake_tg)

    alert = {
        "status": "firing",
        "labels": {"alertname": "AnomalySpike", "severity": "anomaly", "service": "api", "env": "prod"},
        "annotations": {"summary": "latency spike"},
    }

    af.forward_alerts([alert, alert])

    # Slack receives both alerts immediately
    slack_calls = [c for c in sent if c[0] == "slack"]
    assert len(slack_calls) == 2

    # Telegram message should be delayed and aggregated
    assert not [c for c in sent if c[0] == "telegram"]
    time.sleep(0.1)
    telegram_calls = [c for c in sent if c[0] == "telegram"]
    assert len(telegram_calls) == 1
    assert "2 מופעים" in telegram_calls[0][1]

    af._reset_anomaly_batches_for_tests()


def test_anomaly_detected_formats_as_system_anomaly(monkeypatch):
    import alert_forwarder as af
    import importlib
    importlib.reload(af)

    alert = {
        "status": "firing",
        "labels": {"alertname": "anomaly_detected", "severity": "anomaly"},
        "annotations": {
            "summary": "avg_rt=3.081s (threshold 3.000s)",
            "top_slow_endpoint": "POST bookmarks.toggle_bookmark (2.794s)",
            "active_requests": "1",
            "recent_errors_5m": "0",
            "avg_memory_usage_mb": "205.14",
            "slow_endpoints_compact": (
                "POST bookmarks.toggle_bookmark: 2.79s (n=1); "
                "GET api_observability_aggregations: 1.59s (n=1); "
                "GET settings: 0.53s (n=1); "
                "GET api_observability_alerts: 0.53s (n=1)"
            ),
        },
    }

    text = af._format_alert_text(alert)  # noqa: SLF001
    assert "🐢 System Anomaly Detected" in text
    assert "Avg Response:" in text and "Threshold:" in text
    assert "🐌 Main Bottleneck:" in text
    assert "POST bookmarks.toggle_bookmark" in text
    assert "📉 Also Slow in this Window:" in text
    assert "📊 Resource Usage:" in text


def test_startup_grace_period_suppresses_noisy_alerts(monkeypatch):
    # Configure sinks so forwarding would normally happen
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "tkn")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("ALERT_STARTUP_GRACE_PERIOD_SECONDS", "300")

    import importlib
    import types

    import alert_forwarder as af
    importlib.reload(af)

    calls = {"posts": []}

    def _pooled(method, url, json=None, timeout=5):  # noqa: ARG001
        calls["posts"].append((url, json))
        return types.SimpleNamespace(status_code=200, json=lambda: {"ok": True})

    monkeypatch.setattr(af, "_pooled_request", _pooled)

    alert = {
        "status": "firing",
        "labels": {"alertname": "AppLatencyEWMARegression", "severity": "warning"},
        "annotations": {"summary": "startup noise"},
    }

    # During startup: should be suppressed (no Slack/Telegram posts)
    monkeypatch.setattr(af, "_MODULE_START_MONOTONIC", af.monotonic())
    af.forward_alerts([alert])
    assert calls["posts"] == []

    # After grace: should be forwarded to both sinks
    monkeypatch.setattr(af, "_MODULE_START_MONOTONIC", af.monotonic() - 301.0)
    af.forward_alerts([alert])
    assert len(calls["posts"]) == 2
