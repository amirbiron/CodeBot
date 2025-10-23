import types
import importlib


def test_alert_manager_respects_silence(monkeypatch):
    # Stub silences to return True
    fake_sil = types.SimpleNamespace(is_silenced=lambda name, severity=None: (True, {"_id": "abc", "until_ts": "2099-01-01"}))
    monkeypatch.setitem(importlib.sys.modules, 'monitoring.silences', fake_sil)

    # Capture dispatches
    sent = {"telegram": 0, "grafana": 0}
    import alert_manager as am
    def _noop_send_tg(text):  # noqa: ARG001
        sent["telegram"] += 1
    def _noop_graf(name, summary):  # noqa: ARG001
        sent["grafana"] += 1
    monkeypatch.setattr(am, "_send_telegram", _noop_send_tg)
    monkeypatch.setattr(am, "_send_grafana_annotation", _noop_graf)

    # Capture record_alert calls
    calls = []
    fake_store = types.SimpleNamespace(record_alert=lambda **kw: calls.append(kw))
    monkeypatch.setitem(importlib.sys.modules, 'monitoring.alerts_storage', fake_store)

    am._notify_critical_external("High Latency", "test", {})

    # Nothing sent to sinks but recorded with silenced=True
    assert sent["telegram"] == 0 and sent["grafana"] == 0
    assert calls and calls[-1].get("silenced") is True


def test_alert_forwarder_respects_silence(monkeypatch):
    # Configure sinks
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.test/abc")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "tkn")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "123")

    # Stub silences to silence this name
    fake_sil = types.SimpleNamespace(is_silenced=lambda name, severity=None: (name == "DiskFull", {"_id": "z", "until_ts": "2099"}))
    monkeypatch.setitem(importlib.sys.modules, 'monitoring.silences', fake_sil)

    # Capture HTTP posts
    posts = []
    import requests as _requests
    def _post(url, json=None, timeout=5):  # noqa: ARG001
        posts.append((url, json))
        return types.SimpleNamespace(status_code=200)
    monkeypatch.setattr(_requests, 'post', _post)

    # Load module and forward alerts (one silenced, one not)
    import alert_forwarder as af
    import importlib as _il
    _il.reload(af)

    alerts = [
        {"status": "firing", "labels": {"alertname": "DiskFull", "severity": "critical"}},
        {"status": "firing", "labels": {"alertname": "CPUHigh", "severity": "warn"}},
    ]
    af.forward_alerts(alerts)

    # Only the non-silenced one should create sink posts; Slack+Telegram => 2 posts
    assert len(posts) == 2
