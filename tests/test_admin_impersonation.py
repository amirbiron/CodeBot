import types

import pytest


class _FakeCursor:
    def __init__(self, docs=None):
        self._docs = list(docs or [])

    def sort(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def __iter__(self):
        return iter(self._docs)


class _FakeUsersCollection:
    def find_one(self, query):
        return {}


class _FakeCodeSnippetsCollection:
    def count_documents(self, *args, **kwargs):
        return 0

    def aggregate(self, *args, **kwargs):
        return []

    def find(self, *args, **kwargs):
        return _FakeCursor([])


class _FakeRepoMetadataCollection:
    def find_one(self, query):
        return None


class _FakeDB:
    def __init__(self):
        self.users = _FakeUsersCollection()
        self.code_snippets = _FakeCodeSnippetsCollection()
        self.repo_metadata = _FakeRepoMetadataCollection()


class _FakeMirrorService:
    def mirror_exists(self, *_args, **_kwargs):
        return False

    def get_last_commit_info(self, *_args, **_kwargs):
        return None


@pytest.fixture
def app_mod(monkeypatch):
    import webapp.app as app_mod

    app_mod.app.testing = True
    app_mod.app.config["SECRET_KEY"] = "test"

    fake_db = _FakeDB()
    monkeypatch.setattr(app_mod, "get_db", lambda: fake_db)
    monkeypatch.setattr(app_mod, "get_mirror_service", lambda: _FakeMirrorService())
    monkeypatch.setattr(app_mod, "_build_activity_timeline", lambda *_a, **_k: {
        "groups": [],
        "feed": [],
        "filters": [],
        "compact_limit": 0,
        "has_events": False,
        "updated_at": "",
    })
    monkeypatch.setattr(app_mod, "_build_push_card", lambda *_a, **_k: {
        "feature_enabled": False,
        "subscriptions": 0,
        "status_text": "",
        "status_variant": "",
        "pending_count": 0,
        "last_push": None,
        "next_reminder": None,
        "cta_href": "",
        "cta_label": "",
    })
    monkeypatch.setattr(app_mod, "_build_notes_snapshot", lambda *_a, **_k: {
        "notes": [],
        "total": 0,
        "has_notes": False,
    })
    monkeypatch.setattr(app_mod, "_load_whats_new", lambda *_a, **_k: {
        "features": [],
        "has_features": False,
        "total": 0,
    })
    monkeypatch.setattr(app_mod, "user_stats", types.SimpleNamespace(
        get_all_time_stats=lambda: {"total_users": 1, "active_today": 1, "active_week": 1},
        get_weekly_stats=lambda: [],
    ))

    return app_mod


@pytest.fixture
def client(app_mod):
    with app_mod.app.test_client() as client:
        yield client


@pytest.fixture
def regular_user_session(client, monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    with client.session_transaction() as sess:
        sess["user_id"] = 2
        sess["user_data"] = {"id": 2, "is_admin": False, "is_premium": False}


@pytest.fixture
def admin_user_session(client, monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "1")
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["user_data"] = {"id": 1, "is_admin": True, "is_premium": False}


class TestAdminImpersonation:
    """טסטים למצב Admin Impersonation."""
    
    def test_non_admin_cannot_impersonate(self, client, regular_user_session):
        """משתמש רגיל לא יכול להפעיל Impersonation."""
        response = client.post('/admin/impersonate/start')
        assert response.status_code == 403
    
    def test_admin_can_start_impersonation(self, client, admin_user_session):
        """אדמין יכול להפעיל Impersonation."""
        response = client.post('/admin/impersonate/start')
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
    
    def test_impersonation_hides_admin_ui(self, client, admin_user_session):
        """במצב Impersonation, אלמנטי אדמין נעלמים."""
        # הפעלת Impersonation
        client.post('/admin/impersonate/start')
        
        # בדיקת עמוד הבית
        response = client.get('/dashboard')
        assert b'admin-menu' not in response.data
    
    def test_impersonation_blocks_admin_pages(self, client, admin_user_session):
        """במצב Impersonation, עמודי אדמין חסומים."""
        client.post('/admin/impersonate/start')
        
        response = client.get('/admin/stats')
        assert response.status_code in (302, 403)  # redirect או forbidden
    
    def test_stop_impersonation_restores_admin(self, client, admin_user_session):
        """יציאה מ-Impersonation מחזירה הרשאות אדמין."""
        client.post('/admin/impersonate/start')
        client.post('/admin/impersonate/stop')
        
        response = client.get('/admin/stats')
        assert response.status_code == 200
    
    def test_force_admin_bypasses_impersonation(self, client, admin_user_session):
        """🆘 Fail-Safe: ?force_admin=1 עוקף את מצב Impersonation."""
        client.post('/admin/impersonate/start')
        
        # בלי force_admin - חסום
        response = client.get('/admin/stats')
        assert response.status_code in (302, 403)
        
        # עם force_admin - מותר
        response = client.get('/admin/stats?force_admin=1')
        assert response.status_code == 200
    
    def test_impersonation_does_not_modify_user_data(self, client, admin_user_session):
        """וידוא ש-session['user_data'] לא משתנה במצב Impersonation."""
        with client.session_transaction() as sess:
            original_user_data = dict(sess.get('user_data', {}))
        
        client.post('/admin/impersonate/start')
        
        with client.session_transaction() as sess:
            current_user_data = dict(sess.get('user_data', {}))
            # user_data לא אמור להשתנות - רק הדגל הנפרד
            assert current_user_data.get('is_admin') == original_user_data.get('is_admin')
    
    def test_context_processor_calculates_effective_status(self, client, admin_user_session):
        """בדיקה שה-Context Processor מחשב נכון את הסטטוס האפקטיבי."""
        # לפני Impersonation
        response = client.get('/dashboard')
        # בדוק שיש אלמנטי אדמין ב-HTML
        assert b'actual_is_admin' in response.data or b'admin-menu' in response.data
        
        # אחרי הפעלת Impersonation
        client.post('/admin/impersonate/start')
        response = client.get('/dashboard')
        # בדוק שאין אלמנטי אדמין ב-HTML (למעט כפתור היציאה)
        assert b'impersonation-banner' in response.data
