"""מחיקה לפי מזהה מורידה את **כל** גרסאות הקובץ, ולא את המסמך שנשלח.

המזהה מסמן גרסה; הקובץ הוא ``(user_id, file_name)``. מסכי הרשימה מוסרים
את המזהה של הגרסה האחרונה בלבד, ולכן מחיקה שמסננת לפיו השאירה את שאר
הגרסאות פעילות — והקובץ חזר לרשימה גרסה אחת אחורה.
"""

import types

from bson import ObjectId


class _Coll:
    """סטאב שמכבד את המסננים, כי בלי זה הבדיקה לא בודקת כלום."""

    def __init__(self, docs):
        self.docs = list(docs)
        self.update_filters = []

    def find(self, query, projection=None, *a, **k):
        ids = set((query.get("_id") or {}).get("$in") or [])
        return [
            dict(d) for d in self.docs
            if d["_id"] in ids and d["user_id"] == query.get("user_id")
        ]

    def distinct(self, key, filter=None, *a, **k):
        f = filter or {}
        wanted = set((f.get("file_name") or {}).get("$in") or [])
        return sorted({
            d[key] for d in self.docs
            if d["user_id"] == f.get("user_id")
            and d["file_name"] in wanted
            and d.get("is_active") is f.get("is_active")
        })

    def update_many(self, flt, upd):
        self.update_filters.append(flt)
        names = set((flt.get("file_name") or {}).get("$in") or [])
        n = 0
        for d in self.docs:
            if (d["user_id"] == flt.get("user_id") and d["file_name"] in names
                    and d.get("is_active") is flt.get("is_active")):
                d.update(upd["$set"])
                n += 1
        return types.SimpleNamespace(modified_count=n)


class _Mgr:
    def __init__(self, coll):
        self.collection = coll
        self.large_files_collection = coll
        self.db = types.SimpleNamespace()


def _repo(coll):
    from database.repository import Repository
    return Repository(_Mgr(coll))


def test_every_version_of_the_file_goes_to_the_trash():
    ids = [ObjectId() for _ in range(3)]
    coll = _Coll([
        {"_id": oid, "user_id": 3, "file_name": "a.py", "version": v, "is_active": True}
        for v, oid in enumerate(ids, start=1)
    ])

    # רק המזהה של הגרסה האחרונה נשלח — כך המסך בנוי
    out = _repo(coll).soft_delete_files_by_ids(3, [str(ids[-1])])

    assert out == {"files": 1, "versions": 3, "missing": 0}, out
    assert all(d["is_active"] is False for d in coll.docs), coll.docs
    # והמסנן עצמו לפי שם, לא לפי מזהה — אחרת הטענה למעלה עוברת במקרה
    assert "_id" not in coll.update_filters[-1], coll.update_filters[-1]


def test_an_id_of_another_user_deletes_nothing():
    oid = ObjectId()
    coll = _Coll([
        {"_id": oid, "user_id": 99, "file_name": "theirs.py", "version": 1, "is_active": True},
    ])

    out = _repo(coll).soft_delete_files_by_ids(3, [str(oid)])

    assert out == {"files": 0, "versions": 0, "missing": 1}, out
    assert coll.docs[0]["is_active"] is True
    assert coll.update_filters == []
