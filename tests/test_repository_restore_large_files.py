"""שחזור ומחיקה סופית מוצאים את הקובץ גם כשהוא ב-``large_files``.

הנפילה לקולקציה השנייה היא מה שנבדק כאן: ה-repository מחפש את המזהה
ב-``code_snippets`` קודם, ועובר ל-``large_files`` רק כשאין שם מה למצוא.
אחרי השינוי של אוקטובר 2026 החיפוש הזה הוא **קריאה** — מזהה ← שם קובץ
(``file_deletion.resolve_trashed_file_names``) — ולכן סטאב שמחזיר מונה
כתיבה בלי להחזיק מסמכים לא יכול להבדיל בין "נמצא" ל"לא נמצא".
"""

import types

from bson import ObjectId


class _Coll:
    """אוסף שמכבד את המסננים — בלי זה הבדיקה אינה בודקת את הנפילה."""

    def __init__(self, docs=()):
        self.docs = [dict(d) for d in docs]
        self.updated = 0
        self.deleted = 0

    def _matching(self, flt):
        ids = flt.get("_id", {}).get("$in") if isinstance(flt.get("_id"), dict) else None
        names = (flt.get("file_name") or {}).get("$in") if isinstance(flt.get("file_name"), dict) else None
        out = []
        for d in self.docs:
            if d.get("user_id") != flt.get("user_id"):
                continue
            if "is_active" in flt and d.get("is_active") is not flt.get("is_active"):
                continue
            if ids is not None and d.get("_id") not in ids:
                continue
            if names is not None and d.get("file_name") not in names:
                continue
            out.append(d)
        return out

    def find(self, flt, projection=None, *a, **k):
        return [dict(d) for d in self._matching(flt)]

    def update_many(self, flt, upd):
        self.updated += 1
        hits = self._matching(flt)
        for d in hits:
            d.update(upd.get("$set") or {})
            for key in (upd.get("$unset") or {}):
                d.pop(key, None)
        return types.SimpleNamespace(modified_count=len(hits))

    def delete_many(self, flt):
        self.deleted += 1
        hits = self._matching(flt)
        for d in hits:
            self.docs.remove(d)
        return types.SimpleNamespace(deleted_count=len(hits))

    def count_documents(self, flt=None, *a, **k):
        return len(self._matching(flt or {}))

    def aggregate(self, *a, **k):
        return []


class _Manager:
    def __init__(self, large_docs):
        # ``code_snippets`` ריק במכוון: זה מה שמאלץ את המעבר לקולקציה השנייה.
        self.collection = _Coll()
        self.large_files_collection = _Coll(large_docs)


def _large(file_name="big.txt", copies=2, user_id=5):
    return [{"_id": ObjectId(), "user_id": user_id, "file_name": file_name,
             "is_active": False} for _ in range(copies)]


def test_restore_and_purge_large_files(monkeypatch):
    from database.repository import Repository

    docs = _large()
    mgr = _Manager(docs)
    repo = Repository(mgr)

    assert repo.restore_file_by_id(5, str(docs[0]["_id"])) is True
    # **כל** מסמכי הסל של אותו שם, ולא רק זה שהמזהה הצביע עליו.
    assert all(d["is_active"] is True for d in mgr.large_files_collection.docs)
    assert mgr.collection.updated == 0, "נשלחה כתיבה לקולקציה הלא נכונה"

    docs = _large("other.txt", copies=3)
    mgr = _Manager(docs)
    repo = Repository(mgr)

    assert repo.purge_file_by_id(5, str(docs[2]["_id"])) is True
    assert mgr.large_files_collection.docs == []
    assert mgr.collection.deleted == 0


def test_an_id_in_neither_collection_is_false(monkeypatch):
    """אין מה לשחזר — ואין כתיבה. ``False`` כאן אינו כשל אלא "לא נמצא"."""
    from database.repository import Repository

    mgr = _Manager(_large(user_id=99))
    repo = Repository(mgr)

    assert repo.restore_file_by_id(5, str(ObjectId())) is False
    assert repo.purge_file_by_id(5, str(ObjectId())) is False
    assert mgr.collection.updated == mgr.collection.deleted == 0
    assert mgr.large_files_collection.updated == 0
    assert mgr.large_files_collection.deleted == 0
