import types

import pytest

from webapp import app as webapp_app


class _StubUsers:
    def __init__(self):
        self.calls = []

    def update_one(self, query, update, upsert=False):
        self.calls.append((query, update, upsert))
        return types.SimpleNamespace(acknowledged=True)

    def find_one(self, *args, **kwargs):
        return {}


class _StubDB:
    def __init__(self):
        self.users = _StubUsers()


def _login(client, user_id=42):
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["user_data"] = {"id": int(user_id), "first_name": "Tester"}


@pytest.fixture
def client(monkeypatch):
    stub_db = _StubDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: stub_db)
    webapp_app.app.testing = True
    return webapp_app.app.test_client()


def test_save_custom_theme_unauthorized(client):
    resp = client.post("/api/themes/save", json={"name": "Test"})
    assert resp.status_code == 401


def test_save_custom_theme_admin_only(client, monkeypatch):
    _login(client)
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: False)
    resp = client.post("/api/themes/save", json={"name": "Test"})
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "admin_only"


def test_save_custom_theme_missing_name(client, monkeypatch):
    _login(client)
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: True)
    resp = client.post("/api/themes/save", json={})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "missing_name"


def test_save_custom_theme_invalid_color(client, monkeypatch):
    _login(client)
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: True)
    resp = client.post(
        "/api/themes/save",
        json={
            "name": "Test",
            "variables": {"--bg-primary": "not-a-color"},
        },
    )
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["error"] == "invalid_color"
    assert payload["field"] == "--bg-primary"


def test_save_custom_theme_success_sets_custom_theme_and_ui_prefs(client, monkeypatch):
    _login(client)
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: True)

    stub_db = webapp_app.get_db()

    resp = client.post(
        "/api/themes/save",
        json={
            "name": "My Theme",
            "variables": {
                "--bg-primary": "#123456",
                "--primary": "rgba(100, 100, 100, 0.50)",
                "--glass-blur": "20px",
                "--ignored": "#ffffff",
            },
        },
    )

    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True

    # First update should set custom_theme
    assert stub_db.users.calls, "expected at least one update_one call"
    first = stub_db.users.calls[0]
    assert first[0] == {"user_id": 42}
    assert "$set" in first[1]
    assert "custom_theme" in first[1]["$set"]

    # Second update should set ui_prefs.theme = custom
    assert any(
        call[1].get("$set", {}).get("ui_prefs.theme") == "custom" for call in stub_db.users.calls
    )


def test_delete_custom_theme_resets_to_classic(client, monkeypatch):
    _login(client)
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: True)

    stub_db = webapp_app.get_db()

    resp = client.delete("/api/themes/custom")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["reset_to"] == "classic"

    assert stub_db.users.calls, "expected update_one call"
    query, update, _upsert = stub_db.users.calls[-1]
    assert query == {"user_id": 42}
    assert update.get("$set", {}).get("ui_prefs.theme") == "classic"
    assert "$unset" in update
