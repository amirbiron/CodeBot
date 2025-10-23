from types import SimpleNamespace
import pytest

from database.collections_manager import CollectionsManager, ObjectId


class Coll:
    def __init__(self):
        self.docs = []
    def create_indexes(self, *a, **k): return None
    def insert_one(self, doc):
        if "_id" not in doc:
            doc["_id"] = f"oid{len(self.docs)+1}"
        self.docs.append(dict(doc))
        return SimpleNamespace(inserted_id=doc["_id"])
    def update_one(self, flt, upd):
        mod = 0
        for d in self.docs:
            if str(d.get("_id")) == str(flt.get("_id")) and int(d.get("user_id")) == int(flt.get("user_id")):
                for k, v in upd.get("$set", {}).items():
                    d[k] = v
                mod += 1
        return SimpleNamespace(modified_count=mod)
    def find_one(self, flt):
        for d in self.docs:
            if str(d.get("_id")) == str(flt.get("_id")) and int(d.get("user_id")) == int(flt.get("user_id")):
                return dict(d)
        return None


class Items:
    def __init__(self):
        self.docs = []
    def create_indexes(self, *a, **k): return None
    def insert_one(self, doc): self.docs.append(dict(doc)); return SimpleNamespace(inserted_id=doc.get("_id"))
    def aggregate(self, pipeline, allowDiskUse=True):
        # respect match by collection_id + user_id
        docs = self.docs
        for st in pipeline:
            if "$match" in st:
                m = st["$match"]
                docs = [d for d in docs if str(d.get("collection_id")) == str(m.get("collection_id")) and int(d.get("user_id")) == int(m.get("user_id"))]
            elif "$group" in st:
                return [{"_id": None, "cnt": len(docs), "pinned": len([1 for d in docs if d.get('pinned')])}]
        return []


class DB:
    def __init__(self):
        self.user_collections = Coll()
        self.collection_items = Items()
        self.code_snippets = SimpleNamespace(aggregate=lambda *a, **k: [])


@pytest.fixture()
def mgr() -> CollectionsManager:
    return CollectionsManager(DB())


def test_counts_are_scoped_to_owner(mgr: CollectionsManager):
    # two users, two collections
    c1 = mgr.create_collection(1, "A")["collection"]
    c2 = mgr.create_collection(2, "B")["collection"]
    # add item to c1 by user 1
    mgr.add_items(1, c1["id"], [{"source":"regular","file_name":"a.py","pinned":True}])
    # malicious attempt: user 2 tries to bump counts by calling add on c1
    mgr.add_items(2, c1["id"], [{"source":"regular","file_name":"b.py"}])
    # counts for c1 should reflect only user 1 items
    doc1 = mgr.collections.find_one({"_id": ObjectId(c1["id"]), "user_id": 1})
    assert doc1 and doc1.get("items_count") == 1 and doc1.get("pinned_count") == 1


def test_update_fails_on_foreign_collection(mgr: CollectionsManager):
    # ensure c owned by user 3
    c = mgr.create_collection(3, "X")["collection"]
    # user 4 tries to add and cause counts update on foreign collection — update_one must not match
    mgr.add_items(4, c["id"], [{"source":"regular","file_name":"x.py"}])
    # verify counters unchanged for owner (remain 0)
    doc = mgr.collections.find_one({"_id": ObjectId(c["id"]), "user_id": 3})
    assert doc and int(doc.get("items_count") or 0) == 0
