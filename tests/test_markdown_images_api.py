from bson import ObjectId

from webapp import app as webapp_app


class _StubMarkdownImages:
    def __init__(self, doc=None):
        self._doc = doc
        self.last_query = None

    def find_one(self, query):
        self.last_query = query
        return self._doc


class _StubDB:
    def __init__(self, doc=None):
        self.markdown_images = _StubMarkdownImages(doc)


def _build_image_doc(snippet_id, user_id, image_id, payload=b"hello", content_type="image/png"):
    return {
        "_id": image_id,
        "snippet_id": snippet_id,
        "user_id": user_id,
        "file_name": "preview.png",
        "content_type": content_type,
        "size": len(payload),
        "data": payload,
    }


def _prepare_client(monkeypatch, doc):
    stub_db = _StubDB(doc)
    monkeypatch.setattr(webapp_app, "get_db", lambda: stub_db)
    flask_app = webapp_app.app
    client = flask_app.test_client()
    with client.session_transaction() as sess:
        sess["user_id"] = 123
        sess["user_data"] = {"id": 123, "first_name": "Tester"}
    return client, stub_db


def test_markdown_image_served_when_exists(monkeypatch):
    snippet_id = ObjectId()
    image_id = ObjectId()
    payload = b"sample-bytes"
    client, stub_db = _prepare_client(
        monkeypatch,
        _build_image_doc(snippet_id, 123, image_id, payload=payload, content_type="image/webp"),
    )

    resp = client.get(f"/file/{snippet_id}/images/{image_id}")

    assert resp.status_code == 200
    assert resp.data == payload
    assert resp.headers.get("Content-Type") == "image/webp"
    assert stub_db.markdown_images.last_query == {
        "_id": image_id,
        "snippet_id": snippet_id,
        "user_id": 123,
    }


def test_markdown_image_returns_404_for_unknown(monkeypatch):
    snippet_id = ObjectId()
    image_id = ObjectId()
    client, _ = _prepare_client(monkeypatch, None)

    resp = client.get(f"/file/{snippet_id}/images/{image_id}")

    assert resp.status_code == 404


def test_markdown_image_rejects_invalid_ids(monkeypatch):
    client, _ = _prepare_client(monkeypatch, None)

    resp = client.get("/file/not-an-id/images/also-bad")

    assert resp.status_code == 404
