from datetime import datetime, timezone
from types import SimpleNamespace
import typing as t

import pytest

from database.collections_manager import CollectionsManager, ObjectId


class FakeUpdateResult:
    def __init__(self, matched=0, modified=0, deleted=0, inserted_id=None):
        self.matched_count = matched
        self.modified_count = modified
        self.deleted_count = deleted
        self.inserted_id = inserted_id
        self.acknowledged = True


class FakeCollection:
    def __init__(self):
        self.docs: list[dict] = []

    # Index API
    def create_indexes(self, *a, **k):
        return None

    # CRUD helpers
    def insert_one(self, doc: dict):
        if "_id" not in doc or not doc["_id"]:
            # simple ObjectId-like
            doc["_id"] = f"oid{len(self.docs)+1}"
        self.docs.append(dict(doc))
        return FakeUpdateResult(inserted_id=doc["_id"])

    def find_one(self, flt: dict, proj: dict | None = None):
        for d in self.docs:
            if _match(d, flt):
                return dict(d)
        return None

    def update_one(self, flt: dict, upd: dict, **kwargs):
        modified = 0
        for d in self.docs:
            if _match(d, flt):
                _apply_update(d, upd)
                modified += 1
                break
        return FakeUpdateResult(modified=modified)

    def update_many(self, flt: dict, upd: dict, **kwargs):
        modified = 0
        for d in self.docs:
            if _match(d, flt):
                _apply_update(d, upd)
                modified += 1
        return FakeUpdateResult(modified=modified)

    def delete_one(self, flt: dict):
        deleted = 0
        for i, d in enumerate(list(self.docs)):
            if _match(d, flt):
                self.docs.pop(i)
                deleted += 1
                break
        return FakeUpdateResult(deleted=deleted)

    def delete_many(self, flt: dict):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _match(d, flt)]
        return FakeUpdateResult(deleted=(before - len(self.docs)))

    def count_documents(self, flt: dict):
        return sum(1 for d in self.docs if _match(d, flt))

    # find may return list directly — CollectionsManager handles both list/cursor
    def find(self, flt: dict):
        return [dict(d) for d in self.docs if _match(d, flt)]

    def find_one_and_update(self, flt: dict, upd: dict, return_document: bool = True):
        doc = self.find_one(flt)
        if not doc:
            return None
        # update original in self.docs
        for d in self.docs:
            if d.get("_id") == doc.get("_id"):
                _apply_update(d, upd)
                doc = dict(d)
                break
        return doc

    # Minimal aggregate used for items_count/pinned_count
    def aggregate(self, pipeline: list[dict], allowDiskUse: bool = False):
        # Support pattern used in add_items/remove_items: match by collection_id then group counts
        docs = self.docs
        for stage in pipeline:
            if "$match" in stage:
                flt = stage["$match"]
                docs = [d for d in docs if _match(d, flt)]
            elif "$group" in stage:
                # Only support shape: {"_id": None, "cnt": {"$sum": 1}, "pinned": {"$sum": {"$cond": ["$pinned", 1, 0]}}}
                cnt = len(docs)
                pinned = sum(1 for d in docs if bool(d.get("pinned")))
                return [{"_id": None, "cnt": cnt, "pinned": pinned}]
        return []


class FakeDB:
    def __init__(self):
        self.user_collections = FakeCollection()
        self.collection_items = FakeCollection()
        self.code_snippets = FakeCollection()


def _match(doc: dict, flt: dict) -> bool:
    # Minimal matcher supporting nested $or and simple equality
    def m(d, f):
        for k, v in f.items():
            if k == "$or":
                if not any(m(d, cond) for cond in v):
                    return False
            elif isinstance(v, dict) and "$in" in v:
                if d.get(k) not in v["$in"]:
                    return False
            else:
                if str(d.get(k)) != str(v):
                    return False
        return True
    return m(doc, flt)


def _apply_update(doc: dict, upd: dict) -> None:
    if "$set" in upd:
        for k, v in upd["$set"].items():
            doc[k] = v
    if "$unset" in upd:
        for k in upd["$unset"].keys():
            if k in doc:
                del doc[k]


@pytest.fixture()
def mgr() -> CollectionsManager:
    return CollectionsManager(FakeDB())


def test_create_update_delete_list_get_collection(mgr: CollectionsManager):
    # create
    res = mgr.create_collection(user_id=1, name="Favorites", description="desc", mode="manual")
    assert res["ok"]
    cid = res["collection"]["id"]

    # update name (slug recalculation happens; not exposed but accepted)
    res2 = mgr.update_collection(1, cid, name="New Name", is_favorite=True)
    assert res2["ok"] and res2["collection"]["name"] == "New Name"

    # list
    lst = mgr.list_collections(1, limit=10, skip=0)
    assert lst["ok"] and lst["count"] == 1 and len(lst["collections"]) == 1

    # get
    got = mgr.get_collection(1, cid)
    assert got["ok"] and got["collection"]["id"] == cid

    # delete (soft)
    dl = mgr.delete_collection(1, cid)
    assert dl["ok"]


def test_limits_enforced(mgr: CollectionsManager):
    # 100 collections limit
    for i in range(100):
        ok = mgr.create_collection(1, f"C{i}")
        assert ok["ok"], f"failed at {i}"
    over = mgr.create_collection(1, "overflow")
    assert not over["ok"] and "100" in over["error"]

    # items limit 5000
    # Seed user items to 5000
    for i in range(5000):
        mgr.items.insert_one({"_id": f"it{i}", "user_id": 1, "collection_id": ObjectId("cccccccccccccccccccccccc"), "file_name": f"f{i}.py"})
    col = mgr.create_collection(2, "HasItems")["collection"]
    add = mgr.add_items(2, col["id"], [{"source": "regular", "file_name": "a.py"}])
    assert add["ok"]
    # For user 1 should fail
    col2 = mgr.create_collection(1, "TooMany")["collection"]
    add2 = mgr.add_items(1, col2["id"], [{"source": "regular", "file_name": "x.py"}])
    assert not add2["ok"] and "5000" in add2["error"]


def test_add_remove_reorder_and_counts(mgr: CollectionsManager):
    col = mgr.create_collection(3, "Work")["collection"]
    cid = col["id"]
    # add items
    r = mgr.add_items(3, cid, [
        {"source": "regular", "file_name": "a.py", "pinned": True},
        {"source": "regular", "file_name": "b.py"},
        {"source": "regular", "file_name": "c.py"},
    ])
    assert r["ok"] and r["added"] >= 0
    # Stats updated on collection doc
    stored = mgr.collections.find_one({"_id": cid})
    assert stored and stored.get("items_count") == 3 and stored.get("pinned_count") == 1

    # reorder
    rr = mgr.reorder_items(3, cid, [
        {"source": "regular", "file_name": "c.py"},
        {"source": "regular", "file_name": "a.py"},
        {"source": "regular", "file_name": "b.py"},
    ])
    assert rr["ok"] and rr["updated"] == 3

    # remove one
    rm = mgr.remove_items(3, cid, [{"source": "regular", "file_name": "b.py"}])
    assert rm["ok"] and rm["deleted"] == 1
    stored = mgr.collections.find_one({"_id": cid})
    assert stored and stored.get("items_count") == 2

    # get items (manual mode)
    out = mgr.get_collection_items(3, cid, page=1, per_page=10, include_computed=True)
    assert out["ok"] and len(out["items"]) == 2


def test_get_collection_invalid_id(mgr: CollectionsManager):
    bad = mgr.get_collection(99, "not-an-id")
    assert not bad["ok"]
