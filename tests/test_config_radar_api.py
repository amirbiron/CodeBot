import importlib


def _build_app():
    app_mod = importlib.import_module('webapp.app')
    app = app_mod.app
    app.testing = True
    return app


def test_config_radar_requires_admin(monkeypatch):
    monkeypatch.setenv('ADMIN_USER_IDS', '1')
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 2  # not in allow list
            sess['user_data'] = {'first_name': 'Regular'}
        resp = client.get('/api/config/radar')
        assert resp.status_code == 403
        payload = resp.get_json()
        assert payload['ok'] is False
        assert payload['error'] == 'admin_only'


def test_config_radar_returns_snapshot(monkeypatch):
    admin_id = 321
    monkeypatch.setenv('ADMIN_USER_IDS', str(admin_id))
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = admin_id
            sess['user_data'] = {'first_name': 'Admin'}
        resp = client.get('/api/config/radar')
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload['ok'] is True
        assert payload['validation']['status'] == 'ok'
        assert isinstance(payload['alerts'], dict)
        assert isinstance(payload['error_signatures'], dict)
        assert isinstance(payload['image_settings'], dict)
        assert payload['alerts']['window_minutes'] == 5
        assert payload['error_signatures']['categories']
