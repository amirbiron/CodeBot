from services import community_library_service as cls


def test_get_item_by_id_returns_doc(monkeypatch):
    class DummyCollection:
        def __init__(self):
            self.last_query = None

        def find_one(self, query):
            self.last_query = query
            return {"_id": query["_id"], "title": "Demo"}

    dummy = DummyCollection()
    monkeypatch.setattr(cls, "_coll", lambda: dummy)

    doc = cls.get_item_by_id("507f1f77bcf86cd799439011")
    assert doc and doc["title"] == "Demo"
    assert dummy.last_query is not None


def test_get_item_by_id_handles_missing(monkeypatch):
    monkeypatch.setattr(cls, "_coll", lambda: None)
    assert cls.get_item_by_id("anything") is None
