import pytest

from webapp import app as webapp_app


@pytest.fixture
def client():
    flask_app = webapp_app.app
    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 42
        sess["user_data"] = {"id": 42, "first_name": "Tester"}
    return client


def test_live_preview_rejects_empty_payload(client):
    resp = client.post("/api/preview/live", json={"content": ""})
    assert resp.status_code == 400
    data = resp.get_json()
    assert data["error"] == "empty_content"


def test_live_preview_renders_markdown(client):
    payload = {
        "content": "# שלום\n\n**bold** _italic_",
        "language": "markdown",
    }
    resp = client.post("/api/preview/live", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    assert data["mode"] == "markdown"
    assert "<strong>" in data["html"]
    assert data["presentation"] == "fragment"
    assert data["meta"]["language"] == "markdown"
    assert data["meta"]["styles"]


def test_live_preview_sanitizes_html(client):
    payload = {
        "content": "<h2>כותרת</h2><script>alert(1)</script>",
        "language": "html",
    }
    resp = client.post("/api/preview/live", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["mode"] == "html"
    assert data["presentation"] == "iframe"
    assert "<script>" not in data["html"]


def test_live_preview_highlights_code(client):
    payload = {
        "content": "def hello():\n    return 'world'",
        "language": "python",
    }
    resp = client.post("/api/preview/live", json=payload)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["mode"] == "code"
    assert "codehilite" in data["html"]
    assert any("codehilite" in css for css in data["meta"].get("styles", []))


def test_live_preview_removes_dangerous_form_action(client):
    payload = {
        "content": '<form action="javascript:alert(1)"><button>send</button></form>',
        "language": "html",
    }
    resp = client.post("/api/preview/live", json=payload)
    assert resp.status_code == 200
    html = resp.get_json()["html"]
    assert "javascript:alert" not in html
    assert "action" not in html or 'action="' not in html


def test_live_preview_blocks_protocol_relative_urls(client):
    payload = {
        "content": "![tracker](//evil.example/track.png)",
        "language": "markdown",
    }
    resp = client.post("/api/preview/live", json=payload)
    assert resp.status_code == 200
    html = resp.get_json()["html"]
    assert "//evil.example" not in html
