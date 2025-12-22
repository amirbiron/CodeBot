import socket
from unittest.mock import MagicMock


def test_execute_matched_actions_noop_when_no_match():
    from services import rules_evaluator as reval

    reval.execute_matched_actions(None)  # type: ignore[arg-type]
    reval.execute_matched_actions({"matched": False})


def test_execute_matched_actions_suppress_sets_flags():
    from services import rules_evaluator as reval

    alert_data = {"name": "A"}
    evaluation = {
        "matched": True,
        "alert_data": alert_data,
        "rules": [{"rule_id": "r1", "actions": [{"type": "suppress"}]}],
    }

    reval.execute_matched_actions(evaluation)

    assert alert_data["silenced"] is True
    assert alert_data["silenced_by_rule"] == "r1"


def test_execute_matched_actions_calls_helpers(monkeypatch):
    from services import rules_evaluator as reval

    calls = {"notify": 0, "github": 0, "webhook": 0}

    monkeypatch.setattr(reval, "_send_custom_notification", lambda *a, **k: calls.__setitem__("notify", calls["notify"] + 1))
    monkeypatch.setattr(reval, "_create_github_issue", lambda *a, **k: calls.__setitem__("github", calls["github"] + 1))
    monkeypatch.setattr(reval, "_call_webhook", lambda *a, **k: calls.__setitem__("webhook", calls["webhook"] + 1))

    evaluation = {
        "matched": True,
        "alert_data": {"summary": "x", "severity": "info"},
        "rules": [
            {
                "rule_id": "r1",
                "actions": [
                    {"type": "send_alert", "channel": "default", "message_template": "{{summary}}"},
                    {"type": "create_github_issue"},
                    {"type": "webhook", "webhook_url": "https://example.com/hook"},
                ],
            }
        ],
    }

    reval.execute_matched_actions(evaluation)
    assert calls == {"notify": 1, "github": 1, "webhook": 1}


def test_is_safe_webhook_url_blocks_non_http():
    from services.rules_evaluator import _is_safe_webhook_url

    assert _is_safe_webhook_url("ftp://example.com/hook") is False
    assert _is_safe_webhook_url("file:///etc/passwd") is False


def test_is_safe_webhook_url_blocks_resolution_failure(monkeypatch):
    from services import rules_evaluator as reval

    def _boom(*_a, **_k):
        raise OSError("dns failed")

    monkeypatch.setattr(reval.socket, "getaddrinfo", _boom)
    assert reval._is_safe_webhook_url("https://example.com/hook") is False  # noqa: SLF001


def test_is_safe_webhook_url_blocks_private_ips(monkeypatch):
    from services import rules_evaluator as reval

    monkeypatch.setattr(
        reval.socket,
        "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 443))],
    )
    assert reval._is_safe_webhook_url("https://example.com/hook") is False  # noqa: SLF001


def test_is_safe_webhook_url_allows_public_ip(monkeypatch):
    from services import rules_evaluator as reval

    monkeypatch.delenv("ALLOWED_WEBHOOK_HOSTS", raising=False)
    monkeypatch.delenv("ALLOWED_WEBHOOK_SUFFIXES", raising=False)
    monkeypatch.setattr(
        reval.socket,
        "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))],
    )
    assert reval._is_safe_webhook_url("https://example.com/hook") is True  # noqa: SLF001


def test_is_safe_webhook_url_host_allowlist(monkeypatch):
    from services import rules_evaluator as reval

    monkeypatch.setenv("ALLOWED_WEBHOOK_HOSTS", "allowed.example.com, other.example.com")
    monkeypatch.delenv("ALLOWED_WEBHOOK_SUFFIXES", raising=False)
    monkeypatch.setattr(
        reval.socket,
        "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))],
    )

    assert reval._is_safe_webhook_url("https://allowed.example.com/h") is True  # noqa: SLF001
    assert reval._is_safe_webhook_url("https://not-allowed.example.com/h") is False  # noqa: SLF001


def test_is_safe_webhook_url_suffix_allowlist(monkeypatch):
    from services import rules_evaluator as reval

    monkeypatch.delenv("ALLOWED_WEBHOOK_HOSTS", raising=False)
    monkeypatch.setenv("ALLOWED_WEBHOOK_SUFFIXES", ".example.com")
    monkeypatch.setattr(
        reval.socket,
        "getaddrinfo",
        lambda *_a, **_k: [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("93.184.216.34", 443))],
    )

    assert reval._is_safe_webhook_url("https://a.example.com/h") is True  # noqa: SLF001
    assert reval._is_safe_webhook_url("https://example.com/h") is True  # noqa: SLF001
    assert reval._is_safe_webhook_url("https://evil.com/h") is False  # noqa: SLF001


def test_call_webhook_respects_safety_gate(monkeypatch):
    from services import rules_evaluator as reval

    # Ensure requests.post isn't called when URL is blocked
    import requests

    post = MagicMock()
    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr(reval, "_is_safe_webhook_url", lambda *_a, **_k: False)

    reval._call_webhook({"type": "webhook", "webhook_url": "https://example.com/h"}, {"x": 1})  # noqa: SLF001
    assert post.call_count == 0

    # When allowed, it should post once
    monkeypatch.setattr(reval, "_is_safe_webhook_url", lambda *_a, **_k: True)
    reval._call_webhook({"type": "webhook", "webhook_url": "https://example.com/h"}, {"x": 1})  # noqa: SLF001
    assert post.call_count == 1


class _FakeTelegramResponse:
    def __init__(self, payload):
        self.status_code = 200
        self.url = "https://api.telegram.org/botXXX/sendMessage"
        self._payload = payload

    def json(self):
        return self._payload


def test_send_alert_dispatches_to_telegram_direct(monkeypatch):
    from services import rules_evaluator as reval
    import http_sync

    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "tkn")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "123")

    calls = {}

    def _req(method, url, json=None, timeout=None):  # noqa: A002
        calls["method"] = method
        calls["url"] = url
        calls["json"] = json
        calls["timeout"] = timeout
        return _FakeTelegramResponse({"ok": True, "result": {"message_id": 1}})

    monkeypatch.setattr(http_sync, "request", _req)

    evaluation = {
        "matched": True,
        "alert_data": {"summary": "hello", "severity": "warn"},
        "rules": [
            {
                "rule_id": "r1",
                "rule_name": "My Rule",
                "triggered_conditions": ["severity == warn", "source == internal"],
                "actions": [
                    {
                        "type": "send_alert",
                        "channel": "telegram",
                        "message_template": "Rule={{rule_name}}\nSeverity={{severity}}\nSummary={{summary}}\nTriggered:\n{{triggered_conditions_json}}",
                    }
                ],
            }
        ],
    }

    reval.execute_matched_actions(evaluation)

    assert calls["method"] == "POST"
    assert calls["url"] == "https://api.telegram.org/bottkn/sendMessage"
    assert calls["timeout"] == 5
    assert calls["json"]["chat_id"] == "123"
    assert "My Rule" in calls["json"]["text"]
    assert "warn" in calls["json"]["text"]
    assert "hello" in calls["json"]["text"]


def test_send_alert_fail_open_on_telegram_error(monkeypatch):
    from services import rules_evaluator as reval
    import http_sync

    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "tkn")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "123")

    def _boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(http_sync, "request", _boom)

    # Must not raise (fail-open)
    reval._send_custom_notification(  # noqa: SLF001
        {"type": "send_alert", "channel": "telegram", "message_template": "{{rule_name}}: {{summary}}"},
        {"summary": "hello", "severity": "warn"},
        {"rule_id": "r1", "rule_name": "My Rule", "triggered_conditions": ["x"]},
    )
