import pytest
import sys
from types import ModuleType, SimpleNamespace
from flask import Flask, request as flask_request, session as flask_session

try:
    import flask_login  # noqa: F401
except ModuleNotFoundError:
    flask_login_stub = ModuleType("flask_login")
    flask_login_stub.current_user = SimpleNamespace(is_authenticated=False)
    sys.modules["flask_login"] = flask_login_stub

from services.git_mirror_service import GitMirrorService
from webapp.routes import repo_browser


class _Cursor:
    def __init__(self, items):
        self._items = items

    def sort(self, *_args, **_kwargs):
        return self

    def __iter__(self):
        return iter(self._items)


class _RepoMetadata:
    def __init__(self, repos):
        self._repos = repos

    def find(self, *_args, **_kwargs):
        return _Cursor(self._repos)

    def find_one(self, query):
        repo_name = query.get("repo_name")
        for repo in self._repos:
            if repo.get("repo_name") == repo_name:
                return repo
        return None


class _RepoFiles:
    def find(self, *_args, **_kwargs):
        return _Cursor([])

    def distinct(self, *_args, **_kwargs):
        return []

    def aggregate(self, *_args, **_kwargs):
        return _Cursor([])

    def find_one(self, *_args, **_kwargs):
        return None


class _StubDB:
    def __init__(self):
        self.repo_metadata = _RepoMetadata([])
        self.repo_files = _RepoFiles()


# שם המפתח כפי שהוא ב-webapp/app.py — לא ערך מומצא לטסט
IMPERSONATION_SESSION_KEY = 'admin_impersonation_active'
ADMIN_USER_ID = 999
REGULAR_USER_ID = 123


@pytest.fixture
def app(tmp_path, monkeypatch) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    git_service = GitMirrorService(mirrors_base_path=str(tmp_path))
    app.extensions['git_mirror_service'] = git_service

    stub_db = _StubDB()
    monkeypatch.setattr(repo_browser, "get_db", lambda: stub_db)
    monkeypatch.setattr(repo_browser, "get_mirror_service", lambda: git_service)

    # דפדפן הקוד חסום לאדמינים; מזריקים webapp.app מדומה כדי לבדוק את
    # לוגיקת ההרשאה האמיתית בלי לגרור את אפליקציית ה-webapp המלאה
    webapp_app_stub = ModuleType("webapp.app")

    def _stub_is_admin(uid):
        return int(uid) == ADMIN_USER_ID

    def _stub_is_impersonating_safe():
        """העתק נאמן של ‎is_impersonating_safe‎ מ-webapp/app.py.

        מפתח הסשן וסדר הבדיקות זהים למקור בכוונה — כולל מסלול המילוט
        ‎?force_admin=1‎ וההגנה מפני דגל בסשן של מי שאינו אדמין. stub
        מפושט היה מאמת את עצמו במקום את המדיניות האמיתית.
        """
        if flask_request.args.get('force_admin') == '1':
            return False
        if not flask_session.get(IMPERSONATION_SESSION_KEY, False):
            return False
        uid = flask_session.get('user_id')
        if uid is None:
            return False
        try:
            if not _stub_is_admin(int(uid)):
                return False
        except Exception:
            return False
        return True

    webapp_app_stub.is_admin = _stub_is_admin
    webapp_app_stub.is_impersonating_safe = _stub_is_impersonating_safe
    monkeypatch.setitem(sys.modules, "webapp.app", webapp_app_stub)

    app.register_blueprint(repo_browser.repo_bp)
    return app


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['user_id'] = user_id


@pytest.fixture
def client(app: Flask):
    """לקוח מחובר כאדמין — ברירת המחדל לטסטים הפונקציונליים."""
    c = app.test_client()
    _login(c, ADMIN_USER_ID)
    return c


@pytest.fixture
def anon_client(app: Flask):
    """לקוח בלי סשן."""
    return app.test_client()


@pytest.fixture
def user_client(app: Flask):
    """לקוח מחובר כמשתמש רגיל (לא אדמין)."""
    c = app.test_client()
    _login(c, REGULAR_USER_ID)
    return c


class TestRepoBrowserIsAdminOnly:
    """דפדפן הקוד הוא כלי אדמין; אף אחד אחר לא אמור להגיע לשום route בו."""

    def test_anonymous_gets_403_on_page(self, anon_client):
        assert anon_client.get('/repo/').status_code == 403

    def test_anonymous_gets_json_403_on_api(self, anon_client):
        """חוזה ה-API לאנונימי: 403 עם admin_only, לא 401 ולא דף HTML."""
        response = anon_client.get('/repo/api/repos')
        assert response.status_code == 403
        assert response.get_json()['error'] == 'admin_only'

    def test_anonymous_cannot_select_repo(self, anon_client):
        """המסלול האנונימי של select-repo נעצר ב-guard לפני flask_login."""
        response = anon_client.post('/repo/api/select-repo',
                                    json={'repo_name': 'CodeBot'})
        assert response.status_code == 403
        assert response.get_json()['error'] == 'admin_only'

    def test_admin_while_impersonating_is_blocked(self, app):
        """במצב Impersonation האדמין גולש כמשתמש אחר — ולכן חסום."""
        c = app.test_client()
        with c.session_transaction() as sess:
            sess['user_id'] = ADMIN_USER_ID
            sess[IMPERSONATION_SESSION_KEY] = True
        assert c.get('/repo/api/repos').status_code == 403

    def test_force_admin_escape_hatch_works_while_impersonating(self, app):
        """‎?force_admin=1‎ הוא מסלול המילוט של המערכת — חייב לפתוח גם כאן."""
        c = app.test_client()
        with c.session_transaction() as sess:
            sess['user_id'] = ADMIN_USER_ID
            sess[IMPERSONATION_SESSION_KEY] = True
        assert c.get('/repo/api/repos?force_admin=1').status_code == 200

    def test_impersonation_flag_on_non_admin_does_not_grant_access(self, app):
        """דגל Impersonation מזויף בסשן של לא-אדמין לא פותח כלום."""
        c = app.test_client()
        with c.session_transaction() as sess:
            sess['user_id'] = REGULAR_USER_ID
            sess[IMPERSONATION_SESSION_KEY] = True
        assert c.get('/repo/api/repos').status_code == 403
        assert c.get('/repo/api/repos?force_admin=1').status_code == 403

    def test_regular_user_gets_403_on_page(self, user_client):
        assert user_client.get('/repo/').status_code == 403

    def test_regular_user_gets_json_403_on_api(self, user_client):
        response = user_client.get('/repo/api/repos')
        assert response.status_code == 403
        assert response.get_json()['error'] == 'admin_only'

    def test_regular_user_cannot_list_other_repos(self, user_client):
        """הדליפה המקורית: רשימת הריפויים של כולם דרך ה-API."""
        response = user_client.get('/repo/api/repos')
        assert response.status_code == 403
        assert 'repos' not in (response.get_json() or {})

    def test_regular_user_cannot_reach_repo_via_query_param(self, user_client):
        """גם מעבר ישיר לריפו לפי שם חסום, לא רק הרשימה."""
        assert user_client.get('/repo/api/tree?repo=CodeBot').status_code == 403

    def test_admin_passes_through(self, client):
        assert client.get('/repo/api/repos').status_code == 200

    def test_every_route_is_covered_by_the_blueprint_guard(self, app):
        """אף route ב-blueprint לא עוקף את הבדיקה — כולל כאלה שיתווספו."""
        guards = app.before_request_funcs.get('repo', [])
        assert repo_browser._require_admin_for_repo_browser in guards


class TestMultiRepoSupport:

    def test_api_list_repos(self, client):
        """בדיקה שה-API מחזיר רשימת ריפויים"""
        response = client.get('/repo/api/repos')
        assert response.status_code == 200
        data = response.get_json()
        assert data['success'] is True
        assert 'repos' in data
        assert isinstance(data['repos'], list)

    def test_tree_with_repo_param(self, client):
        """בדיקה שעץ הקבצים עובד עם פרמטר repo"""
        response = client.get('/repo/api/tree?repo=CodeBot')
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, list)

    def test_tree_invalid_repo(self, client):
        """בדיקה שריפו לא קיים מחזיר רשימה ריקה"""
        response = client.get('/repo/api/tree?repo=NonExistent')
        assert response.status_code == 200
        data = response.get_json()
        assert data == []  # אין קבצים לריפו שלא קיים

    def test_file_with_repo_param(self, client):
        """בדיקה שקריאת קובץ עובדת עם פרמטר repo"""
        response = client.get('/repo/api/file/README.md?repo=CodeBot')
        assert response.status_code in [200, 404]  # תלוי אם הקובץ קיים

    def test_select_repo_admin_without_flask_login_gets_401(self, client):
        """אדמין שעבר את ה-guard אך אינו מחובר ב-flask_login מקבל 401.

        השם מדויק בכוונה: מאז שדפדפן הקוד נחסם לאדמינים, ‎client‎ הוא אדמין,
        וה-401 כאן מגיע משכבת flask_login ולא מהיעדר סשן.
        """
        response = client.post('/repo/api/select-repo',
                               json={'repo_name': 'CodeBot'})
        assert response.status_code == 401
