import importlib
import os


def _import_app():
    # ודא שהפיצ'רים האופציונליים לא חוסמים טעינת app בזמן טסטים
    os.environ.setdefault("COMMUNITY_LIBRARY_ENABLED", "1")
    os.environ.setdefault("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", "1")
    app_mod = importlib.import_module('webapp.app')
    app = app_mod.app
    app.testing = True
    return app


def test_compare_versions_unauthorized():
    app = _import_app()
    with app.test_client() as c:
        r = c.get('/api/compare/versions/123')
        assert r.status_code == 401


def test_compare_versions_not_found_authenticated():
    app = _import_app()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 123
        r = c.get('/api/compare/versions/nonexistent')
        assert r.status_code == 404


def test_compare_versions_success(monkeypatch):
    app = _import_app()

    # איפוס singleton כדי למנוע זליגת state בין טסטים
    import services.diff_service as diff_mod
    diff_mod._diff_service = None

    import database

    def _fake_get_file_by_id(file_id: str):
        return {
            "_id": file_id,
            "user_id": 123,
            "file_name": "test.py",
            "version": 2,
            "programming_language": "python",
            "code": "line1\nline2\nline3",
        }

    def _fake_get_version(user_id: int, file_name: str, version: int):
        if version == 1:
            return {"_id": "v1", "code": "line1\nline2", "updated_at": "2025-01-01"}
        if version == 2:
            return {"_id": "v2", "code": "line1\nline2\nline3", "updated_at": "2025-01-02"}
        return None

    monkeypatch.setattr(database.db, "get_file_by_id", _fake_get_file_by_id)
    monkeypatch.setattr(database.db, "get_version", _fake_get_version)

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 123
        r = c.get('/api/compare/versions/abc123?left=1&right=2')
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, dict)
        assert 'lines' in data
        assert 'stats' in data


def test_compare_files_success(monkeypatch):
    app = _import_app()

    import services.diff_service as diff_mod
    diff_mod._diff_service = None

    import database

    def _fake_get_file_by_id(file_id: str):
        if file_id == "left":
            return {"_id": "left", "user_id": 123, "file_name": "a.py", "programming_language": "python", "version": 1, "code": "a\nb\n"}
        if file_id == "right":
            return {"_id": "right", "user_id": 123, "file_name": "b.py", "programming_language": "python", "version": 1, "code": "a\nb\nc\n"}
        return None

    monkeypatch.setattr(database.db, "get_file_by_id", _fake_get_file_by_id)

    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 123
        r = c.post('/api/compare/files', json={"left_file_id": "left", "right_file_id": "right"})
        assert r.status_code == 200
        data = r.get_json()
        assert isinstance(data, dict)
        assert 'lines' in data
        assert 'stats' in data

