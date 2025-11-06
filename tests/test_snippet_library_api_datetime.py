import importlib
import datetime as dt

def test_snippets_api_serializes_datetime(monkeypatch):
    # monkeypatch service to return datetime
    def _fake_list_public_snippets(**kwargs):
        return ([{"title": "t", "description": "d", "code": "c", "language": "py", "approved_at": dt.datetime(2024, 1, 1)}], 1)

    monkeypatch.setenv("COMMUNITY_LIBRARY_ENABLED", "1")
    mod = importlib.import_module('webapp.snippet_library_api')
    monkeypatch.setattr(mod, 'list_public_snippets', lambda **k: _fake_list_public_snippets(**k), raising=True)

    app_mod = importlib.import_module('webapp.app')
    app = app_mod.app
    app.testing = True
    with app.test_client() as c:
        r = c.get('/api/snippets')
        assert r.status_code == 200
        data = r.get_json()
        assert data['ok'] is True
        assert data['items'][0]['approved_at'].startswith('2024-01-01')
