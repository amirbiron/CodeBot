"""מחיקת קובץ חייבת להוריד גם את הצ'אנקים הסמנטיים שלו.

הרקע (אישו #3332): ה-``delete_many`` היחיד על ``snippet_chunks`` בכל הריפו
היה בתוך ``save_snippet_chunks``. אף נתיב מחיקה לא נגע בקולקציה, ולכן
נמדדו בפרודקשן 355 צ'אנקים יתומים (6.5MB) על פני 118 קבצים מחוקים.

הצ'אנקים האלה אינם מוצגים בתוצאות — הצינור מסנן אותם ב-``$lookup`` —
אבל הם תופסים מקום ומתחרים על מקומות ה-ANN.
"""

import inspect
from datetime import datetime, timezone

import pytest
from bson import ObjectId

import database.repository as repo_mod
from database.manager import (
    delete_snippet_chunks as _real_delete_snippet_chunks,
    mark_snippets_for_reindex as _real_mark_snippets_for_reindex,
)


class _Result:
    def __init__(self, modified=0, deleted=0, inserted_id=None):
        self.modified_count = modified
        self.deleted_count = deleted
        self.inserted_id = inserted_id


class _FakeCollection:
    """דמות מקרטון של אוסף מונגו — מספיק למסלולי המחיקה והשחזור."""

    def __init__(self, docs=None):
        self.docs = list(docs or [])
        self.modified = 1
        self.deleted = 1

    def update_many(self, query, update):
        return _Result(modified=self.modified)

    def delete_many(self, query):
        """מוחקת באמת את מה שהמסנן תופס — ``deleted = 0`` מדמה "לא נמחק כלום".

        ‏``purge_files_by_names`` משווה את ``deleted_count`` למספר המזהים
        שאסף, וכשהוא קצר קורא מה **עוד קיים**. דמה שמדווחת מחיקה בלי למחוק
        הייתה מציגה לו שורד מקבילי שאינו קיים.
        """
        if not self.deleted:
            return _Result(deleted=0)
        hits = [d for d in self.docs if self._matches(d, query)]
        self.docs = [d for d in self.docs if d not in hits]
        return _Result(deleted=len(hits))

    @staticmethod
    def _matches(doc, query):
        ids = (query.get("_id") or {}).get("$in") if isinstance(query.get("_id"), dict) else None
        names = (query.get("file_name") or {}).get("$in") if isinstance(query.get("file_name"), dict) else None
        if "user_id" in query and doc.get("user_id") != query.get("user_id"):
            return False
        if "is_active" in query and doc.get("is_active") is not query.get("is_active"):
            return False
        if ids is not None and doc.get("_id") not in ids:
            return False
        if names is not None and doc.get("file_name") not in names:
            return False
        return True

    def find(self, query, projection=None, *args, sort=None, **kwargs):
        """מכבדת את המסננים, כי בלעדיהם אין מה שהבדיקה בודקת.

        מסלולי השחזור וה-purge מתרגמים מזהה ← שם קובץ ואז אוספים את מזהי
        **כל** גרסאות הסל של אותו שם. דמה שמחזירה את כל המסמכים לכל
        שאילתה לא יכולה להבדיל בין "מצאתי" ל"לא מצאתי", ודמה שמחזירה
        מסמך בלי ``file_name`` מחזירה רשימת שמות ריקה — כלומר ``False``
        בלי שום רמז למה.

        ‏``sort`` מכובד כמו ב-pymongo (``Cursor(sort=...)``): ``_trashed_ids_for_names``
        ממיין כדי שהמזהה הראשון יהיה הגרסה האחרונה, ודמה שמתעלמת מהמיון
        הייתה מחזירה את הסדר הטבעי — בדיוק הבאג שהטסט צריך לתפוס.
        """
        out = [dict(doc) for doc in self.docs if self._matches(doc, query)]
        # מיון יציב, מהמפתח האחרון לראשון. שדה חסר נמוך מכל ערך, כמו ב-BSON.
        for key, direction in reversed(list(sort or [])):
            out.sort(key=lambda d: (d.get(key) is not None, d.get(key) if d.get(key) is not None else 0),
                     reverse=direction == -1)
        return out

    def distinct(self, key, filter=None, *a, **k):
        """‏``Collection.distinct(key, filter=None, ...)`` — כמו pymongo.

        מסלול המחיקה שואל אילו שמות פעילים **לפני** שהוא מכבה אותם, כי
        אחרי העדכון אי אפשר לספור אותם. דמה בלי המתודה הזו זורקת
        ``AttributeError`` שנבלע ב-``except`` של ``delete_file``, והמחיקה
        מדווחת ``False`` בלי שום רמז למה.
        """
        wanted = ((filter or {}).get("file_name") or {}).get("$in")
        if wanted is not None:
            return list(dict.fromkeys(wanted))
        return [d[key] for d in self.docs if key in d]

    def find_one(self, query, projection=None, **kwargs):
        return self.docs[0] if self.docs else None

    def insert_one(self, doc):
        return _Result(inserted_id="new-id")


#: המזהה שהבדיקות בקובץ הזה שולחות. ``ObjectId`` ולא מחרוזת: כל מסלול
#: שמקבל מזהה ממיר אותו ואז משווה אותו במסד, ולכן דמה עם ``_id`` מחרוזתי
#: לא תתאים לשום שאילתה — והמסלול יחזיר "לא נמצא" מסיבה שאינה הנבדקת.
FILE_ID = ObjectId("507f1f77bcf86cd799439011")


def _versions(*, is_active, file_name="a.py", user_id=7, count=2):
    """גרסאות של אותו קובץ, הראשונה ב-``FILE_ID``.

    מסמך של גרסה נושא שם קובץ ומצב — שני התנאים שהתרגום מזהה ← שם מסנן
    לפיהם, יחד עם הבעלות.
    """
    docs = [{"_id": FILE_ID, "user_id": user_id, "file_name": file_name,
             "version": 1, "is_active": is_active}]
    docs += [{"_id": ObjectId(), "user_id": user_id, "file_name": file_name,
              "version": v, "is_active": is_active}
             for v in range(2, count + 1)]
    return docs


class _FakeManager:
    def __init__(self):
        # ברירת המחדל היא קובץ **בסל**: מסלולי השחזור וה-purge הם הרוב
        # בקובץ הזה. מי שבודק מחיקה מציב גרסאות פעילות במקומן.
        self.collection = _FakeCollection(_versions(is_active=False))
        self.large_files_collection = _FakeCollection()


# הדמות נבדקות מול **החתימה האמיתית**, לא מול חתימה שנכתבה ביד.
#
# למה זה חשוב: דמה שנכתבה ביד קופאת ברגע שנכתבה. כשהפונקציה האמיתית מקבלת
# פרמטר חדש (``older_than_version``, ``file_names``), הדמה הצרה נופלת על
# ``TypeError`` שנבלע במקום אחר, או — גרוע יותר — הטסט עובר בזמן שהקוד
# האמיתי שולח משהו שהדמה מעולם לא ראתה. ``Signature.bind`` מקשר את השתיים.
_DELETE_SIG = inspect.signature(_real_delete_snippet_chunks)
_REINDEX_SIG = inspect.signature(_real_mark_snippets_for_reindex)


@pytest.fixture()
def repo(monkeypatch):
    calls = {"delete": [], "reindex": []}

    def _delete(*args, **kwargs):
        bound = _DELETE_SIG.bind(*args, **kwargs)
        bound.apply_defaults()
        calls["delete"].append(dict(bound.arguments))
        return 0

    def _reindex(*args, **kwargs):
        bound = _REINDEX_SIG.bind(*args, **kwargs)
        bound.apply_defaults()
        calls["reindex"].append(list(bound.arguments.get("snippet_ids") or []))
        return len(bound.arguments.get("snippet_ids") or [])

    monkeypatch.setattr(repo_mod, "delete_snippet_chunks", _delete)
    monkeypatch.setattr(repo_mod, "mark_snippets_for_reindex", _reindex)
    return repo_mod.Repository(_FakeManager()), calls


class TestSoftDelete:
    def test_delete_file_cleans_chunks_by_name(self, repo):
        repository, calls = repo
        assert repository.delete_file(7, "a.py") is True

        assert calls["delete"], "delete_file left the semantic chunks behind"
        assert calls["delete"][-1]["user_id"] == 7
        # ‏``file_names`` גם לשם יחיד: מחיקה בודדת ומחיקה מרובה עוברות
        # באותו קוד, וזה מה שמונע מהן להיפרד שוב.
        assert calls["delete"][-1]["file_names"] == ["a.py"]
        assert calls["delete"][-1]["file_name"] is None

    def test_delete_file_skips_cleanup_when_nothing_was_trashed(self, repo):
        repository, calls = repo
        repository.manager.collection.modified = 0

        assert repository.delete_file(7, "a.py") is False
        assert calls["delete"] == []

    def test_bulk_soft_delete_cleans_every_name_in_one_call(self, repo):
        """שאילתה אחת עם ``$in``, לא לולאה לפי שם.

        מחיקה מרובה של 1,000 קבצים בלולאה הייתה מייצרת 2,000 פעולות סדרתיות
        מול מונגו (``find`` + ``delete_many`` לכל שם), כל אחת עם round-trip
        משלה. ה-helper כבר תומך ב-``file_names``.
        """
        repository, calls = repo
        repository.soft_delete_files_by_names(7, ["a.py", "b.py", "c.py"])

        assert len(calls["delete"]) == 1, (
            f"{len(calls['delete'])} cleanup calls for 3 files; expected one batched call"
        )
        call = calls["delete"][0]
        assert set(call["file_names"]) == {"a.py", "b.py", "c.py"}
        assert call["file_name"] is None, "the batched path must not also pass a single name"
        assert call["user_id"] == 7

    def test_delete_by_id_cleans_the_whole_file_and_not_one_version(self, repo):
        """הטענה הזו הפוכה מקודמתה, במכוון.

        קודם הניקוי נעשה לפי ``snippet_ids`` — כלומר לפי מזהה הגרסה
        היחידה שהמסך מסר. כך הצ'אנקים של הגרסאות שמתחתיה נשארו מאונדקסים
        בזמן שהקובץ כולו יושב בסל. הניקוי הוא לפי **שם**, כמו המחיקה
        עצמה, ובקריאה אחת.
        """
        repository, calls = repo
        repository.manager.collection.docs = _versions(is_active=True, count=1)

        out = repository.soft_delete_files_by_ids(7, [str(FILE_ID)])

        assert out == {"files": 1, "versions": 1, "missing": 0}, out
        assert calls["delete"], "soft_delete_files_by_ids left the semantic chunks behind"
        assert calls["delete"][-1]["user_id"] == 7
        assert calls["delete"][-1]["file_names"] == ["a.py"]
        assert calls["delete"][-1]["snippet_ids"] is None, (
            "ניקוי לפי מזהה גרסה משאיר את הצ'אנקים של הגרסאות שמתחת")

    def test_an_id_that_belongs_to_nobody_cleans_nothing(self, repo):
        """לעולם לא מוחקים צ'אנקים בלי תיחום למשתמש.

        מזהה שלא נמצא בבעלות המשתמש אינו מייצר שם קובץ, ולכן אין מה
        לנקות — עדיף להשאיר יתום מאשר לגעת בנתונים של משתמש אחר.
        """
        repository, calls = repo
        repository.manager.collection.docs = []

        out = repository.soft_delete_files_by_ids(7, [str(FILE_ID)])

        assert out == {"files": 0, "versions": 0, "missing": 1}, out
        assert calls["delete"] == []


class TestPurge:
    def test_purge_cleans_chunks(self, repo):
        repository, calls = repo
        assert repository.purge_file_by_id(7, str(FILE_ID)) is True
        assert calls["delete"], "purge_file_by_id left the semantic chunks behind"

    def test_a_version_restored_mid_purge_keeps_its_chunks(self, repo):
        """שחזור מקביל בין איסוף המזהים למחיקה.

        המזהים נאספים לפני ``delete_many``. גרסה ששוחזרה ביניהם אינה נמחקת —
        המסנן תחום ל-``is_active: False`` — אבל המזהה שלה כבר ברשימה, והרשימה
        הולכת ל-``delete_snippet_chunks``. כלומר מחיקה של הצ'אנקים של גרסה
        **חיה**. הרשימה שחוזרת חייבת להיות מה שבאמת נמחק.
        """
        repository, calls = repo
        coll = repository.manager.collection
        survivor = max(coll.docs, key=lambda d: d["version"])
        real_delete_many = coll.delete_many

        def _restore_then_delete(query):
            # השחזור המקביל נוחת בדיוק כאן: אחרי האיסוף, לפני המחיקה.
            survivor["is_active"] = True
            return real_delete_many(query)

        coll.delete_many = _restore_then_delete

        assert repository.purge_file_by_id(7, str(FILE_ID)) is True

        assert any(d["_id"] == survivor["_id"] for d in coll.docs), "הגרסה החיה נמחקה"
        sent = calls["delete"][-1]["snippet_ids"]
        assert survivor["_id"] not in sent, "הצ'אנקים של גרסה ששוחזרה נשלחו למחיקה"
        assert sent == [FILE_ID], sent

    def test_purge_that_found_nothing_cleans_nothing(self, repo):
        repository, calls = repo
        repository.manager.collection.deleted = 0
        repository.manager.large_files_collection.deleted = 0

        assert repository.purge_file_by_id(7, str(FILE_ID)) is False
        assert calls["delete"] == []


class TestRestore:
    def test_restore_marks_the_file_for_reindex(self, repo):
        """הצ'אנקים נמחקו בהעברה לסל; בלי הסימון הזה הקובץ המשוחזר לא היה
        חוזר לחיפוש הסמנטי לעולם."""
        repository, calls = repo
        latest = max(repository.manager.collection.docs, key=lambda d: d["version"])

        # המזהה שנשלח הוא של v1 — זה ש-``FILE_ID`` מחזיק, והראשון בסדר הטבעי.
        assert repository.restore_file_by_id(7, str(FILE_ID)) is True
        assert calls["reindex"], "restored file was never queued for re-embedding"
        # **איזה** מזהה, ולא כמה. ה-worker מסיים כל גרסה שאינה האחרונה באפס
        # צ'אנקים (``is_latest_active_snippet``), ולכן סימון של v1 היה משאיר
        # את הקובץ המשוחזר מחוץ לחיפוש הסמנטי לצמיתות. בדיקה של האורך בלבד
        # עברה על הקוד ששלח את v1.
        assert calls["reindex"][-1] == [latest["_id"]], calls["reindex"][-1]

    def test_restore_that_found_nothing_marks_nothing(self, repo):
        repository, calls = repo
        repository.manager.collection.modified = 0
        repository.manager.large_files_collection.modified = 0

        assert repository.restore_file_by_id(7, str(FILE_ID)) is False
        assert calls["reindex"] == []


class TestNewVersion:
    def test_saving_a_new_version_clears_the_previous_versions_chunks(self, repo, monkeypatch):
        """שמירת גרסה חדשה אינה מכבה את הקודמת (``is_active`` שלה נשאר True),
        ולכן בלי המחיקה הזו כל גרסה היסטורית נשארת מאונדקסת."""
        from database.models import CodeSnippet

        repository, calls = repo
        monkeypatch.setattr(repository, "get_latest_version", lambda *a, **k: None)

        snippet = CodeSnippet(
            user_id=7,
            file_name="a.py",
            code="print(1)",
            programming_language="python",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        repository.save_code_snippet(snippet)

        assert calls["delete"], "previous versions kept their chunks"
        last = calls["delete"][-1]
        assert last["file_name"] == "a.py"
        assert last["exclude_snippet_id"] == "new-id", "the new version lost its own chunks"


class TestOverlappingSaves:
    """המירוץ שהריוויו תפס: שתי שמירות של אותו קובץ שרצות במקביל.

    שמירה A מכניסה גרסה 1, שמירה B מכניסה גרסה 2. הניקוי של B מוחק הכל חוץ
    מ-2 — תקין. אבל הניקוי של A רץ מאוחר יותר בגלל החפיפה, ובכלל "הכל חוץ
    ממני" הוא מוחק גם את הצ'אנקים של גרסה 2. גרסה 2 היא הגרסה האחרונה,
    ה-worker כבר סימן אותה ``chunkerVersion`` נוכחי, ולכן היא **לעולם** לא
    תיחתך שוב — הקובץ נעלם מהחיפוש הסמנטי לצמיתות. ג'וב הניקוי לא עוזר: הוא
    מוחק, לא בונה.

    התיקון הוא בהגדרה, לא בנעילה: "מחק רק מה שישן ממני".
    """

    @staticmethod
    def _save(repository, monkeypatch, version):
        """``save_code_snippet`` קובע את המספר בעצמו (``max_version + 1``),
        ולכן שולטים במקור ולא בעצם — אחרת הטסט היה בודק ערך שנדרס."""
        from database.models import CodeSnippet

        monkeypatch.setattr(repository, "get_latest_version", lambda *a, **k: None)
        monkeypatch.setattr(
            repository, "_max_version_any_state", lambda *a, **k: version - 1
        )
        snippet = CodeSnippet(
            user_id=7,
            file_name="a.py",
            code="print(1)",
            programming_language="python",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        repository.save_code_snippet(snippet)
        assert snippet.version == version, "the fixture did not control the version"

    def test_cleanup_is_bounded_to_versions_older_than_the_one_just_saved(
        self, repo, monkeypatch
    ):
        repository, calls = repo
        self._save(repository, monkeypatch, version=3)

        assert calls["delete"], "previous versions kept their chunks"
        call = calls["delete"][-1]
        assert call["older_than_version"] == 3, (
            "cleanup is unbounded; a concurrent newer save would lose its chunks"
        )
        assert call["file_name"] == "a.py"
        assert call["exclude_snippet_id"] == "new-id"

    def test_a_late_cleanup_from_an_older_save_cannot_touch_a_newer_version(
        self, repo, monkeypatch
    ):
        """סדר ההגעה הפוך: הגרסה החדשה נשמרה קודם, הישנה מנקה אחריה."""
        repository, calls = repo
        self._save(repository, monkeypatch, version=2)
        self._save(repository, monkeypatch, version=1)

        late = calls["delete"][-1]
        assert late["older_than_version"] == 1, (
            "the late cleanup would delete the chunks of version 2"
        )

    def test_the_bound_is_the_version_actually_written(self, repo, monkeypatch):
        """הגבול נלקח מהמספר שהקוד קבע, לא ממה שהמתקשר שלח.

        ``save_code_snippet`` דורס את ``snippet.version`` ב-``max_version + 1``.
        גבול שנקרא מהערך שלפני הדריסה היה נמוך מדי, והניקוי לא היה מוחק כלום.
        """
        repository, calls = repo
        self._save(repository, monkeypatch, version=8)

        assert calls["delete"][-1]["older_than_version"] == 8
