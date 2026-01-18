import pytest
from unittest.mock import MagicMock

from webapp import app as webapp_app


class _StubDB:
    def __init__(self, snippet=None, pinned_docs=None):
        self.code_snippets = MagicMock()
        self.code_snippets.find_one.return_value = snippet
        self.code_snippets.count_documents.return_value = 0
        self.code_snippets.find.return_value.sort.return_value.limit.return_value = pinned_docs or []
        self.code_snippets.aggregate.return_value = pinned_docs or []


def _login(client, user_id=42):
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["user_data"] = {"id": int(user_id), "first_name": "Tester"}


@pytest.fixture
def client(monkeypatch):
    webapp_app.app.testing = True
    return webapp_app.app.test_client()


def test_api_toggle_pin_unauthorized(client):
    resp = client.post("/api/pin/toggle/507f1f77bcf86cd799439011")
    assert resp.status_code == 401
    data = resp.get_json()
    assert data.get("error") == "נדרש להתחבר"


def test_api_toggle_pin_success(client, monkeypatch):
    snippet = {"_id": "507f1f77bcf86cd799439011", "file_name": "test.py", "is_pinned": False, "is_active": True}
    stub_db = _StubDB(snippet=snippet)
    stub_db.code_snippets.find_one.side_effect = [snippet, snippet, None]
    stub_db.code_snippets.aggregate.side_effect = [[{"count": 0}], [{"count": 1}]]
    monkeypatch.setattr(webapp_app, "get_db", lambda: stub_db)
    _login(client, user_id=123)

    resp = client.post("/api/pin/toggle/507f1f77bcf86cd799439011")
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["is_pinned"] is True


def test_api_get_pinned_files_success(client, monkeypatch):
    pinned_docs = [
        {"_id": "p1", "file_name": "alpha.py", "programming_language": "python", "tags": [], "description": "", "lines_count": 3},
        {"_id": "p2", "file_name": "beta.js", "programming_language": "javascript", "tags": ["ui"], "description": "note", "lines_count": 10},
    ]
    stub_db = _StubDB(snippet=None, pinned_docs=pinned_docs)
    monkeypatch.setattr(webapp_app, "get_db", lambda: stub_db)
    _login(client, user_id=123)

    resp = client.get("/api/pinned")
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["count"] == 2
    assert len(data["files"]) == 2
