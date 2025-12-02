import pytest

from webapp import app as webapp_app


class _StubInsertResult:
    def __init__(self, inserted_id="507f1f77bcf86cd799439011"):
        self.inserted_id = inserted_id


class _StubCodeSnippets:
    def __init__(self, languages=None):
        self._languages = languages or []
        self.last_inserted = None

    def distinct(self, field, query):
        return list(self._languages)

    def find_one(self, *args, **kwargs):
        return None

    def insert_one(self, doc):
        self.last_inserted = doc
        return _StubInsertResult()


class _StubDB:
    def __init__(self, languages=None):
        self.code_snippets = _StubCodeSnippets(languages or [])


def _login(client):
    with client.session_transaction() as sess:
        sess["user_id"] = 42
        sess["user_data"] = {"id": 42, "first_name": "Tester"}


def test_upload_get_marks_reset_flag(monkeypatch):
    stub_db = _StubDB([])
    monkeypatch.setattr(webapp_app, "get_db", lambda: stub_db)

    flask_app = webapp_app.app
    flag_key = webapp_app._UPLOAD_CLEAR_DRAFT_SESSION_KEY

    with flask_app.test_client() as client:
        _login(client)
        with client.session_transaction() as sess:
            sess[flag_key] = True

        resp = client.get("/upload")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'data-reset-draft="1"' in html

        with client.session_transaction() as sess:
            assert flag_key not in sess


def test_successful_upload_sets_session_flag(monkeypatch):
    stub_db = _StubDB([])
    monkeypatch.setattr(webapp_app, "get_db", lambda: stub_db)
    monkeypatch.setattr(webapp_app, "_log_webapp_user_activity", lambda: False)

    flask_app = webapp_app.app
    flag_key = webapp_app._UPLOAD_CLEAR_DRAFT_SESSION_KEY

    with flask_app.test_client() as client:
        _login(client)
        resp = client.post(
            "/upload",
            data={
                "file_name": "example.py",
                "code": "print('hi')",
                "language": "python",
                "description": "",
                "tags": "",
                "source_url": "",
                "source_url_touched": "0",
            },
        )
        assert resp.status_code == 302

        with client.session_transaction() as sess:
            assert sess.get(flag_key) is True
