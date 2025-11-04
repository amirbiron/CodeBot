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


def test_ensure_default_collections_creates_once(mgr: CollectionsManager):
    mgr.ensure_default_collections(42)
    first = mgr.list_collections(42)
    assert first["ok"]
    collections = first["collections"]
    assert any(col["name"] == "שולחן עבודה" for col in collections)
    workspace = next(col for col in collections if col["name"] == "שולחן עבודה")
    assert workspace["is_favorite"] is True
    assert workspace["sort_order"] == -1
    assert workspace["icon"] == "🖥️"
    assert workspace["color"] == "purple"

    count_before = len(collections)
    mgr.ensure_default_collections(42)
    second = mgr.list_collections(42)
    assert second["ok"]
    assert len(second["collections"]) == count_before


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
    # For user 1 should fail – use an existing collection (limit 100 reached)
    existing = mgr.list_collections(1, limit=1, skip=0)
    assert existing["ok"] and existing["collections"], "expected at least one collection for user 1"
    col2_id = existing["collections"][0]["id"]
    add2 = mgr.add_items(1, col2_id, [{"source": "regular", "file_name": "x.py"}])
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


def test_icon_color_whitelist_and_slug_uniqueness(mgr: CollectionsManager):
    # invalid icon/color -> empty strings
    res = mgr.create_collection(user_id=10, name="Guides", description="", mode="manual", icon="<x>", color="invalid")
    assert res["ok"]
    col = res["collection"]
    assert col["icon"] == "" and col["color"] == ""

    # slug uniqueness when names collide
    res2 = mgr.create_collection(10, name="Guides")
    assert res2["ok"]
    c1 = col["slug"]
    c2 = res2["collection"]["slug"]
    assert c1 != c2


def test_update_mode_rules_and_validation(mgr: CollectionsManager):
    c = mgr.create_collection(11, "Smart")["collection"]
    # invalid mode
    bad = mgr.update_collection(11, c["id"], mode="invalid")
    assert not bad["ok"]
    # valid smart mode and rules
    good = mgr.update_collection(11, c["id"], mode="smart", rules={"query": "http", "programming_language": "python", "tags": ["retry"], "repo_tag": "repo:core"})
    assert good["ok"] and good["collection"]["mode"] == "smart"


def test_add_items_duplicate_updates_note_and_pinned(mgr: CollectionsManager):
    c = mgr.create_collection(12, "Work")["collection"]
    cid = c["id"]
    r1 = mgr.add_items(12, cid, [{"source": "regular", "file_name": "a.py", "note": "n1", "pinned": False}])
    assert r1["ok"]
    # add duplicate -> should update note/pinned (path goes through update_one)
    r2 = mgr.add_items(12, cid, [{"source": "regular", "file_name": "a.py", "note": "n2", "pinned": True}])
    assert r2["ok"]
    # verify by reading raw fake storage
    found = None
    for d in mgr.items.docs:  # type: ignore[attr-defined]
        if d.get("collection_id") == ObjectId(cid) and d.get("file_name") == "a.py":
            found = d
            break
    assert found and found.get("note") == "n2" and bool(found.get("pinned")) is True


def test_remove_items_invalid_and_then_ok(mgr: CollectionsManager):
    c = mgr.create_collection(13, "R")["collection"]
    # invalid body
    bad = mgr.remove_items(13, c["id"], [])
    assert not bad["ok"]
    mgr.add_items(13, c["id"], [{"source": "regular", "file_name": "x.py"}])
    ok = mgr.remove_items(13, c["id"], [{"source": "regular", "file_name": "x.py"}])
    assert ok["ok"] and ok["deleted"] == 1


def test_reorder_invalid_then_valid_and_sorting_mixed(monkeypatch, mgr: CollectionsManager):
    c = mgr.create_collection(14, "Mix")["collection"]
    cid = c["id"]
    # invalid
    bad = mgr.reorder_items(14, cid, [])
    assert not bad["ok"]
    # add manual items (one pinned)
    mgr.add_items(14, cid, [
        {"source": "regular", "file_name": "a.py"},
        {"source": "regular", "file_name": "b.py", "pinned": True},
        {"source": "regular", "file_name": "c.py"},
    ])
    # reorder sets custom_order: c -> 1, a -> 2, b -> 3
    mgr.reorder_items(14, cid, [
        {"source": "regular", "file_name": "c.py"},
        {"source": "regular", "file_name": "a.py"},
        {"source": "regular", "file_name": "b.py"},
    ])
    # switch mode to mixed and stub compute_smart_items to include duplicate and new file
    mgr.update_collection(14, cid, mode="mixed")
    monkeypatch.setattr(mgr, "compute_smart_items", lambda user_id, rules, limit=200: [
        {"source": "regular", "file_name": "a.py"},  # duplicate -> must be deduped
        {"source": "regular", "file_name": "d.py"},
    ])
    out = mgr.get_collection_items(14, cid, page=1, per_page=10, include_computed=True)
    assert out["ok"]
    names = [it["file_name"] for it in out["items"]]
    # expected order: pinned(b) first, then c(custom_order=1), a(custom_order=2), d(no custom)
    assert names[:4] == ["b.py", "c.py", "a.py", "d.py"]


def test_list_pagination(mgr: CollectionsManager):
    # ensure many
    for i in range(15):
        mgr.create_collection(15, f"P{i}")
    p1 = mgr.list_collections(15, limit=5, skip=0)
    p2 = mgr.list_collections(15, limit=5, skip=5)
    p3 = mgr.list_collections(15, limit=5, skip=10)
    assert p1["ok"] and p2["ok"] and p3["ok"]
    assert len(p1["collections"]) == 5 and len(p2["collections"]) == 5 and len(p3["collections"]) == 5


def test_add_remove_reorder_invalid_ids(mgr: CollectionsManager):
    # invalid ObjectId
    assert not mgr.add_items(99, "bad-id", [{"source":"regular","file_name":"x"}])["ok"]
    assert not mgr.remove_items(99, "bad-id", [{"source":"regular","file_name":"x"}])["ok"]
    assert not mgr.reorder_items(99, "bad-id", [{"source":"regular","file_name":"x"}])["ok"]


def test_update_without_fields(mgr: CollectionsManager):
    c = mgr.create_collection(16, "U")["collection"]
    res = mgr.update_collection(16, c["id"])  # no fields
    assert not res["ok"]
