import importlib
from datetime import datetime, timezone


def _build_app():
    app_mod = importlib.import_module('webapp.app')
    app = app_mod.app
    app.testing = True
    return app


def test_observability_alerts_requires_admin(monkeypatch):
    monkeypatch.setenv('ADMIN_USER_IDS', '10')
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 99
        resp = client.get('/api/observability/alerts')
        assert resp.status_code == 403
        payload = resp.get_json()
        assert payload['error'] == 'admin_only'


def test_observability_alerts_returns_data(monkeypatch):
    admin_id = 7
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))

    captured = {}

    def _fake_fetch_alerts(**kwargs):
        captured.update(kwargs)
        return {
            'alerts': [{'name': 'High Error Rate', 'severity': 'critical'}],
            'total': 1,
            'page': kwargs.get('page', 1),
            'per_page': kwargs.get('per_page', 50),
        }

    monkeypatch.setattr(
        'webapp.app.observability_service.fetch_alerts',
        _fake_fetch_alerts,
    )

    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        resp = client.get('/api/observability/alerts?timerange=1h&severity=critical')
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['ok'] is True
        assert payload['total'] == 1
        assert payload['alerts'][0]['name'] == 'High Error Rate'

    assert captured['severity'] == 'critical'
    assert captured['page'] == 1
    assert captured['per_page'] == 50
    assert isinstance(captured['start_dt'], datetime)
    assert isinstance(captured['end_dt'], datetime)
    assert captured['end_dt'] >= captured['start_dt']


def test_observability_aggregations_passes_limit(monkeypatch):
    admin_id = 42
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))

    captured = {}

    def _fake_fetch_aggregations(**kwargs):
        captured.update(kwargs)
        return {
            'summary': {'total': 5, 'critical': 2, 'anomaly': 1, 'deployment': 1},
            'top_slow_endpoints': [],
            'deployment_correlation': {},
        }

    monkeypatch.setattr(
        'webapp.app.observability_service.fetch_aggregations',
        _fake_fetch_aggregations,
    )

    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        resp = client.get('/api/observability/aggregations?timerange=24h&limit=3')
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['ok'] is True
        assert payload['summary']['total'] == 5

    assert captured['slow_endpoints_limit'] == 3
    assert isinstance(captured['start_dt'], datetime)
    assert captured['start_dt'].tzinfo == timezone.utc


def test_observability_timeseries_custom_granularity(monkeypatch):
    admin_id = 77
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))

    captured = {}

    def _fake_fetch_timeseries(**kwargs):
        captured.update(kwargs)
        return {
            'metric': kwargs.get('metric'),
            'data': [{'timestamp': '2025-01-01T00:00:00Z', 'count': 10, 'avg_duration': 0.5, 'error_rate': 0}],
        }

    monkeypatch.setattr(
        'webapp.app.observability_service.fetch_timeseries',
        _fake_fetch_timeseries,
    )

    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        resp = client.get('/api/observability/timeseries?granularity=15m')
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['ok'] is True
        assert payload['metric'] == 'alerts_count'
        assert payload['granularity_seconds'] == 900

    assert captured['granularity_seconds'] == 900
    assert captured['metric'] == 'alerts_count'
