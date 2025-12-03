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
    monkeypatch.setitem(sys.modules, 'predictive_engine', fake_pe)

    payload = obs.fetch_timeseries(
        start_dt=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_dt=datetime(2025, 1, 1, 1, tzinfo=timezone.utc),
        granularity_seconds=900,
        metric='memory_usage_percent',
    )

    assert payload['metric'] == 'memory_usage_percent'
    assert payload['data']
    assert abs(payload['data'][0]['value'] - 82.5) < 0.01


def test_fetch_timeseries_requests_per_minute(monkeypatch):
    from services import observability_dashboard as obs

    def _fake_request_ts(**kwargs):
        return [
            {'timestamp': '2025-01-01T00:00:00+00:00', 'count': 120, 'avg_duration': 0.4, 'max_duration': 1.2},
            {'timestamp': '2025-01-01T01:00:00+00:00', 'count': 60, 'avg_duration': 0.5, 'max_duration': 1.0},
        ]

    monkeypatch.setattr(obs.metrics_storage, 'aggregate_request_timeseries', _fake_request_ts)

    payload = obs.fetch_timeseries(
        start_dt=datetime(2025, 1, 1, tzinfo=timezone.utc),
        end_dt=datetime(2025, 1, 1, 2, tzinfo=timezone.utc),
        granularity_seconds=3600,
        metric='requests_per_minute',
    )

    assert payload['metric'] == 'requests_per_minute'
    points = payload['data']
    assert len(points) == 2
    assert abs(points[0]['requests_per_minute'] - 2.0) < 0.01  # 120 per hour -> 2 per minute
    assert abs(points[1]['requests_per_minute'] - 1.0) < 0.01


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

    def _fake_http_get(url, headers=None, timeout=None):
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

    def _fake_http_get(url, headers=None, timeout=None):
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
