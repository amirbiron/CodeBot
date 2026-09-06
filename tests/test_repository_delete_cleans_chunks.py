"""מחיקת קובץ חייבת להוריד גם את הצ'אנקים הסמנטיים שלו.

הרקע (אישו #3332): ה-``delete_many`` היחיד על ``snippet_chunks`` בכל הריפו
היה בתוך ``save_snippet_chunks``. אף נתיב מחיקה לא נגע בקולקציה, ולכן
נמדדו בפרודקשן 355 צ'אנקים יתומים (6.5MB) על פני 118 קבצים מחוקים.

הצ'אנקים האלה אינם מוצגים בתוצאות — הצינור מסנן אותם ב-``$lookup`` —
אבל הם תופסים מקום ומתחרים על מקומות ה-ANN.
"""

from datetime import datetime, timezone

import pytest

import database.repository as repo_mod


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


@pytest.fixture()
def repo(monkeypatch):
    calls = {"delete": [], "reindex": []}

    def _delete(user_id, *, snippet_ids=None, file_name=None, exclude_snippet_id=None):
        calls["delete"].append({
            "user_id": user_id,
            "snippet_ids": list(snippet_ids or []),
            "file_name": file_name,
            "exclude_snippet_id": exclude_snippet_id,
        })
        return 0

    def _reindex(snippet_ids):
        calls["reindex"].append(list(snippet_ids or []))
        return len(snippet_ids or [])

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

    def test_bulk_soft_delete_cleans_every_name(self, repo):
        repository, calls = repo
        repository.soft_delete_files_by_names(7, ["a.py", "b.py"])

        cleaned = {c["file_name"] for c in calls["delete"]}
        assert cleaned == {"a.py", "b.py"}

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
