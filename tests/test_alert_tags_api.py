import importlib


def _build_app():
    app_mod = importlib.import_module("webapp.app")
    app = app_mod.app
    app.testing = True
    return app


def test_alert_tags_endpoints_require_admin(monkeypatch):
    monkeypatch.setenv("ADMIN_USER_IDS", "10")
    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 99
        resp = client.get("/api/observability/alerts/u1/tags")
        assert resp.status_code == 403
        assert resp.get_json()["error"] == "admin_only"


def test_suggest_tags_endpoint_returns_payload(monkeypatch):
    admin_id = 7
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin_id))

    def _fake_suggest(prefix, limit):
        assert prefix == "bug"
        assert limit == 15
        return {"ok": True, "suggestions": ["bug", "bugfix"]}

    monkeypatch.setattr("webapp.app.observability_service.suggest_tags", _fake_suggest)

    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = admin_id
        resp = client.get("/api/observability/tags/suggest?q=bug&limit=15")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True
        assert data["suggestions"] == ["bug", "bugfix"]


def test_set_global_tags_endpoint_calls_service(monkeypatch):
    admin_id = 5
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin_id))
    captured = {}

    def _fake_set_global(*, alert_name, tags, user_id):
        captured["alert_name"] = alert_name
        captured["tags"] = tags
        captured["user_id"] = user_id
        return {"ok": True, "alert_type_name": alert_name, "tags": tags}

    monkeypatch.setattr("webapp.app.observability_service.set_global_alert_tags", _fake_set_global)

    app = _build_app()
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = admin_id
        resp = client.post(
            "/api/observability/alerts/global-tags",
            json={"alert_name": "CPU High", "tags": ["infra"]},
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["ok"] is True

    assert captured["alert_name"] == "CPU High"
    assert captured["tags"] == ["infra"]
    assert captured["user_id"] == admin_id

