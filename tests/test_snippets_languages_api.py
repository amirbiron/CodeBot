import importlib
import os

def test_snippets_languages_api(monkeypatch):
    os.environ.setdefault("COMMUNITY_LIBRARY_ENABLED", "1")
    # להריץ בסביבה שמאפשרת אדמינים ריקים (לא נדרש כאן אבל בטוח)
    os.environ.setdefault("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", "1")
    app_mod = importlib.import_module('webapp.app')
    app = app_mod.app
    app.testing = True
    with app.test_client() as c:
        r = c.get('/api/snippets/languages')
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, dict) and data.get('ok') is True
        langs = data.get('languages')
        assert isinstance(langs, list)
        # יש לפחות שפה אחת (built-in של השירות כוללים python)
        assert 'python' in [str(x).lower() for x in langs]
