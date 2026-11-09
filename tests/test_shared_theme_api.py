import types

import pytest

from webapp import app as webapp_app


class _StubSharedThemes:
    def __init__(self):
        self.docs = []
        self.calls = []

    class _Cursor:
        def __init__(self, docs):
            self._docs = list(docs or [])

        def sort(self, *_args, **_kwargs):
            return self

        def __iter__(self):
            return iter(self._docs)

    def find(self, query, projection=None):
        self.calls.append(("find", query, projection))
        out = []
        for doc in self.docs:
            if query.get("is_active") and not doc.get("is_active", False):
                continue
            out.append(doc)
        return self._Cursor(out)

    def find_one(self, query, projection=None):
        self.calls.append(("find_one", query, projection))
        for doc in self.docs:
            if doc.get("_id") != query.get("_id"):
                continue
            if query.get("is_active") and not doc.get("is_active", False):
                return None
            return doc
        return None

    def insert_one(self, doc):
        self.calls.append(("insert_one", doc))
        self.docs.append(doc)
        return types.SimpleNamespace(inserted_id=doc.get("_id"))

    def update_one(self, query, update, **kwargs):
        self.calls.append(("update_one", query, update, kwargs))
        return types.SimpleNamespace(acknowledged=True, modified_count=1)

    def delete_one(self, query):
        self.calls.append(("delete_one", query))
        for i, doc in enumerate(list(self.docs)):
            if doc.get("_id") == query.get("_id"):
                self.docs.pop(i)
                return types.SimpleNamespace(deleted_count=1)
        return types.SimpleNamespace(deleted_count=0)


class _StubUsers:
    def __init__(self):
        self.calls = []

    def find_one(self, _query, projection=None):
        self.calls.append(("find_one", _query, projection))
        return {"custom_themes": []}

    def update_one(self, query, update, upsert=False, **kwargs):
        self.calls.append(("update_one", query, update, upsert, kwargs))
        return types.SimpleNamespace(acknowledged=True, modified_count=1)


class _StubDB:
    def __init__(self):
        self.shared_themes = _StubSharedThemes()
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


def test_get_themes_list_unauthorized(client):
    resp = client.get("/api/themes/list")
    assert resp.status_code == 401


def test_get_themes_list_success(client, stub_db, monkeypatch):
    _login(client)
    # add one shared theme
    stub_db.shared_themes.docs = [{"_id": "cyber", "name": "Cyber", "is_active": True}]
    resp = client.get("/api/themes/list")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["count"] > 0
    assert any(t.get("type") == "shared" for t in data["themes"])


def test_publish_theme_not_admin(client, stub_db, monkeypatch):
    _login(client, user_id=999)
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: False)
    resp = client.post(
        "/api/themes/publish",
        json={"slug": "test_theme", "name": "Test Theme", "colors": {"--primary": "#667eea"}},
    )
    assert resp.status_code == 403
    assert resp.get_json()["error"] == "admin_required"


def test_publish_theme_success(client, stub_db, monkeypatch):
    _login(client, user_id=6865105071)
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: True)
    resp = client.post(
        "/api/themes/publish",
        json={
            "slug": "new_theme",
            "name": "New Theme",
            "colors": {"--primary": "#667eea", "--bg-primary": "#000000"},
            "syntax_css": ':root[data-theme="custom"] .tok-keyword { color: #ffffff; }',
        },
    )
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["ok"] is True
    assert data["theme_id"] == "new_theme"
    assert any(doc.get("_id") == "new_theme" for doc in stub_db.shared_themes.docs)
    doc = next(doc for doc in stub_db.shared_themes.docs if doc.get("_id") == "new_theme")
    assert 'data-theme-type="custom"' in str(doc.get("syntax_css") or "")


def test_apply_shared_theme_sets_ui_pref(client, stub_db, monkeypatch):
    _login(client, user_id=42)
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: False)
    stub_db.shared_themes.docs = [{"_id": "cyber", "name": "Cyber", "is_active": True, "colors": {"--primary": "#667eea"}}]

    resp = client.post("/api/themes/shared/cyber/apply")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["ok"] is True

    update_calls = [c for c in stub_db.users.calls if c[0] == "update_one"]
    assert any(call[2].get("$set", {}).get("ui_prefs.theme") == "shared:cyber" for call in update_calls)



# ============= syntax_css בפרסום =============


def _publish(client, monkeypatch, **extra):
    _login(client, user_id=6865105071)
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: True)
    body = {"slug": "morass", "name": "morass", "colors": {"--primary": "#fdec5a"}, **extra}
    return client.post("/api/themes/publish", json=body)


def test_publish_reports_how_many_syntax_rules_did_not_pass(client, stub_db, monkeypatch):
    resp = _publish(
        client,
        monkeypatch,
        syntax_css=(
            ':root[data-theme-type="custom"] .hljs-string { color: #ce9178 !important; }\n'
            ':root[data-theme-type="custom"] .source .k { color: #c586c0 !important; }'
        ),
    )
    data = resp.get_json()
    assert resp.status_code == 200, data
    assert data["syntax_rules_dropped"] == 1
    doc = next(doc for doc in stub_db.shared_themes.docs if doc.get("_id") == "morass")
    assert (
        doc["syntax_css"]
        == ':root[data-theme-type="custom"] .hljs-string { color: #ce9178 !important; }'
    )


def test_publish_with_syntax_css_that_is_not_a_string_is_a_400(client, stub_db, monkeypatch):
    resp = _publish(client, monkeypatch, syntax_css=["x"])
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_syntax_css"
    assert stub_db.shared_themes.docs == []


def test_publish_with_syntax_css_over_the_ceiling_is_a_400_with_max(client, stub_db, monkeypatch):
    from services.shared_theme_service import MAX_SYNTAX_CSS_LENGTH

    resp = _publish(client, monkeypatch, syntax_css="a" * (MAX_SYNTAX_CSS_LENGTH + 1))
    data = resp.get_json()
    assert resp.status_code == 400
    assert data["error"] == "syntax_css_too_long"
    assert data["max"] == MAX_SYNTAX_CSS_LENGTH
    assert stub_db.shared_themes.docs == []


def test_update_shared_theme_with_syntax_css_that_is_not_a_string_is_a_400(
    client, stub_db, monkeypatch
):
    _login(client, user_id=6865105071)
    monkeypatch.setattr(webapp_app, "is_admin", lambda *_: True)
    stub_db.shared_themes.docs = [
        {"_id": "morass", "name": "morass", "is_active": True, "syntax_css": "kept"}
    ]
    resp = client.put("/api/themes/shared/morass", json={"syntax_css": 7})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_syntax_css"
    assert not any(call[0] == "update_one" for call in stub_db.shared_themes.calls)


def test_publish_keeps_the_json_colors_of_the_personal_theme(client, stub_db, monkeypatch):
    """הבאג שהתגלה: בלוק JSON ב-Markdown בערכה הציבורית איבד את התכלת של המפתחות ואת החום של המחרוזות."""
    from services.styled_export_service import _MORASS_TOKEN_COLORS
    from services.theme_parser_service import parse_vscode_theme

    personal = parse_vscode_theme(
        {
            "name": "morass",
            "colors": {
                "editor.background": "#313a36",
                "editor.foreground": "#e4e3e1",
                "sideBar.background": "#485650",
            },
            "tokenColors": _MORASS_TOKEN_COLORS,
        }
    )["syntax_css"]
    resp = _publish(client, monkeypatch, syntax_css=personal)
    assert resp.status_code == 200, resp.get_json()
    saved = next(doc for doc in stub_db.shared_themes.docs if doc.get("_id") == "morass")[
        "syntax_css"
    ]
    assert ':root[data-theme-type="custom"] .hljs-attr { color: #9cdcfe !important; }' in saved
    assert ':root[data-theme-type="custom"] .hljs-string { color: #ce9178 !important; }' in saved
