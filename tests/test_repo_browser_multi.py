import pytest
import sys
from types import ModuleType, SimpleNamespace
from flask import Flask

from services.git_mirror_service import GitMirrorService
from webapp.routes import repo_browser


if "flask_login" not in sys.modules:
    flask_login_stub = ModuleType("flask_login")
    flask_login_stub.current_user = SimpleNamespace(is_authenticated=False)
    sys.modules["flask_login"] = flask_login_stub


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


@pytest.fixture
def app(tmp_path, monkeypatch) -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    app.extensions['git_mirror_service'] = GitMirrorService(mirrors_base_path=str(tmp_path))

    stub_db = _StubDB()
    monkeypatch.setattr(repo_browser, "get_db", lambda: stub_db)
    app.register_blueprint(repo_browser.repo_bp)
    return app


@pytest.fixture
def client(app: Flask):
    return app.test_client()


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

    def test_select_repo_unauthenticated(self, client):
        """בדיקה שבחירת ריפו דורשת אותנטיקציה"""
        response = client.post('/repo/api/select-repo',
                               json={'repo_name': 'CodeBot'})
        assert response.status_code == 401
