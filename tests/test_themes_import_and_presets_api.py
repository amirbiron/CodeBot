import io
import json
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


class TestPresetsAPI:
    def test_list_presets(self, client):
        _login(client)
        resp = client.get("/api/themes/presets")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert "presets" in data
        assert len(data["presets"]) > 0
        preset = data["presets"][0]
        assert "id" in preset
        assert "name" in preset
        assert "category" in preset

    def test_get_preset_details(self, client):
        _login(client)
        resp = client.get("/api/themes/presets/dracula")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Dracula"
        assert "variables" in data

    def test_apply_preset(self, client, stub_db):
        _login(client)
        stub_db.users.queue_find_one({"custom_themes": []})
        resp = client.post("/api/themes/presets/github-light/apply")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["theme"]["name"] == "GitHub Light"

        update_calls = [c for c in stub_db.users.calls if c[0] == "update_one"]
        assert any("$push" in call[2] and "custom_themes" in call[2]["$push"] for call in update_calls)


class TestImportAPI:
    def test_import_vscode_theme_json(self, client, stub_db):
        _login(client)
        stub_db.users.queue_find_one({"custom_themes": []})

        vscode_theme = {
            "name": "Test",
            "type": "dark",
            "colors": {
                "editor.background": "#282a36",
                "editor.foreground": "#f8f8f2",
                "button.background": "#bd93f9",
            },
            "tokenColors": [
                {"scope": ["comment"], "settings": {"foreground": "#6272a4", "fontStyle": "italic"}},
            ],
        }

        resp = client.post("/api/themes/import", json={"json_content": json.dumps(vscode_theme)})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["theme"]["source"] == "vscode"

        update_calls = [c for c in stub_db.users.calls if c[0] == "update_one"]
        assert update_calls, "expected update_one calls"
        pushed = None
        for call in update_calls:
            upd = call[2]
            if "$push" in upd and "custom_themes" in upd["$push"]:
                pushed = upd["$push"]["custom_themes"]
                break
        assert pushed is not None
        assert "syntax_css" in pushed
        assert ".cm-comment" in (pushed.get("syntax_css") or "")

    def test_import_rejects_invalid_json(self, client, stub_db):
        _login(client)
        stub_db.users.queue_find_one({"custom_themes": []})

        resp = client.post("/api/themes/import", json={"json_content": "not valid json {"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "JSON" in data["error"]

    def test_import_file_upload(self, client, stub_db):
        _login(client)
        stub_db.users.queue_find_one({"custom_themes": []})

        payload = {
            "name": "File Theme",
            "type": "dark",
            "colors": {
                "editor.background": "#000000",
                "editor.foreground": "#ffffff",
                "button.background": "#ff00ff",
            },
        }
        f = io.BytesIO(json.dumps(payload).encode("utf-8"))
        resp = client.post(
            "/api/themes/import",
            data={"file": (f, "theme.json")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True


class TestExportAPI:
    def test_export_sanitizes_filename_control_chars(self, client, stub_db):
        _login(client)
        theme_id = "t-1"
        stub_db.users.queue_find_one(
            {
                "custom_themes": [
                    {
                        "id": theme_id,
                        "name": "evil\r\nname",
                        "description": "",
                        "is_active": False,
                        "variables": {"--bg-primary": "#000000", "--text-primary": "#ffffff"},
                        "syntax_css": "",
                    }
                ]
            }
        )
        resp = client.get(f"/api/themes/{theme_id}/export")
        assert resp.status_code == 200
        cd = resp.headers.get("Content-Disposition") or ""
        assert "\n" not in cd and "\r" not in cd
        assert cd.startswith("attachment;")
        assert cd.endswith('.json"')

