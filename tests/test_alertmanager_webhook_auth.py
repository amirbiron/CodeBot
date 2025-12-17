import importlib


def _build_app(monkeypatch):
    app_mod = importlib.import_module('webapp.app')

    # Avoid side effects (Telegram/Slack forwarding)
    monkeypatch.setattr(app_mod, '_forward_alerts', lambda alerts: None, raising=True)

    app = app_mod.app
    app.testing = True
    return app


def _payload():
    return {
        'alerts': [
            {
                'labels': {'alertname': 'ServiceDown', 'severity': 'critical'},
                'annotations': {'summary': 'service down'},
            }
        ]
    }


def test_alertmanager_webhook_allows_when_no_guards_configured(monkeypatch):
    monkeypatch.delenv('ALERTMANAGER_WEBHOOK_SECRET', raising=False)
    monkeypatch.delenv('ALERTMANAGER_IP_ALLOWLIST', raising=False)

    app = _build_app(monkeypatch)
    with app.test_client() as client:
        resp = client.post('/alertmanager/webhook', json=_payload())
        assert resp.status_code == 200
        data = resp.get_json()
        assert data and data.get('status') == 'ok'
        assert data.get('forwarded') == 1


def test_alertmanager_webhook_requires_token_when_secret_configured(monkeypatch):
    monkeypatch.setenv('ALERTMANAGER_WEBHOOK_SECRET', 'secret123')
    monkeypatch.delenv('ALERTMANAGER_IP_ALLOWLIST', raising=False)

    app = _build_app(monkeypatch)
    with app.test_client() as client:
        resp = client.post('/alertmanager/webhook', json=_payload())
        assert resp.status_code == 403


def test_alertmanager_webhook_accepts_token_query_param(monkeypatch):
    monkeypatch.setenv('ALERTMANAGER_WEBHOOK_SECRET', 'secret123')
    monkeypatch.delenv('ALERTMANAGER_IP_ALLOWLIST', raising=False)

    app = _build_app(monkeypatch)
    with app.test_client() as client:
        resp = client.post('/alertmanager/webhook?token=secret123', json=_payload())
        assert resp.status_code == 200


def test_alertmanager_webhook_accepts_secret_query_param(monkeypatch):
    monkeypatch.setenv('ALERTMANAGER_WEBHOOK_SECRET', 'secret123')
    monkeypatch.delenv('ALERTMANAGER_IP_ALLOWLIST', raising=False)

    app = _build_app(monkeypatch)
    with app.test_client() as client:
        resp = client.post('/alertmanager/webhook?secret=secret123', json=_payload())
        assert resp.status_code == 200


def test_alertmanager_webhook_accepts_authorization_bearer(monkeypatch):
    monkeypatch.setenv('ALERTMANAGER_WEBHOOK_SECRET', 'secret123')
    monkeypatch.delenv('ALERTMANAGER_IP_ALLOWLIST', raising=False)

    app = _build_app(monkeypatch)
    with app.test_client() as client:
        resp = client.post(
            '/alertmanager/webhook',
            json=_payload(),
            headers={'Authorization': 'Bearer secret123'},
        )
        assert resp.status_code == 200


def test_alertmanager_webhook_allows_ip_allowlist_exact_match(monkeypatch):
    monkeypatch.delenv('ALERTMANAGER_WEBHOOK_SECRET', raising=False)
    monkeypatch.setenv('ALERTMANAGER_IP_ALLOWLIST', '1.2.3.4')

    app = _build_app(monkeypatch)
    with app.test_client() as client:
        resp = client.post(
            '/alertmanager/webhook',
            json=_payload(),
            environ_base={'REMOTE_ADDR': '1.2.3.4'},
        )
        assert resp.status_code == 200


def test_alertmanager_webhook_allows_ip_allowlist_cidr(monkeypatch):
    monkeypatch.delenv('ALERTMANAGER_WEBHOOK_SECRET', raising=False)
    monkeypatch.setenv('ALERTMANAGER_IP_ALLOWLIST', '1.2.3.0/24')

    app = _build_app(monkeypatch)
    with app.test_client() as client:
        resp = client.post(
            '/alertmanager/webhook',
            json=_payload(),
            environ_base={'REMOTE_ADDR': '1.2.3.4'},
        )
        assert resp.status_code == 200


def test_alertmanager_webhook_blocks_ip_outside_allowlist(monkeypatch):
    monkeypatch.delenv('ALERTMANAGER_WEBHOOK_SECRET', raising=False)
    monkeypatch.setenv('ALERTMANAGER_IP_ALLOWLIST', '1.2.3.0/24')

    app = _build_app(monkeypatch)
    with app.test_client() as client:
        resp = client.post(
            '/alertmanager/webhook',
            json=_payload(),
            environ_base={'REMOTE_ADDR': '9.9.9.9'},
        )
        assert resp.status_code == 403
