"""טסט לארכיון אוספים: ארכוב/שחזור דרך update_collection + סינון ב-list_collections.

מוודא ש:
- אוסף שאורכב (is_archived=True) נעלם מהתצוגה הרגילה ומופיע רק ב-archived_only=True.
- שחזור (is_archived=False) מחזיר אותו לתצוגה הרגילה.
- אוסף "ישן" ללא השדה is_archived עדיין מופיע בתצוגה הרגילה (בזכות $ne:True).

ה-fakes כאן תומכים ב-$ne/$or/$in/$exists/$set ו-find_one_and_update (כמו
FakeCollection ב-test_collections_manager_unit), כדי לתרגל את המסלול המלא.
"""

from database.collections_manager import CollectionsManager


def _match(doc, flt):
    for k, v in flt.items():
        if k == "$or":
            if not any(_match(doc, c) for c in v):
                return False
        elif isinstance(v, dict) and "$in" in v:
            if doc.get(k) not in v["$in"]:
                return False
        elif isinstance(v, dict) and "$ne" in v:
            # $ne מתקיים גם כששדה חסר (מיוצג כ-None) — חשוב לאוספים ישנים
            if doc.get(k) == v["$ne"]:
                return False
        elif isinstance(v, dict) and "$exists" in v:
            if bool(v["$exists"]) != (k in doc):
                return False
        else:
            if str(doc.get(k)) != str(v):
                return False
    return True


def _apply_set(doc, upd):
    if "$set" in upd:
        for k, val in upd["$set"].items():
            doc[k] = val


class _Result:
    def __init__(self, modified=0):
        self.modified_count = modified
        self.matched_count = modified
        self.acknowledged = True


class _Coll:
    def __init__(self):
        self.docs = []

    def create_indexes(self, *a, **k):
        return None

    def create_index(self, *a, **k):
        return None

    def insert_one(self, doc):
        if not doc.get("_id"):
            doc["_id"] = f"{len(self.docs) + 1:024x}"
        self.docs.append(dict(doc))
        return _Result(1)

    def find(self, flt, projection=None):
        return [dict(d) for d in self.docs if _match(d, flt)]

    def find_one(self, flt, projection=None):
        for d in self.docs:
            if _match(d, flt):
                return dict(d)
        return None

    def find_one_and_update(self, flt, upd, return_document=True):
        for d in self.docs:
            if _match(d, flt):
                _apply_set(d, upd)
                return dict(d)
        return None

    def update_many(self, flt, upd, **k):
        n = 0
        for d in self.docs:
            if _match(d, flt):
                _apply_set(d, upd)
                n += 1
        return _Result(n)

    def count_documents(self, flt):
        return sum(1 for d in self.docs if _match(d, flt))

    def aggregate(self, *a, **k):
        return []


class _DB:
    def __init__(self):
        self.user_collections = _Coll()
        self.collection_items = _Coll()
        self.code_snippets = _Coll()


def _names(res):
    return sorted(c["name"] for c in res["collections"])


def test_archive_hides_from_default_and_shows_in_archive_view():
    mgr = CollectionsManager(_DB())
    uid = 7
    a = mgr.create_collection(uid, "אוסף א")
    b = mgr.create_collection(uid, "אוסף ב")
    assert a["ok"] and b["ok"]
    cid_a = a["collection"]["id"]

    # לפני ארכוב: שניהם ברשימה הרגילה, הארכיון ריק
    assert _names(mgr.list_collections(uid)) == ["אוסף א", "אוסף ב"]
    assert mgr.list_collections(uid, archived_only=True)["collections"] == []

    # ארכוב א' דרך update_collection (אותו מסלול כמו is_favorite)
    upd = mgr.update_collection(uid, cid_a, is_archived=True)
    assert upd["ok"] is True
    assert upd["collection"]["is_archived"] is True

    # אחרי ארכוב: רק ב' ברגיל, רק א' בארכיון
    assert _names(mgr.list_collections(uid)) == ["אוסף ב"]
    assert _names(mgr.list_collections(uid, archived_only=True)) == ["אוסף א"]


def test_unarchive_restores_to_default():
    mgr = CollectionsManager(_DB())
    uid = 9
    c = mgr.create_collection(uid, "לשחזר")
    cid = c["collection"]["id"]
    mgr.update_collection(uid, cid, is_archived=True)
    assert _names(mgr.list_collections(uid)) == []

    upd = mgr.update_collection(uid, cid, is_archived=False)
    assert upd["ok"] is True
    assert upd["collection"]["is_archived"] is False
    assert _names(mgr.list_collections(uid)) == ["לשחזר"]
    assert mgr.list_collections(uid, archived_only=True)["collections"] == []


def test_include_archived_returns_both():
    # include_archived=True (מסלול הגיבוי האישי): גם פעילים וגם מאורכבים
    mgr = CollectionsManager(_DB())
    uid = 11
    mgr.create_collection(uid, "פעיל")
    b = mgr.create_collection(uid, "מאורכב")
    mgr.update_collection(uid, b["collection"]["id"], is_archived=True)
    assert _names(mgr.list_collections(uid)) == ["פעיל"]
    assert _names(mgr.list_collections(uid, include_archived=True)) == ["מאורכב", "פעיל"]


def test_legacy_collection_without_field_shows_in_default():
    # אוסף "ישן" שנשמר לפני הוספת is_archived (השדה חסר בכוונה)
    db = _DB()
    db.user_collections.docs.append(
        {
            "_id": "0" * 24,
            "user_id": 5,
            "name": "ישן",
            "slug": "yashan",
            "is_active": True,
        }
    )
    mgr = CollectionsManager(db)
    assert _names(mgr.list_collections(5)) == ["ישן"]
    assert mgr.list_collections(5, archived_only=True)["collections"] == []
