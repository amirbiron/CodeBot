"""
Tests for JSON Formatter API
============================
"""

import pytest
from flask import Flask

from webapp.json_formatter_api import json_formatter_bp


@pytest.fixture
def app() -> Flask:
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    app.register_blueprint(json_formatter_bp)
    return app


@pytest.fixture
def client(app: Flask):
    with app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 1
        yield client


@pytest.fixture
def client_no_auth(app: Flask):
    return app.test_client()


class TestAuth:
    def test_requires_login(self, client_no_auth) -> None:
        resp = client_no_auth.post("/api/json/validate", json={"content": "{}"})
        assert resp.status_code == 401
        data = resp.get_json()
        assert data["success"] is False


class TestFormatEndpoint:
    def test_format_success(self, client) -> None:
        resp = client.post("/api/json/format", json={"content": '{"a":1}'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert '"a": 1' in data["result"]
        assert "stats" in data

    def test_format_invalid_json(self, client) -> None:
        resp = client.post("/api/json/format", json={"content": "not json"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False
        assert "line" in data

    def test_format_missing_content(self, client) -> None:
        resp = client.post("/api/json/format", json={})
        assert resp.status_code == 400


class TestValidateEndpoint:
    def test_validate_valid(self, client) -> None:
        resp = client.post("/api/json/validate", json={"content": '{"valid": true}'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["is_valid"] is True
        assert "stats" in data

    def test_validate_invalid(self, client) -> None:
        resp = client.post("/api/json/validate", json={"content": "{invalid}"})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["is_valid"] is False
        assert "error" in data
        assert "line" in data
        assert "column" in data


class TestMinifyEndpoint:
    def test_minify_success(self, client) -> None:
        resp = client.post("/api/json/minify", json={"content": '{\n  "a": 1\n}'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert " " not in data["result"]
        assert "savings_percent" in data


class TestFixEndpoint:
    def test_fix_success(self, client) -> None:
        resp = client.post("/api/json/fix", json={"content": '{"a": 1,}'})
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["success"] is True
        assert data["result"]
        assert "fixes_applied" in data

    def test_fix_failure(self, client) -> None:
        resp = client.post("/api/json/fix", json={"content": "{not even close"})
        assert resp.status_code == 400
        data = resp.get_json()
        assert data["success"] is False

