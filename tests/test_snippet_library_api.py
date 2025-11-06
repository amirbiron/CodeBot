import importlib
import os

def test_public_snippets_api_ok(monkeypatch):
    os.environ.setdefault("COMMUNITY_LIBRARY_ENABLED", "1")
    app_mod = importlib.import_module('webapp.app')
    app = app_mod.app
    app.testing = True
    with app.test_client() as c:
        r = c.get('/api/snippets')
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, dict) and data.get('ok') is True
        assert 'items' in data and isinstance(data['items'], list)
