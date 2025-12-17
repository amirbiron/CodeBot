import pytest

from datetime import datetime, timezone

from services import observability_http as obs_http
from services import observability_dashboard as obs_dash


def test_is_private_ip_detects_loopback():
    assert obs_http.is_private_ip("127.0.0.1") is True
    assert obs_http.is_private_ip("8.8.8.8") is False


def test_resolve_and_validate_domain_rejects_private(monkeypatch):
    def fake_getaddrinfo(*_args, **_kwargs):
        return [(None, None, None, None, ("10.0.0.5", 0))]

    monkeypatch.setattr(obs_http.socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(obs_http.SecurityError):
        obs_http.resolve_and_validate_domain("example.com")


def test_fetch_graph_securely_rewrites_host(monkeypatch):
    locked_ip = "93.184.216.34"

    def fake_getaddrinfo(*_args, **_kwargs):
        return [(None, None, None, None, (locked_ip, 0))]

    monkeypatch.setattr(obs_http.socket, "getaddrinfo", fake_getaddrinfo)

    class DummyResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self):
            return None

    class DummySession:
        def __init__(self):
            self.called = {}
            self.mounted = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def mount(self, prefix, adapter):
            self.mounted[prefix] = adapter

        def get(self, url, headers, timeout, allow_redirects, verify):
            self.called = {
                "url": url,
                "headers": headers,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
                "verify": verify,
            }
            return DummyResponse(b'{"ok": true}')

    dummy_session = DummySession()
    monkeypatch.setattr(obs_http.requests, "Session", lambda: dummy_session)

    payload = obs_http.fetch_graph_securely(
        "https://grafana.example.com/render?panel={panel}",
        panel="45",
    )

    assert payload == b'{"ok": true}'
    assert dummy_session.called["url"].startswith(f"https://{locked_ip}")
    assert dummy_session.called["headers"]["Host"] == "grafana.example.com"
    assert dummy_session.called["allow_redirects"] is False


def test_fetch_graph_securely_preserves_basic_auth(monkeypatch):
    locked_ip = "93.184.216.34"

    def fake_getaddrinfo(*_args, **_kwargs):
        return [(None, None, None, None, (locked_ip, 0))]

    monkeypatch.setattr(obs_http.socket, "getaddrinfo", fake_getaddrinfo)

    class DummyResponse:
        def __init__(self, content: bytes):
            self.content = content

        def raise_for_status(self):
            return None

    class DummySession:
        def __init__(self):
            self.called = {}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def mount(self, *_args, **_kwargs):
            return None

        def get(self, url, headers, timeout, allow_redirects, verify):
            self.called = {
                "url": url,
                "headers": headers,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
                "verify": verify,
            }
            return DummyResponse(b'{"ok": true}')

    dummy_session = DummySession()
    monkeypatch.setattr(obs_http.requests, "Session", lambda: dummy_session)

    obs_http.fetch_graph_securely(
        "https://user:pass@grafana.example.com/render?panel={panel}",
        panel="99",
    )

    assert dummy_session.called["url"].startswith(f"https://user:pass@{locked_ip}")
    assert dummy_session.called["headers"]["Host"] == "grafana.example.com"


def test_http_get_json_decodes_payload(monkeypatch):
    monkeypatch.setattr(obs_dash, "fetch_graph_securely", lambda *a, **k: b'{"value": 1}')
    data = obs_dash._http_get_json("https://example.com/path")
    assert data == {"value": 1}


def test_http_get_json_wraps_security_error(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise obs_http.SecurityError("blocked")

    monkeypatch.setattr(obs_dash, "fetch_graph_securely", _raise)
    with pytest.raises(obs_http.SecurityError) as exc:
        obs_dash._http_get_json("https://example.com/path")
    assert "visual_context_fetch_blocked" in str(exc.value)


def test_fetch_aggregations_handles_naive_and_aware_datetimes(monkeypatch):
    # Avoid cache interference
    monkeypatch.setattr(obs_dash, "_cache_get", lambda *_a, **_k: None)
    monkeypatch.setattr(obs_dash, "_cache_set", lambda *_a, **_k: None)

    monkeypatch.setattr(
        obs_dash.alerts_storage,
        "aggregate_alert_summary",
        lambda **_kwargs: {"total": 2, "critical": 0, "anomaly": 1, "deployment": 1},
    )

    def _fake_fetch_alert_timestamps(*, start_dt, end_dt, severity=None, alert_type=None, limit=500):
        # Deployment timestamps come back as UTC-aware
        if alert_type == "deployment_event":
            return [datetime(2025, 1, 1, 0, 30, tzinfo=timezone.utc)]
        # Anomaly timestamps come back as offset-naive (common in DB)
        if severity == "anomaly":
            return [datetime(2025, 1, 1, 0, 45)]
        return []

    monkeypatch.setattr(obs_dash.alerts_storage, "fetch_alert_timestamps", _fake_fetch_alert_timestamps)

    monkeypatch.setattr(
        obs_dash.metrics_storage,
        "aggregate_top_endpoints",
        lambda **_kwargs: [
            {"endpoint": "/healthz", "method": "GET", "count": 1, "avg_duration": 0.1, "max_duration": 0.1}
        ],
    )
    monkeypatch.setattr(obs_dash.metrics_storage, "average_request_duration", lambda **_kwargs: 1.23)

    payload = obs_dash.fetch_aggregations(
        start_dt=datetime(2025, 1, 1, 0, 0, tzinfo=timezone.utc),
        end_dt=datetime(2025, 1, 1, 2, 0, tzinfo=timezone.utc),
        slow_endpoints_limit=5,
    )

    assert payload["deployment_correlation"]["anomalies_not_related_to_deployment_percent"] == 0.0
    assert payload["deployment_correlation"]["avg_spike_during_deployment"] == 1.23
