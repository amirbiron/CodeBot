"""טסט ל-enrichment של תיאור הקובץ ב-get_collection_items.

מוודא שכל פריט באוסף מקבל את ה-description של הקובץ מ-code_snippets (לאייקון
התיאור בכרטיס), דרך אותו batch שמחשב is_file_active — בלי N+1 ובלי שדות כבדים.

הערה: ה-fakes כאן תומכים ב-find(..., projection=...) (בניגוד ל-FakeCollection
ב-test_collections_manager_unit), אחרת ה-batch נופל ל-fail-open ולא מצרף תיאור.
"""

from database.collections_manager import CollectionsManager, ObjectId


def _match(doc, flt):
    for k, v in flt.items():
        if k == "$or":
            if not any(_match(doc, c) for c in v):
                return False
        elif isinstance(v, dict) and "$in" in v:
            if doc.get(k) not in v["$in"]:
                return False
        elif isinstance(v, dict) and "$ne" in v:
            if doc.get(k) == v["$ne"]:
                return False
        else:
            if str(doc.get(k)) != str(v):
                return False
    return True


class _Coll:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    def find(self, flt, projection=None):
        return [dict(d) for d in self.docs if _match(d, flt)]

    def find_one(self, flt, projection=None):
        for d in self.docs:
            if _match(d, flt):
                return dict(d)
        return None

    def create_indexes(self, *a, **k):
        return None

    def create_index(self, *a, **k):
        return None

    def aggregate(self, *a, **k):
        return []


class _DB:
    def __init__(self, collections, items, snippets):
        self.user_collections = _Coll(collections)
        self.collection_items = _Coll(items)
        self.code_snippets = _Coll(snippets)


def _setup(*, description, is_active=True, file_name="a.py"):
    uid = 7
    cid = ObjectId()
    col = {"_id": cid, "user_id": uid, "mode": "manual", "rules": {}}
    item = {
        "_id": ObjectId(),
        "collection_id": cid,
        "user_id": uid,
        "source": "regular",
        "file_name": file_name,
    }
    snippet = {
        "_id": ObjectId(),
        "user_id": uid,
        "file_name": file_name,
        "description": description,
        "is_active": is_active,
    }
    mgr = CollectionsManager(_DB([col], [item], [snippet]))
    return mgr, uid, str(cid)


def test_item_gets_file_description():
    mgr, uid, cid = _setup(description="תיאור הקובץ שלי")
    res = mgr.get_collection_items(uid, cid)
    assert res["ok"] is True
    item = res["items"][0]
    assert item["description"] == "תיאור הקובץ שלי"
    assert item["is_file_active"] is True


def test_item_without_description_gets_empty_string():
    mgr, uid, cid = _setup(description="")
    item = mgr.get_collection_items(uid, cid)["items"][0]
    assert item["description"] == ""


def test_inactive_file_has_no_description():
    # קובץ לא-פעיל לא נשלף ב-batch (is_active:True) ⇒ אין תיאור, ואין אייקון.
    mgr, uid, cid = _setup(description="לא אמור להופיע", is_active=False)
    item = mgr.get_collection_items(uid, cid)["items"][0]
    assert item["description"] == ""
    assert item["is_file_active"] is False
