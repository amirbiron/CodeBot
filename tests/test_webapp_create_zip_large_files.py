from io import BytesIO
import zipfile

from bson import ObjectId
from webapp import app as webapp_app


class _StubCollection:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query, projection=None):
        ids = set((query.get("_id") or {}).get("$in", []) or [])
        uid = query.get("user_id")
        is_active = query.get("is_active")
        out = []
        for d in self.docs:
            if ids and d.get("_id") not in ids:
                continue
            if uid is not None and d.get("user_id") != uid:
                continue
            if is_active is not None and d.get("is_active") != is_active:
                continue
            item = dict(d)
            if projection:
                include = {k for k, v in projection.items() if v}
                if include:
                    if projection.get("_id", 1):
                        include.add("_id")
                    item = {k: item.get(k) for k in include if k in item}
            out.append(item)
        return out


class _StubDB:
    def __init__(self, regular_docs, large_docs):
        self.code_snippets = _StubCollection(regular_docs)
        self.large_files = _StubCollection(large_docs)


def test_create_zip_includes_large_files(monkeypatch):
    large_id = ObjectId("0123456789abcdef01234567")
    stub_db = _StubDB(
        regular_docs=[],
        large_docs=[
            {
                "_id": large_id,
                "user_id": 123,
                "is_active": True,
                "file_name": "big.txt",
                "content": "hello large file",
            }
        ],
    )
    monkeypatch.setattr(webapp_app, "get_db", lambda: stub_db)

    flask_app = webapp_app.app
    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 123
            sess["user_data"] = {"id": 123, "first_name": "Test"}

        resp = client.post("/api/files/create-zip", json={"file_ids": [str(large_id)]})
        assert resp.status_code == 200

        zip_bytes = resp.get_data()
        with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
            assert "big.txt" in zf.namelist()
            content = zf.read("big.txt").decode("utf-8")
            assert content == "hello large file"
