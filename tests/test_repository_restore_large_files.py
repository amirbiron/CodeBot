"""שחזור ומחיקה סופית מוצאים את הקובץ גם כשהוא ב-``large_files``.

הנפילה לקולקציה השנייה היא מה שנבדק כאן: ה-repository מחפש את המזהה
ב-``code_snippets`` קודם, ועובר ל-``large_files`` רק כשאין שם מה למצוא.
אחרי השינוי של אוקטובר 2026 החיפוש הזה הוא **קריאה** — מזהה ← שם קובץ
(``file_deletion.resolve_trashed_file_names``) — ולכן סטאב שמחזיר מונה
כתיבה בלי להחזיק מסמכים לא יכול להבדיל בין "נמצא" ל"לא נמצא".

**ושחזור של קובץ גדול מחזיר רוויזיה אחת.** ב-``large_files`` מסמך הוא
הקובץ (``file_deletion.SINGLE_ACTIVE_COLLECTIONS``): ``save_large_file``
מוריד את הקודם לסל בכל שמירה מחדש, והקוראים מניחים פעיל אחד לכל שם.
"""

import types
from datetime import datetime, timedelta, timezone

from bson import ObjectId

T0 = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc)


class _Coll:
    """אוסף שמכבד את המסננים — בלי זה הבדיקה אינה בודקת את הנפילה."""

    def __init__(self, docs=()):
        self.docs = [dict(d) for d in docs]
        self.updated = 0
        self.deleted = 0

    def _matching(self, flt):
        # ``_id`` בשוויון פשוט (``update_one`` לפי מזהה) או ב-``$in``. דמה שמבינה
        # רק ``$in`` מתעלמת מהמזהה ומעדכנת את המסמך הראשון שתואם — כלומר
        # "מצליחה" על המסמך הלא נכון.
        raw_id = flt.get("_id")
        if isinstance(raw_id, dict):
            ids = raw_id.get("$in")
        elif "_id" in flt:
            ids = [raw_id]
        else:
            ids = None
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

    def find(self, flt, projection=None, *a, sort=None, **k):
        out = [dict(d) for d in self._matching(flt)]
        for key, direction in reversed(list(sort or [])):
            out.sort(key=lambda d: (d.get(key) is not None, d.get(key) if d.get(key) is not None else 0),
                     reverse=direction == -1)
        return out

    def find_one(self, flt, projection=None, *a, sort=None, **k):
        found = self.find(flt, projection, sort=sort)
        return found[0] if found else None

    def _apply(self, docs, upd):
        for d in docs:
            d.update(upd.get("$set") or {})
            for key in (upd.get("$unset") or {}):
                d.pop(key, None)

    def update_one(self, flt, upd):
        self.updated += 1
        hits = self._matching(flt)[:1]
        self._apply(hits, upd)
        return types.SimpleNamespace(modified_count=len(hits))

    def update_many(self, flt, upd):
        self.updated += 1
        hits = self._matching(flt)
        self._apply(hits, upd)
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
    """רוויזיות בסל, הראשונה נמחקה ראשונה. ``updated_at`` הפוך ל-``deleted_at``
    בכוונה — שחזור מגיבוי מעביר ``updated_at`` היסטורי — כדי שמיון לפי השדה
    הלא נכון ייפול כאן ולא יעבור דרך שובר השוויון."""
    return [{"_id": ObjectId(), "user_id": user_id, "file_name": file_name,
             "is_active": False,
             "deleted_at": T0 + timedelta(days=i),
             "updated_at": T0 - timedelta(days=i)} for i in range(copies)]


def test_restore_and_purge_large_files(monkeypatch):
    from database.repository import Repository

    docs = _large()
    mgr = _Manager(docs)
    repo = Repository(mgr)

    assert repo.restore_file_by_id(5, str(docs[0]["_id"])) is True
    active = [d for d in mgr.large_files_collection.docs if d["is_active"] is True]
    # **אחת** — ודווקא זו שנמחקה אחרונה, גם כשהמזהה שנשלח הוא של אחרת.
    assert [d["_id"] for d in active] == [docs[-1]["_id"]], active
    assert mgr.collection.updated == 0, "נשלחה כתיבה לקולקציה הלא נכונה"

    docs = _large("other.txt", copies=3)
    mgr = _Manager(docs)
    repo = Repository(mgr)

    assert repo.purge_file_by_id(5, str(docs[2]["_id"])) is True
    assert mgr.large_files_collection.docs == []
    assert mgr.collection.deleted == 0


def test_a_large_file_that_is_still_alive_is_not_restored_twice(monkeypatch):
    """רוויזיה בסל של קובץ גדול **חי** — מצב קבוע אחרי כל שמירה מחדש.

    הצינור מסתיר שורה כזו, אבל עמוד ישן או קריאה ישירה ל-API עדיין שולחים
    את המזהה. שחזור היה יוצר עותק פעיל שני.
    """
    from database.repository import Repository

    trashed = _large("live.txt", copies=1)
    alive = {"_id": ObjectId(), "user_id": 5, "file_name": "live.txt", "is_active": True}
    mgr = _Manager(trashed + [alive])
    repo = Repository(mgr)

    assert repo.restore_file_by_id(5, str(trashed[0]["_id"])) is False
    assert [d["_id"] for d in mgr.large_files_collection.docs if d["is_active"]] == [alive["_id"]]
    assert mgr.large_files_collection.updated == 0


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
