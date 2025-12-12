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


def test_observability_runbook_requires_admin(monkeypatch):
    monkeypatch.setenv('ADMIN_USER_IDS', '10')
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 4
        resp = client.get('/api/observability/runbook/demo')
    assert resp.status_code == 403


def test_observability_runbook_returns_payload(monkeypatch):
    admin_id = 11
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))

    captured = {}

    def _fake_fetch(event_id, fallback_metadata=None):
        captured['event_id'] = event_id
        captured['fallback'] = fallback_metadata
        return {'event': {'id': event_id}, 'runbook': {'title': 'Demo', 'steps': []}, 'actions': [], 'status': {}}

    monkeypatch.setattr(
        'webapp.app.observability_service.fetch_runbook_for_event',
        _fake_fetch,
    )

    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        resp = client.get('/api/observability/runbook/evt?alert_type=demo_alert')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['ok'] is True
    assert data['event']['id'] == 'evt'
    assert captured['event_id'] == 'evt'


def test_observability_runbook_status_updates(monkeypatch):
    admin_id = 12
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))
    captured = {}

    def _fake_update(event_id, step_id, completed, user_id, fallback_metadata=None):
        captured.update({
            'event_id': event_id,
            'step_id': step_id,
            'completed': completed,
            'user_id': user_id,
            'fallback': fallback_metadata,
        })
        return {'event': {'id': event_id}, 'runbook': {'title': 'Demo', 'steps': [{'id': step_id, 'completed': completed}]}, 'actions': [], 'status': {'completed_steps': [step_id]}}

    monkeypatch.setattr(
        'webapp.app.observability_service.update_runbook_step_status',
        _fake_update,
    )

    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        resp = client.post('/api/observability/runbook/evt/status', json={
            'step_id': 'check',
            'completed': True,
            'event': {
                'id': 'evt',
                'alert_type': 'demo_alert',
                'type': 'alert',
                'severity': 'critical',
                'summary': 'demo',
                'title': 'Demo',
                'timestamp': '2025-01-01T00:00:00Z',
                'metadata': {
                    'alert_type': 'demo_alert',
                    'endpoint': '/healthz',
                },
            },
        })
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload['ok'] is True
    assert payload['status']['completed_steps'] == ['check']
    assert captured['step_id'] == 'check'
    assert captured['completed'] is True
    assert captured['fallback']['alert_type'] == 'demo_alert'


def test_observability_ai_explain_requires_admin(monkeypatch):
    monkeypatch.setenv('ADMIN_USER_IDS', '10')
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 99
        resp = client.post('/api/observability/alerts/ai_explain', json={'alert': {}})
        assert resp.status_code == 403
        payload = resp.get_json()
        assert payload['error'] == 'admin_only'


def test_observability_ai_explain_returns_payload(monkeypatch):
    admin_id = 5
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))
    captured = {}

    def _fake_explain(alert_snapshot, *, force_refresh=False):
        captured['alert'] = alert_snapshot
        captured['force'] = force_refresh
        return {
            'alert_uid': 'u1',
            'root_cause': 'test root',
            'actions': ['a'],
            'signals': ['b'],
            'provider': 'heuristic',
            'generated_at': '2025-01-01T00:00:00Z',
            'cached': False,
        }

    monkeypatch.setattr(
        'webapp.app.observability_service.explain_alert_with_ai',
        _fake_explain,
    )

    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        resp = client.post(
            '/api/observability/alerts/ai_explain',
            json={'alert': {'alert_uid': 'A1'}, 'force': True},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['explanation']['root_cause'] == 'test root'

    assert captured['alert']['alert_uid'] == 'A1'
    assert captured['force'] is True


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


def test_observability_coverage_requires_admin(monkeypatch):
    monkeypatch.setenv('ADMIN_USER_IDS', '10')
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 99
        resp = client.get('/api/observability/coverage')
        assert resp.status_code == 403
        payload = resp.get_json()
        assert payload['error'] == 'admin_only'


def test_observability_coverage_calls_service(monkeypatch):
    admin_id = 77
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))
    captured = {}

    def _fake_report(*, start_dt, end_dt, min_count=1):
        captured['start_dt'] = start_dt
        captured['end_dt'] = end_dt
        captured['min_count'] = min_count
        return {'missing_runbooks': [], 'missing_quick_fixes': [], 'orphan_runbooks': [], 'orphan_quick_fixes': [], 'meta': {}}

    monkeypatch.setattr('webapp.app.observability_service.build_coverage_report', _fake_report)
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
        resp = client.get('/api/observability/coverage?timerange=24h&min_count=3')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['ok'] is True
        assert data['missing_runbooks'] == []

    assert captured['min_count'] == 3
    assert captured['end_dt'] >= captured['start_dt']


def test_coverage_logic_missing_and_orphans(monkeypatch, tmp_path):
    # Unit test for matching logic (runbook coverage, quick-fix coverage) and orphan detection.
    from datetime import timedelta
    import importlib

    svc = importlib.import_module('services.observability_dashboard')
    alerts_storage = importlib.import_module('monitoring.alerts_storage')

    runbooks_yaml = """
version: 1
default: generic_incident_flow
runbooks:
  a:
    title: "A"
    aliases: ["a_alias"]
    steps:
      - id: s1
        title: "step"
        action:
          label: "do"
          type: copy
          payload: "/do"
  b:
    title: "B"
    aliases: ["alias_only"]
    steps:
      - id: s2
        title: "no action"
  orphaned_runbook:
    title: "Orphan"
    aliases: ["old_alias"]
    steps: []
  generic_incident_flow:
    title: "Default"
    default: true
    steps:
      - id: g1
        title: "fallback"
"""

    quick_fixes_json = """
{
  "version": 1,
  "by_alert_type": {
    "a": [{"id":"x","label":"x","type":"copy","payload":"/x"}],
    "dead_alert": [{"id":"y","label":"y","type":"copy","payload":"/y"}]
  },
  "by_severity": {},
  "fallback": []
}
"""

    rb_path = tmp_path / 'runbooks.yml'
    qf_path = tmp_path / 'quickfix.json'
    rb_path.write_text(runbooks_yaml, encoding='utf-8')
    qf_path.write_text(quick_fixes_json, encoding='utf-8')

    # Patch service module paths + reset caches
    monkeypatch.setattr(svc, '_RUNBOOK_PATH', rb_path, raising=True)
    monkeypatch.setattr(svc, '_QUICK_FIX_PATH', qf_path, raising=True)
    monkeypatch.setattr(svc, '_RUNBOOK_CACHE', {}, raising=True)
    monkeypatch.setattr(svc, '_RUNBOOK_ALIAS_MAP', {}, raising=True)
    monkeypatch.setattr(svc, '_RUNBOOK_MTIME', 0.0, raising=True)
    monkeypatch.setattr(svc, '_QUICK_FIX_CACHE', {}, raising=True)
    monkeypatch.setattr(svc, '_QUICK_FIX_MTIME', 0.0, raising=True)

    now = datetime.now(timezone.utc)
    start_dt = now - timedelta(hours=24)
    end_dt = now

    def _fake_catalog(*, min_total_count=1, limit=50000):
        # Respect min_total_count to mimic real catalog behavior
        base = [
            {"alert_type": "a", "count": 2, "last_seen_dt": end_dt, "sample_title": "A", "sample_name": "A"},
            {"alert_type": "alias_only", "count": 1, "last_seen_dt": end_dt, "sample_title": "B", "sample_name": "B"},
            {"alert_type": "unknown", "count": 5, "last_seen_dt": end_dt, "sample_title": "U", "sample_name": "U"},
        ]
        return [row for row in base if int(row["count"]) >= int(min_total_count or 1)]

    monkeypatch.setattr(alerts_storage, 'fetch_alert_type_catalog', _fake_catalog, raising=True)

    report = svc.build_coverage_report(start_dt=start_dt, end_dt=end_dt, min_count=1)
    assert isinstance(report, dict)
    assert report['missing_runbooks'][0]['alert_type'] == 'unknown'
    assert all(item['alert_type'] != 'a' for item in report['missing_runbooks'])
    # alias_only has a runbook (via alias) but no per-alert quick fixes -> should be missing quick fixes
    assert any(item['alert_type'] == 'alias_only' for item in report['missing_quick_fixes'])
    # Orphan runbook should be detected; default should not appear
    assert any(item['runbook_key'] == 'orphaned_runbook' for item in report['orphan_runbooks'])
    assert all(item['runbook_key'] != 'generic_incident_flow' for item in report['orphan_runbooks'])
    # Orphan quick fix key
    assert any(item['alert_type'] == 'dead_alert' for item in report['orphan_quick_fixes'])
    assert report['meta']['mode'] == 'catalog'

    report_min = svc.build_coverage_report(start_dt=start_dt, end_dt=end_dt, min_count=2)
    # alias_only filtered out by min_count, so it shouldn't appear in missing quick fixes
    assert all(item['alert_type'] != 'alias_only' for item in report_min['missing_quick_fixes'])
