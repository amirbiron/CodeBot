import types

import pytest

from webapp import app as webapp_app


class _StubUsers:
    def __init__(self):
        self.calls = []
        self._find_one_queue = []
        self._update_one_queue = []

    def queue_find_one(self, *values):
        self._find_one_queue.extend(values)

    def queue_update_one(self, *values):
        self._update_one_queue.extend(values)

    def find_one(self, *args, **kwargs):
        self.calls.append(("find_one", args, kwargs))
        if self._find_one_queue:
            return self._find_one_queue.pop(0)
        return {}

    def update_one(self, query, update, upsert=False, array_filters=None):
        self.calls.append(("update_one", query, update, upsert, array_filters))
        if self._update_one_queue:
            return self._update_one_queue.pop(0)
        return types.SimpleNamespace(acknowledged=True, modified_count=1)


class _StubDB:
    def __init__(self):
        self.users = _StubUsers()


def _login(client, user_id=42):
    with client.session_transaction() as sess:
        sess["user_id"] = int(user_id)
        sess["user_data"] = {"id": int(user_id), "first_name": "Tester"}


@pytest.fixture
def stub_db(monkeypatch):
    db = _StubDB()
    monkeypatch.setattr(webapp_app, "get_db", lambda: db)
    return db


@pytest.fixture
def client(stub_db):
    webapp_app.app.testing = True
    return webapp_app.app.test_client()


def test_get_themes_unauthorized(client):
    resp = client.get("/api/themes")
    assert resp.status_code == 401


def test_get_themes_empty_list(client, stub_db):
    _login(client)
    stub_db.users.queue_find_one({"custom_themes": []})

    resp = client.get("/api/themes")
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["themes"] == []
    assert data["count"] == 0
    assert data["max_allowed"] == 10


def test_get_themes_with_items(client, stub_db):
    _login(client)
    stub_db.users.queue_find_one(
        {
            "custom_themes": [
                {"id": "abc", "name": "Theme 1", "is_active": True},
                {"id": "def", "name": "Theme 2", "is_active": False},
            ]
        }
    )

    resp = client.get("/api/themes")
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["count"] == 2
    assert data["themes"][0]["name"] == "Theme 1"
    assert "variables" not in data["themes"][0]


def test_create_theme_max_limit(client, stub_db):
    _login(client)
    stub_db.users.queue_find_one({"custom_themes": [{"id": str(i)} for i in range(10)]})

    resp = client.post("/api/themes", json={"name": "New Theme", "variables": {}})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "max_themes_reached"


def test_create_theme_missing_name(client, stub_db):
    _login(client)
    stub_db.users.queue_find_one({"custom_themes": []})

    resp = client.post("/api/themes", json={"variables": {"--primary": "#ff0000"}})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "missing_name"


def test_create_theme_success(client, stub_db):
    _login(client)
    stub_db.users.queue_find_one({"custom_themes": []})
    stub_db.users.queue_update_one(types.SimpleNamespace(acknowledged=True, modified_count=1))

    resp = client.post(
        "/api/themes",
        json={"name": "My New Theme", "variables": {"--primary": "#667eea"}},
    )
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["ok"] is True
    assert "theme_id" in data
    assert isinstance(data["theme_id"], str)
    assert data["theme_id"]

    # verify $push custom_themes called
    update_calls = [c for c in stub_db.users.calls if c[0] == "update_one"]
    assert any("$push" in call[2] and "custom_themes" in call[2]["$push"] for call in update_calls)


def test_update_theme_not_found(client, stub_db):
    _login(client)
    stub_db.users.queue_find_one(None)

    resp = client.put("/api/themes/nonexistent", json={"name": "Updated Name"})
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "theme_not_found"


def test_update_theme_success(client, stub_db):
    _login(client)
    stub_db.users.queue_find_one({"custom_themes": [{"id": "abc", "name": "Old Name"}]})
    stub_db.users.queue_update_one(types.SimpleNamespace(acknowledged=True, modified_count=1))

    resp = client.put("/api/themes/abc", json={"name": "New Name"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_activate_theme_not_found(client, stub_db):
    _login(client)
    stub_db.users.queue_find_one(None)

    resp = client.post("/api/themes/nonexistent/activate")
    assert resp.status_code == 404
    assert resp.get_json()["error"] == "theme_not_found"


def test_activate_theme_success(client, stub_db):
    _login(client)
    stub_db.users.queue_find_one({"custom_themes": [{"id": "abc", "is_active": False}]})
    # activate_theme_simple does 2 update_one calls; second must have modified_count > 0
    stub_db.users.queue_update_one(
        types.SimpleNamespace(acknowledged=True, modified_count=1),
        types.SimpleNamespace(acknowledged=True, modified_count=1),
    )

    resp = client.post("/api/themes/abc/activate")
    assert resp.status_code == 200
    assert resp.get_json()["active_theme_id"] == "abc"


def test_delete_active_theme_resets_to_classic(client, stub_db):
    _login(client)
    stub_db.users.queue_find_one({"custom_themes": [{"id": "abc", "is_active": True}]})
    stub_db.users.queue_update_one(
        types.SimpleNamespace(acknowledged=True, modified_count=1),
        types.SimpleNamespace(acknowledged=True, modified_count=1),
    )

    resp = client.delete("/api/themes/abc")
    data = resp.get_json()

    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["was_active"] is True
    assert data["reset_to"] == "classic"

    update_calls = [c for c in stub_db.users.calls if c[0] == "update_one"]
    assert any(call[2].get("$set", {}).get("ui_prefs.theme") == "classic" for call in update_calls)
