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


def test_story_template_requires_admin(monkeypatch):
    monkeypatch.setenv('ADMIN_USER_IDS', '10')
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 99  # משתמש מחובר אך לא אדמין
        resp = client.post('/api/observability/story/template', json={'alert': {}})
    assert resp.status_code == 403


def test_story_template_returns_payload(monkeypatch):
    admin_id = 91
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))
    captured = {}

    def _fake_template(alert_snapshot, timerange_label=None):
        captured['alert'] = alert_snapshot
        captured['timerange'] = timerange_label
        return {'alert_uid': 'a1'}

    monkeypatch.setattr('webapp.app.observability_service.build_story_template', _fake_template)
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        resp = client.post('/api/observability/story/template', json={'alert': {'alert_uid': 'x'}, 'timerange': '1h'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['story']['alert_uid'] == 'a1'
    assert captured['alert']['alert_uid'] == 'x'
    assert captured['timerange'] == '1h'


def test_story_save_calls_service(monkeypatch):
    admin_id = 55
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))
    captured = {}

    def _fake_save(payload, user_id=None):
        captured['payload'] = payload
        captured['user_id'] = user_id
        return {**payload, 'story_id': 's-1'}

    monkeypatch.setattr('webapp.app.observability_service.save_incident_story', _fake_save)
    app = _build_app()
    body = {
        'alert_uid': 'alert-1',
        'time_window': {'start': '2025-01-01T00:00:00Z', 'end': '2025-01-01T01:00:00Z'},
        'what_we_saw': {'description': 'desc'},
    }
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        resp = client.post('/api/observability/stories', json=body)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['story']['story_id'] == 's-1'
    assert captured['payload']['alert_uid'] == 'alert-1'
    assert captured['user_id'] == admin_id


def test_story_get_endpoint(monkeypatch):
    admin_id = 33
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))

    def _fake_fetch(story_id):
        return {'story_id': story_id}

    monkeypatch.setattr('webapp.app.observability_service.fetch_story', _fake_fetch)
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        resp = client.get('/api/observability/stories/demo')
        assert resp.status_code == 200
        assert resp.get_json()['story']['story_id'] == 'demo'


def test_story_export_markdown(monkeypatch):
    admin_id = 22
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))

    def _fake_export(story_id):
        return f"# Story {story_id}\n"

    monkeypatch.setattr('webapp.app.observability_service.export_story_markdown', _fake_export)
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        resp = client.get('/api/observability/stories/demo/export')
        assert resp.status_code == 200
        assert resp.mimetype == 'text/markdown'
        assert b'Story demo' in resp.data


def test_story_save_markdown_requires_admin(monkeypatch):
    monkeypatch.setenv('ADMIN_USER_IDS', '42')
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 7
        resp = client.post('/api/observability/stories/save_markdown', json={'file_name': 'demo', 'story': {}})
    assert resp.status_code == 403


def test_story_save_markdown_calls_helpers(monkeypatch):
    admin_id = 77
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))
    captured = {}

    def _fake_render(story_payload):
        captured['story'] = story_payload
        return '# story markdown'

    def _fake_persist(**kwargs):
        captured['persist'] = kwargs
        fname = kwargs['file_name']
        if not fname.endswith('.md'):
            fname = f'{fname}.md'
        return {'file_id': 'abc', 'file_name': fname, 'version': 1}

    monkeypatch.setattr('webapp.app.observability_service.render_story_markdown_inline', _fake_render)
    monkeypatch.setattr('webapp.app._persist_story_markdown_file', _fake_persist)

    payload = {
        'alert_uid': 'alert-55',
        'what_we_saw': {'description': 'desc'},
        'time_window': {'start': '2025-01-01T00:00:00Z', 'end': '2025-01-01T01:00:00Z'}
    }

    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        resp = client.post('/api/observability/stories/save_markdown', json={'file_name': 'incident_story', 'story': payload})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['file_name'].endswith('.md')
        assert data['md_preview_url'].startswith('/md/')
        assert data['view_url'].startswith('/file/')

    assert captured['story']['alert_uid'] == 'alert-55'
    assert captured['persist']['markdown'] == '# story markdown'
    assert captured['persist']['file_name'] == 'incident_story'
