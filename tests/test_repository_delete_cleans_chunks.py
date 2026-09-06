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
        return _Result(deleted=self.deleted)

    def find(self, query, projection=None):
        return list(self.docs)

    def find_one(self, query, projection=None, **kwargs):
        return self.docs[0] if self.docs else None

    def insert_one(self, doc):
        return _Result(inserted_id="new-id")


class _FakeManager:
    def __init__(self):
        self.collection = _FakeCollection([{"_id": "f1", "user_id": 7}])
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
        assert calls["delete"][-1]["file_name"] == "a.py"

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

    def test_delete_by_id_cleans_that_version_only(self, repo):
        repository, calls = repo
        repository.manager.collection.docs = [{"_id": "f1", "user_id": 7}]

        repository.delete_file_by_id("507f1f77bcf86cd799439011")

        assert calls["delete"], "delete_file_by_id left the semantic chunks behind"
        assert calls["delete"][-1]["user_id"] == 7
        assert len(calls["delete"][-1]["snippet_ids"]) == 1

    def test_delete_by_id_skips_cleanup_without_a_known_user(self, repo):
        """לעולם לא מוחקים צ'אנקים בלי תיחום למשתמש.

        אם השליפה המקדימה נכשלה, ג'וב הניקוי יטפל בהם — עדיף להשאיר יתום
        מאשר לגעת בנתונים של משתמש אחר.
        """
        repository, calls = repo
        repository.manager.collection.docs = []

        repository.delete_file_by_id("507f1f77bcf86cd799439011")

        assert calls["delete"] == []


class TestPurge:
    def test_purge_cleans_chunks(self, repo):
        repository, calls = repo
        assert repository.purge_file_by_id(7, "507f1f77bcf86cd799439011") is True
        assert calls["delete"], "purge_file_by_id left the semantic chunks behind"

    def test_purge_that_found_nothing_cleans_nothing(self, repo):
        repository, calls = repo
        repository.manager.collection.deleted = 0
        repository.manager.large_files_collection.deleted = 0

        assert repository.purge_file_by_id(7, "507f1f77bcf86cd799439011") is False
        assert calls["delete"] == []


class TestRestore:
    def test_restore_marks_the_file_for_reindex(self, repo):
        """הצ'אנקים נמחקו בהעברה לסל; בלי הסימון הזה הקובץ המשוחזר לא היה
        חוזר לחיפוש הסמנטי לעולם."""
        repository, calls = repo
        assert repository.restore_file_by_id(7, "507f1f77bcf86cd799439011") is True
        assert calls["reindex"], "restored file was never queued for re-embedding"
        assert len(calls["reindex"][-1]) == 1

    def test_restore_that_found_nothing_marks_nothing(self, repo):
        repository, calls = repo
        repository.manager.collection.modified = 0
        repository.manager.large_files_collection.modified = 0

        assert repository.restore_file_by_id(7, "507f1f77bcf86cd799439011") is False
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
