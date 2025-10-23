import importlib
import types


def _sample_alert():
    return {
        "status": "firing",
        "labels": {"alertname": "DiskFull", "severity": "critical"},
        "annotations": {"summary": "Almost full"},
        "generatorURL": "http://example/alert",
    }


def test_prefers_pooled_over_requests(monkeypatch):
    # Ensure sinks are configured
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "tkn")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "123")

    # Import fresh module
    import alert_forwarder as af
    importlib.reload(af)

    calls = {"requests": 0, "pooled": 0}

    def _req_post(url, json=None, timeout=5):  # noqa: ARG001
        calls["requests"] += 1
        return types.SimpleNamespace(status_code=200)

    def _pooled(method, url, json=None, timeout=5):  # noqa: ARG001
        calls["pooled"] += 1
        return types.SimpleNamespace(status_code=200)

    # Both clients available: should prefer pooled
    monkeypatch.setattr(af._requests, "post", _req_post)
    monkeypatch.setattr(af, "_pooled_request", _pooled)

    af.forward_alerts([_sample_alert()])

    # Both sinks (Slack + Telegram) should go via pooled, not requests
    assert calls["pooled"] == 2
    assert calls["requests"] == 0


def test_fallback_to_pooled_when_requests_missing(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "tkn")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "123")

    import alert_forwarder as af
    importlib.reload(af)

    calls = {"pooled": 0}

    def _pooled(method, url, json=None, timeout=5):  # noqa: ARG001
        calls["pooled"] += 1
        return types.SimpleNamespace(status_code=200)

    # Simulate missing requests client
    monkeypatch.setattr(af, "_requests", None, raising=False)
    monkeypatch.setattr(af, "_pooled_request", _pooled)

    af.forward_alerts([_sample_alert()])

    # Both sinks should use pooled client
    assert calls["pooled"] == 2


def test_emits_errors_when_no_http_client_available(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "tkn")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "123")

    # Capture emitted events
    events = {"evts": []}
    fake_obs = types.SimpleNamespace(
        emit_event=lambda evt, severity="info", **kw: events["evts"].append((evt, severity, kw))
    )
    # Ensure module sees our emit_event
    monkeypatch.setitem(importlib.sys.modules, "observability", fake_obs)

    import alert_forwarder as af
    importlib.reload(af)

    # Simulate no HTTP clients available
    monkeypatch.setattr(af, "_requests", None, raising=False)
    monkeypatch.setattr(af, "_pooled_request", None, raising=False)

    af.forward_alerts([_sample_alert()])

    # Both sinks should report errors
    assert any(e[0] == "alert_forward_slack_error" for e in events["evts"])  # Slack error
    assert any(e[0] == "alert_forward_telegram_error" for e in events["evts"])  # Telegram error
