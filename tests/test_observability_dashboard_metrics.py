import sys
import types
from datetime import datetime, timezone


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
