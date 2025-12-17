import types


from bson import ObjectId
from webapp import app as webapp_app


class _StubCollection:
    def __init__(self, docs):
        self.docs = list(docs)

    def find(self, query, projection=None):
        uid = query.get("user_id")
        active = query.get("is_active")
        out = []
        for d in self.docs:
            if d.get("user_id") == uid and d.get("is_active") == active:
                out.append(dict(d))
        return out

    def update_many(self, flt, upd):
        modified = 0
        for d in self.docs:
            if d.get("_id") != flt.get("_id"):
                continue
            if d.get("user_id") != flt.get("user_id"):
                continue
            if d.get("is_active") != flt.get("is_active"):
                continue
            for k, v in (upd.get("$set") or {}).items():
                d[k] = v
            for k in (upd.get("$unset") or {}).keys():
                d.pop(k, None)
            modified += 1
        return types.SimpleNamespace(modified_count=modified)

    def delete_many(self, flt):
        before = len(self.docs)
        self.docs = [
            d for d in self.docs
            if not (d.get("_id") == flt.get("_id") and d.get("user_id") == flt.get("user_id") and d.get("is_active") == flt.get("is_active"))
        ]
        return types.SimpleNamespace(deleted_count=(before - len(self.docs)))


class _StubDB:
    def __init__(self, docs):
        self.code_snippets = _StubCollection(docs)


def _stub_cache():
    class _Cache:
        def invalidate_user_cache(self, *a, **k):
            return 0
        def delete_pattern(self, *a, **k):
            return 0
    return _Cache()


def test_trash_page_lists_items_and_restore_purge(monkeypatch):
    file_oid = ObjectId("0123456789abcdef01234567")
    stub_db = _StubDB([
        {
            "_id": file_oid,
            "user_id": 123,
            "file_name": "deleted.py",
            "programming_language": "python",
            "is_active": False,
        }
    ])
    monkeypatch.setattr(webapp_app, "get_db", lambda: stub_db)
    monkeypatch.setattr(webapp_app, "cache", _stub_cache())

    flask_app = webapp_app.app
    with flask_app.test_client() as client:
        with client.session_transaction() as sess:
            sess["user_id"] = 123
            sess["user_data"] = {"id": 123, "first_name": "Test"}

        resp = client.get("/trash")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "סל מחזור" in html
        assert "deleted.py" in html

        # Restore
        resp2 = client.post(f"/api/trash/{str(file_oid)}/restore", json={})
        assert resp2.status_code == 200
        payload = resp2.get_json()
        assert payload and payload.get("ok") is True

        # After restore it should disappear from list (no longer is_active=False)
        resp3 = client.get("/trash")
        assert resp3.status_code == 200
        assert "deleted.py" not in resp3.get_data(as_text=True)

        # Put it back into trash and purge
        stub_db.code_snippets.docs.append({
            "_id": file_oid,
            "user_id": 123,
            "file_name": "deleted.py",
            "programming_language": "python",
            "is_active": False,
        })
        resp4 = client.post(f"/api/trash/{str(file_oid)}/purge", json={})
        assert resp4.status_code == 200
        payload2 = resp4.get_json()
        assert payload2 and payload2.get("ok") is True

        resp5 = client.get("/trash")
        assert resp5.status_code == 200
        assert "deleted.py" not in resp5.get_data(as_text=True)

