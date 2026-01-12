import importlib
import os


def _import_app():
    os.environ.setdefault("COMMUNITY_LIBRARY_ENABLED", "1")
    os.environ.setdefault("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", "1")
    app_mod = importlib.import_module('webapp.app')
    app = app_mod.app
    app.testing = True
    return app


def test_compare_paste_page_requires_login():
    """דף ההדבקה דורש התחברות."""
    app = _import_app()
    with app.test_client() as c:
        r = c.get('/compare/paste')
        # אם יש login_required, צפוי redirect
        assert r.status_code in (302, 401)


def test_compare_paste_page_authenticated():
    """דף ההדבקה נטען למשתמש מחובר."""
    app = _import_app()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 123
        r = c.get('/compare/paste')
        assert r.status_code == 200
        assert 'השוואת קוד בהדבקה' in r.data.decode('utf-8')


def test_compare_diff_api_empty_content():
    """API מחזיר תוצאה גם לתוכן ריק (למשתמש מחובר)."""
    app = _import_app()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 123
        r = c.post('/api/compare/diff',
                   json={"left_content": "", "right_content": ""})
        assert r.status_code == 200
        data = r.get_json()
        assert data and 'stats' in data and isinstance(data['stats'], dict)


def test_compare_diff_api_identical():
    """API מזהה קבצים זהים (למשתמש מחובר)."""
    app = _import_app()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 123
        content = "line1\nline2\nline3"
        r = c.post('/api/compare/diff',
                   json={"left_content": content, "right_content": content})
        assert r.status_code == 200
        data = r.get_json()
        assert data['stats']['added'] == 0
        assert data['stats']['removed'] == 0
        assert data['stats']['modified'] == 0
        assert data['stats']['unchanged'] == 3


def test_compare_diff_api_differences():
    """API מזהה הבדלים (למשתמש מחובר)."""
    app = _import_app()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 123
        r = c.post('/api/compare/diff',
                   json={
                       "left_content": "a\nb\nc",
                       "right_content": "a\nx\nc\nd"
                   })
        assert r.status_code == 200
        data = r.get_json()
        assert data['stats']['modified'] == 1  # b -> x
        assert data['stats']['added'] == 1     # d
        assert data['stats']['unchanged'] == 2  # a, c

