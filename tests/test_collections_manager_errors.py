from types import SimpleNamespace
import pytest

from database.collections_manager import CollectionsManager, ObjectId


class StubColl:
    def __init__(self):
        self.docs = []
    def create_indexes(self, *a, **k):
        return None
    def insert_one(self, doc):
        if "_id" not in doc:
            doc["_id"] = f"oid{len(self.docs)+1}"
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc["_id"])
    def find_one_and_update(self, *a, **k):
        return None
    def update_one(self, *a, **k):
        return SimpleNamespace(modified_count=0)
    def find_one(self, flt):
        # Simulate exception path for one test when flag set
        raise RuntimeError("db error")
    def find(self, *a, **k):
        return []
    def count_documents(self, *a, **k):
        return 0


class ItemsColl:
    def __init__(self):
        self.docs = []
    def create_indexes(self, *a, **k):
        return None
    def delete_one(self, *a, **k):
        return SimpleNamespace(deleted_count=0)
    def update_one(self, *a, **k):
        return SimpleNamespace(matched_count=0, modified_count=0)
    def aggregate(self, *a, **k):
        raise RuntimeError("agg error")


class DBErr:
    def __init__(self):
        self.user_collections = StubColl()
        self.collection_items = ItemsColl()
        self.code_snippets = SimpleNamespace(aggregate=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("agg")))


@pytest.fixture()
def mgr_err() -> CollectionsManager:
    return CollectionsManager(DBErr())


def test_get_collection_exception_path(mgr_err: CollectionsManager):
    out = mgr_err.get_collection(1, str(ObjectId()))
    assert not out["ok"]


def test_list_collections_error_path(monkeypatch, mgr_err: CollectionsManager):
    # monkeypatch find to raise inside list_collections
    monkeypatch.setattr(mgr_err.collections, 'find', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('x')))
    res = mgr_err.list_collections(1, limit='x', skip=0)  # force params except path too
    assert not res["ok"] and res["collections"] == []


def test_update_collection_not_found_and_exception(monkeypatch, mgr_err: CollectionsManager):
    # not found (find_one_and_update returns None by default)
    c = mgr_err.update_collection(1, str(ObjectId()), name="A")
    assert not c["ok"]
    # exception path
    def boom(*a, **k):
        raise RuntimeError('fail')
    monkeypatch.setattr(mgr_err.collections, 'find_one_and_update', boom)
    c2 = mgr_err.update_collection(1, str(ObjectId()), name="B")
    assert not c2["ok"]


def test_delete_collection_exception(monkeypatch, mgr_err: CollectionsManager):
    monkeypatch.setattr(mgr_err.collections, 'update_one', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('z')))
    out = mgr_err.delete_collection(1, str(ObjectId()))
    assert not out["ok"]


def test_add_items_aggregate_exception(monkeypatch, mgr_err: CollectionsManager):
    # valid collection doc first to allow update counts (update_one should no-op)
    cid = str(ObjectId())
    # add returns ok even if aggregate fails
    out = mgr_err.add_items(2, cid, [{"source":"regular", "file_name":"a.py"}])
    assert out["ok"]


def test_remove_items_aggregate_exception(monkeypatch, mgr_err: CollectionsManager):
    cid = str(ObjectId())
    out = mgr_err.remove_items(2, cid, [{"source":"regular", "file_name":"a.py"}])
    assert out["ok"]


def test_reorder_items_update_errors(monkeypatch, mgr_err: CollectionsManager):
    cid = str(ObjectId())
    # update_one raises -> handled and continue, updated stays 0
    monkeypatch.setattr(mgr_err.items, 'update_one', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('u')))
    out = mgr_err.reorder_items(3, cid, [{"source":"regular","file_name":"x.py"}])
    assert out["ok"] and out["updated"] == 0


def test_compute_smart_items_exceptions(monkeypatch, mgr_err: CollectionsManager):
    # code_snippets.aggregate already raises; should return []
    res = mgr_err.compute_smart_items(4, {"query":"x"}, limit=5)
    assert res == []
    # None -> []
    mgr_err.code_snippets = None
    res2 = mgr_err.compute_smart_items(4, {}, limit=5)
    assert res2 == []
