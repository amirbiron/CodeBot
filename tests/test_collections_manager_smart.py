from types import SimpleNamespace
import typing as t

import pytest

from database.collections_manager import CollectionsManager, ObjectId


class FakeAgg:
    def __init__(self):
        self.last_pipeline = None
    def aggregate(self, pipeline, allowDiskUse: bool = True):
        self.last_pipeline = pipeline
        # החזר צורה כמו בפייפליין של compute_smart_items (אחרי project)
        return [
            {"file_name": "x.py"},
            {"file_name": "x.py"},  # בכוונה כפילות
            {"file_name": "y.py"},
        ]


class FakeColl:
    def __init__(self):
        self.docs = []
    def create_indexes(self, *a, **k):
        return None
    def insert_one(self, doc):
        if "_id" not in doc:
            doc["_id"] = f"oid{len(self.docs)+1}"
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc["_id"])
    def find_one(self, flt):
        for d in self.docs:
            if str(d.get("_id")) == str(flt.get("_id")) and str(d.get("user_id")) == str(flt.get("user_id")):
                return dict(d)
        return None
    def find(self, flt):
        return [dict(d) for d in self.docs if str(d.get("user_id")) == str(flt.get("user_id"))]
    def count_documents(self, flt):
        return len([1 for d in self.docs if str(d.get("user_id")) == str(flt.get("user_id"))])
    def update_one(self, flt, upd, **kwargs):
        mod = 0
        for d in self.docs:
            if str(d.get("_id")) == str(flt.get("_id")) and str(d.get("user_id")) == str(flt.get("user_id")):
                for k, v in upd.get("$set", {}).items():
                    d[k] = v
                mod += 1
                break
        return SimpleNamespace(modified_count=mod)


class FakeItems:
    def __init__(self):
        self.docs = []
    def create_indexes(self, *a, **k):
        return None
    def insert_one(self, doc):
        # הזנה פשוטה
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc.get("_id"))
    def update_one(self, flt, upd, **kwargs):
        mod = 0
        for d in self.docs:
            ok = (
                str(d.get("collection_id")) == str(flt.get("collection_id")) and
                str(d.get("user_id")) == str(flt.get("user_id")) and
                str(d.get("source")) == str(flt.get("source")) and
                str(d.get("file_name")) == str(flt.get("file_name"))
            )
            if ok:
                for k, v in upd.get("$set", {}).items():
                    d[k] = v
                mod += 1
                break
        return SimpleNamespace(matched_count=mod, modified_count=mod)
    def delete_one(self, flt):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not (
            str(d.get("collection_id")) == str(flt.get("collection_id")) and
            str(d.get("user_id")) == str(flt.get("user_id")) and
            str(d.get("source")) == str(flt.get("source")) and
            str(d.get("file_name")) == str(flt.get("file_name"))
        )]
        return SimpleNamespace(deleted_count=(before - len(self.docs)))
    def delete_many(self, flt):
        before = len(self.docs)
        self.docs = [d for d in self.docs if not (str(d.get("collection_id")) == str(flt.get("collection_id")))]
        return SimpleNamespace(deleted_count=(before - len(self.docs)))
    def count_documents(self, flt):
        return len([1 for d in self.docs if str(d.get("user_id")) == str(flt.get("user_id"))])
    def aggregate(self, pipeline, allowDiskUse=True):
        # תמיכה ב-counts על פי pipeline שהמנג'ר שולח (match + group)
        docs = self.docs
        for stage in pipeline:
            if "$match" in stage:
                m = stage["$match"]
                docs = [d for d in docs if str(d.get("collection_id")) == str(m.get("collection_id"))]
            if "$group" in stage:
                cnt = len(docs)
                pinned = len([1 for d in docs if bool(d.get("pinned"))])
                return [{"_id": None, "cnt": cnt, "pinned": pinned}]
        return []
    def find(self, flt):
        return [d for d in self.docs if str(d.get("collection_id")) == str(flt.get("collection_id")) and str(d.get("user_id")) == str(flt.get("user_id"))]


class FakeDB:
    def __init__(self):
        self.user_collections = FakeColl()
        self.collection_items = FakeItems()
        self.code_snippets = FakeAgg()  # with aggregate


@pytest.fixture()
def mgr() -> CollectionsManager:
    return CollectionsManager(FakeDB())


def test_compute_smart_items_builds_pipeline_and_maps(mgr: CollectionsManager):
    rules = {"query":"http", "programming_language":"python", "tags":["retry"], "repo_tag":"repo:core"}
    out = mgr.compute_smart_items(20, rules, limit=10)
    assert isinstance(out, list) and len(out) >= 2
    # ודא שנבנה pipeline עם match כנדרש
    pl = mgr.code_snippets.last_pipeline  # type: ignore[attr-defined]
    assert isinstance(pl, list) and pl and "$match" in pl[0]
    mt = pl[0]["$match"]
    assert mt["user_id"] == 20
    assert "programming_language" in mt and mt["programming_language"] == "python"
    assert "tags" in mt  # repo_tag משולב גם הוא לתנאי על tags


def test_get_collection_items_smart_and_include_flag(monkeypatch, mgr: CollectionsManager):
    c = mgr.create_collection(21, "Smart")["collection"]
    mgr.update_collection(21, c["id"], mode="smart", rules={"query":"q"})
    # list with include_computed = true -> items מה-aggregate
    res = mgr.get_collection_items(21, c["id"], page=1, per_page=10, include_computed=True)
    assert res["ok"] and any(it["file_name"] == "x.py" for it in res["items"])  # מתוך FakeAgg
    # false -> ללא computed
    res2 = mgr.get_collection_items(21, c["id"], page=1, per_page=10, include_computed=False)
    assert res2["ok"] and len(res2["items"]) == 0


def test_delete_collection_not_found(mgr: CollectionsManager):
    # לא קיים -> שגיאה ידידותית
    out = mgr.delete_collection(22, str(ObjectId()))
    assert not out["ok"]


def test_create_name_too_long_and_update_desc_too_long(mgr: CollectionsManager):
    long_name = "x"*81
    bad = mgr.create_collection(23, long_name)
    assert not bad["ok"]
    c = mgr.create_collection(23, "Short")["collection"]
    long_desc = "a"*600
    bad2 = mgr.update_collection(23, c["id"], description=long_desc)
    assert not bad2["ok"]


def test_add_items_blank_and_remove_not_found(mgr: CollectionsManager):
    c = mgr.create_collection(24, "Work")["collection"]
    # פריט עם שם ריק -> 0 הוספות
    res = mgr.add_items(24, c["id"], [{"source":"regular", "file_name":"   "}])
    assert res["ok"] and res["added"] == 0
    # מחיקה של פריט שלא קיים -> deleted=0
    rm = mgr.remove_items(24, c["id"], [{"source":"regular", "file_name":"nope.py"}])
    assert rm["ok"] and rm["deleted"] == 0
