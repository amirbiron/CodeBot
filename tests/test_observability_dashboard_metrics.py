import sys
import types
from datetime import datetime, timezone

import pytest


def _ts(minutes: int) -> float:
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    return (base.timestamp()) + minutes * 60


def test_fetch_timeseries_predictive_metric(monkeypatch):
    from services import observability_dashboard as obs

    fake_pe = types.SimpleNamespace(
        get_observations=lambda metric, start_ts=None, end_ts=None: [
            (_ts(0), 82.5),
            (_ts(15), 83.0),
        ]
    )
    monkeypatch.setitem(sys.modules, "predictive_engine", fake_pe)

    payload = obs.fetch_timeseries(
        start_dt=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_dt=datetime(2025, 1, 1, 1, tzinfo=timezone.utc),
        granularity_seconds=900,
        metric="memory_usage_percent",
    )

    assert payload["metric"] == "memory_usage_percent"
    assert payload["data"]
    assert abs(payload["data"][0]["value"] - 82.5) < 0.01


def test_fetch_timeseries_requests_per_minute(monkeypatch):
    from services import observability_dashboard as obs

    def _fake_request_ts(**kwargs):
        return [
            {
                "timestamp": "2025-01-01T00:00:00+00:00",
                "count": 120,
                "avg_duration": 0.4,
                "max_duration": 1.2,
            },
            {
                "timestamp": "2025-01-01T01:00:00+00:00",
                "count": 60,
                "avg_duration": 0.5,
                "max_duration": 1.0,
            },
        ]

    monkeypatch.setattr(obs.metrics_storage, "aggregate_request_timeseries", _fake_request_ts)

    payload = obs.fetch_timeseries(
        start_dt=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_dt=datetime(2025, 1, 1, 2, tzinfo=timezone.utc),
        granularity_seconds=3600,
        metric="requests_per_minute",
    )

    assert payload["metric"] == "requests_per_minute"
    points = payload["data"]
    assert len(points) == 2
    assert abs(points[0]["requests_per_minute"] - 2.0) < 0.01  # 120 per hour -> 2 per minute
    assert abs(points[1]["requests_per_minute"] - 1.0) < 0.01


def test_fetch_timeseries_external_metric_enforces_allowlist(monkeypatch):
    from services import observability_dashboard as obs

    obs._CACHE.clear()
    obs._EXTERNAL_ALLOWED_METRICS = {"external_metric"}

    def _fake_get_definition(metric):
        return {
            "metric": metric,
            "source": "external",
            "label": "External Metric",
            "unit": "%",
            "category": "spike",
            "default_range": "1h",
            "allowed_hosts": ["safe.example"],
            "external_config": {
                "graph_url_template": "https://safe.example/api?metric={{metric_name}}",
                "value_key": "value",
                "timestamp_key": "timestamp",
            },
        }

    captured = {}

    def _fake_http_get(url, *, headers=None, timeout=None, allowed_hosts=None):
        captured["url"] = url
        return {"data": [{"timestamp": "2025-01-01T00:00:00+00:00", "value": 42.0}]}

    monkeypatch.setattr(obs, "_get_metric_definition", _fake_get_definition)
    monkeypatch.setattr(obs, "_http_get_json", _fake_http_get)

    payload = obs.fetch_timeseries(
        start_dt=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_dt=datetime(2025, 1, 1, 0, 30, tzinfo=timezone.utc),
        granularity_seconds=900,
        metric="external_metric",
    )

    assert payload["metric"] == "external_metric"
    assert payload["data"][0]["value"] == 42.0
    assert captured["url"].startswith("https://safe.example/")


def test_fetch_timeseries_external_metric_blocks_unknown_host(monkeypatch):
    from services import observability_dashboard as obs

    obs._CACHE.clear()
    obs._EXTERNAL_ALLOWED_METRICS = {"external_metric"}

    def _fake_get_definition(metric):
        return {
            "metric": metric,
            "source": "external",
            "label": "External Metric",
            "unit": "%",
            "category": "spike",
            "default_range": "1h",
            "allowed_hosts": ["safe.example"],
            "external_config": {
                "graph_url_template": "https://evil.example/api?metric={{metric_name}}",
            },
        }

    def _fake_http_get(url, *, headers=None, timeout=None, allowed_hosts=None):
        raise AssertionError("HTTP request should not be executed for blocked host")

    monkeypatch.setattr(obs, "_get_metric_definition", _fake_get_definition)
    monkeypatch.setattr(obs, "_http_get_json", _fake_http_get)

    payload = obs.fetch_timeseries(
        start_dt=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_dt=datetime(2025, 1, 1, 0, 30, tzinfo=timezone.utc),
        granularity_seconds=900,
        metric="external_metric",
    )

    # Host is not on allowlist -> no data and no outbound HTTP call.
    assert payload["metric"] == "external_metric"
    assert payload["data"] == []


def test_fetch_timeseries_external_metric_not_allowlisted(monkeypatch):
    from services import observability_dashboard as obs

    obs._CACHE.clear()
    obs._EXTERNAL_ALLOWED_METRICS = set()

    def _fake_get_definition(metric):
        return {
            "metric": metric,
            "source": "external",
            "label": "External Metric",
            "unit": "%",
            "category": "spike",
            "default_range": "1h",
            "allowed_hosts": ["safe.example"],
            "external_config": {
                "graph_url_template": "https://safe.example/api?metric={{metric_name}}",
            },
        }

    monkeypatch.setattr(obs, "_get_metric_definition", _fake_get_definition)

    with pytest.raises(ValueError):
        obs.fetch_timeseries(
            start_dt=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end_dt=datetime(2025, 1, 1, 0, 30, tzinfo=timezone.utc),
            granularity_seconds=900,
            metric="external_metric",
        )


def test_is_public_ip_blocks_loopback():
    from services.observability_dashboard import is_public_ip

    # IPv4 loopback
    assert is_public_ip("127.0.0.1") is False
    assert is_public_ip("127.0.0.255") is False

    # IPv6 loopback
    assert is_public_ip("::1") is False


def test_is_public_ip_blocks_private_ranges():
    from services.observability_dashboard import is_public_ip

    # Private IPv4 ranges
    assert is_public_ip("10.0.0.1") is False
    assert is_public_ip("10.255.255.255") is False
    assert is_public_ip("192.168.1.1") is False
    assert is_public_ip("192.168.255.255") is False
    assert is_public_ip("172.16.0.1") is False
    assert is_public_ip("172.31.255.255") is False

    # Private IPv6 ranges
    assert is_public_ip("fc00::1") is False
    assert is_public_ip("fd00::1") is False


def test_is_public_ip_blocks_link_local():
    from services.observability_dashboard import is_public_ip

    # IPv4 link-local
    assert is_public_ip("169.254.0.1") is False
    assert is_public_ip("169.254.255.255") is False

    # IPv6 link-local
    assert is_public_ip("fe80::1") is False


def test_is_public_ip_allows_public_ips():
    from services.observability_dashboard import is_public_ip

    # Public IPv4 addresses
    assert is_public_ip("8.8.8.8") is True
    assert is_public_ip("1.1.1.1") is True
    assert is_public_ip("93.184.216.34") is True  # example.com

    # Public IPv6 addresses
    assert is_public_ip("2001:4860:4860::8888") is True  # Google DNS


def test_is_public_ip_rejects_invalid():
    from services.observability_dashboard import is_public_ip

    # Invalid IP addresses
    assert is_public_ip("invalid") is False
    assert is_public_ip("256.256.256.256") is False
    assert is_public_ip("") is False


def test_http_get_json_blocks_localhost_ip(monkeypatch):
    from services.observability_dashboard import _http_get_json
    import socket

    # Mock getaddrinfo to return localhost IP
    def fake_getaddrinfo(host, port, family, socktype):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(RuntimeError, match="private_ip_blocked"):
        _http_get_json("http://safe.example/api", allowed_hosts=["safe.example"])


def test_http_get_json_blocks_private_ip(monkeypatch):
    from services.observability_dashboard import _http_get_json
    import socket

    # Mock getaddrinfo to return private IP
    def fake_getaddrinfo(host, port, family, socktype):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.1.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    with pytest.raises(RuntimeError, match="private_ip_blocked"):
        _http_get_json("http://safe.example/api", allowed_hosts=["safe.example"])


def test_http_get_json_allows_public_ip(monkeypatch):
    from services.observability_dashboard import _http_get_json
    import socket

    # Mock getaddrinfo to return public IP
    def fake_getaddrinfo(host, port, family, socktype):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)

    # Mock HTTP request
    def fake_request(method, url, headers=None, timeout=None):
        class FakeResponse:
            status_code = 200
            text = '{"data": []}'

            def raise_for_status(self):
                pass

        return FakeResponse()

    try:
        import http_sync  # noqa: F401

        monkeypatch.setattr("http_sync.request", fake_request)
    except ImportError:
        # If http_sync is not available, mock requests
        import requests

        monkeypatch.setattr(
            requests,
            "get",
            lambda url, headers=None, timeout=None: fake_request("GET", url, headers, timeout),
        )

    result = _http_get_json("http://safe.example/api", allowed_hosts=["safe.example"])

    assert result == {"data": []}
