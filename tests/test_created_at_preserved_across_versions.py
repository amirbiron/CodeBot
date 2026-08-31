"""שימור תאריך היצירה של קובץ בין גרסאות.

כל "גרסה" היא מסמך חדש ב-``code_snippets``. לפני התיקון כל מסמך כזה נולד עם
``created_at = now``, ולכן המסך שקורא את הגרסה האחרונה הציג את זמן העריכה
כזמן היצירה. הבדיקות כאן נכשלות על הקוד שלפני התיקון.

מוסכמת הריפו: fakes בעבודת יד, בלי mongomock, בלי ייבוא מ-conftest.
"""

import types
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pytest

ORIGINAL_CREATED_AT = datetime(2020, 1, 1, 8, 30, tzinfo=timezone.utc)


class _Result:
    def __init__(self, inserted_id: Any = None, matched: int = 0, modified: int = 0):
        self.inserted_id = inserted_id
        self.matched_count = matched
        self.modified_count = modified


class InMemoryCollection:
    """אוסף Mongo מינימלי: מספיק ל-find_one עם sort, insert_one ו-update_many."""

    def __init__(self) -> None:
        self.docs: List[Dict[str, Any]] = []

    def insert_one(self, doc: Dict[str, Any]):
        doc = dict(doc)
        doc.setdefault("_id", f"id_{len(self.docs) + 1}")
        doc.setdefault("is_active", True)
        self.docs.append(doc)
        return _Result(inserted_id=doc["_id"])

    def find_one(self, query: Dict[str, Any], projection=None, sort=None):
        items = self._filter(query)
        if sort:
            for key, direction in reversed(list(sort)):
                items.sort(key=lambda d: d.get(key, 0), reverse=(direction < 0))
        return dict(items[0]) if items else None

    def update_many(self, query: Dict[str, Any], update: Dict[str, Any]):
        items = self._filter(query)
        set_data = update.get("$set", {})
        modified = 0
        for doc in items:
            before = {k: doc.get(k) for k in set_data}
            doc.update(set_data)
            if before != {k: doc.get(k) for k in set_data}:
                modified += 1
        return _Result(matched=len(items), modified=modified)

    def _filter(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
        def matches(doc: Dict[str, Any]) -> bool:
            for key, expected in query.items():
                if isinstance(expected, dict) and "$ne" in expected:
                    if doc.get(key) == expected["$ne"]:
                        return False
                elif doc.get(key) != expected:
                    return False
            return True

        return [d for d in self.docs if matches(d)]


class FakeManager:
    def __init__(self) -> None:
        self.collection = InMemoryCollection()
        self.large_files_collection = InMemoryCollection()
        self.db = types.SimpleNamespace()


@pytest.fixture()
def repo():
    from database.repository import Repository

    return Repository(FakeManager())


def _snippet(**overrides):
    from database.models import CodeSnippet

    kwargs: Dict[str, Any] = {
        "user_id": 1,
        "file_name": "a.py",
        "code": "print(2)\n",
        "programming_language": "python",
    }
    kwargs.update(overrides)
    return CodeSnippet(**kwargs)


def _large_file(**overrides):
    from database.models import LargeFile

    kwargs: Dict[str, Any] = {
        "user_id": 1,
        "file_name": "big.txt",
        "content": "line\n" * 10,
        "programming_language": "text",
        "file_size": 0,
        "lines_count": 0,
    }
    kwargs.update(overrides)
    return LargeFile(**kwargs)


def _active(collection: InMemoryCollection, file_name: str) -> Optional[Dict[str, Any]]:
    docs = [d for d in collection.docs if d.get("file_name") == file_name and d.get("is_active")]
    return max(docs, key=lambda d: int(d.get("version", 0) or 0)) if docs else None


def test_new_version_inherits_created_at(repo):
    """עריכה מייצרת גרסה חדשה — התאריך המקורי עובר אליה, updated_at מתרענן."""
    repo.manager.collection.insert_one({
        "user_id": 1,
        "file_name": "a.py",
        "code": "print(1)\n",
        "programming_language": "python",
        "version": 1,
        "is_active": True,
        "created_at": ORIGINAL_CREATED_AT,
        "updated_at": ORIGINAL_CREATED_AT,
    })

    assert repo.save_code_snippet(_snippet()) is True

    latest = _active(repo.manager.collection, "a.py")
    assert latest is not None
    assert latest["version"] == 2
    assert latest["created_at"] == ORIGINAL_CREATED_AT
    assert latest["updated_at"] > ORIGINAL_CREATED_AT


def test_third_version_still_carries_the_original_date(repo):
    """הירושה לא נשחקת: גם הגרסה השלישית נושאת את התאריך של הראשונה."""
    repo.manager.collection.insert_one({
        "user_id": 1,
        "file_name": "a.py",
        "code": "print(1)\n",
        "programming_language": "python",
        "version": 1,
        "is_active": True,
        "created_at": ORIGINAL_CREATED_AT,
        "updated_at": ORIGINAL_CREATED_AT,
    })

    assert repo.save_code_snippet(_snippet(code="print(2)\n")) is True
    assert repo.save_code_snippet(_snippet(code="print(3)\n")) is True

    latest = _active(repo.manager.collection, "a.py")
    assert latest is not None
    assert latest["version"] == 3
    assert latest["created_at"] == ORIGINAL_CREATED_AT


def test_brand_new_file_created_at_equals_updated_at(repo):
    """קובץ שנוצר עכשיו ומעולם לא נערך: שני התאריכים זהים בדיוק.

    בלי זה, המסך עלול להציג "עודכן" על קובץ טרי רק בגלל שהשמירה נפלה על
    גבול הדקה בין שתי קריאות ל-datetime.now().
    """
    assert repo.save_code_snippet(_snippet(file_name="new.py")) is True

    doc = _active(repo.manager.collection, "new.py")
    assert doc is not None
    assert doc["version"] == 1
    assert doc["created_at"] == doc["updated_at"]


def test_large_file_resave_inherits_created_at(repo):
    """save_large_file מוחק ומכניס מחדש — התאריך המקורי חייב לשרוד."""
    repo.manager.large_files_collection.insert_one({
        "user_id": 1,
        "file_name": "big.txt",
        "content": "old\n",
        "programming_language": "text",
        "file_size": 4,
        "lines_count": 1,
        "is_active": True,
        "created_at": ORIGINAL_CREATED_AT,
        "updated_at": ORIGINAL_CREATED_AT,
    })

    assert repo.save_large_file(_large_file()) is True

    doc = _active(repo.manager.large_files_collection, "big.txt")
    assert doc is not None
    assert doc["created_at"] == ORIGINAL_CREATED_AT
    assert doc["updated_at"] > ORIGINAL_CREATED_AT


def test_brand_new_large_file_created_at_equals_updated_at(repo):
    assert repo.save_large_file(_large_file(file_name="fresh.txt")) is True

    doc = _active(repo.manager.large_files_collection, "fresh.txt")
    assert doc is not None
    assert doc["created_at"] == doc["updated_at"]


class TestInheritedCreatedAtHelper:
    """הכלל עצמו — מקור אמת אחד שכל נקודות הכתיבה נשענות עליו."""

    def test_takes_the_first_candidate_that_has_a_date(self):
        from database.repository import inherited_created_at

        now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        assert inherited_created_at(now, {"created_at": ORIGINAL_CREATED_AT}) == ORIGINAL_CREATED_AT

    def test_falls_through_a_candidate_that_lacks_the_field(self):
        """שליפה שדה-שדה, לא מיזוג מילונים.

        מיזוג היה נותן למסמך בלי created_at לדרוס את הערך של מסמך שיש לו.
        """
        from database.repository import inherited_created_at

        now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        result = inherited_created_at(now, {"file_name": "a.py"}, {"created_at": ORIGINAL_CREATED_AT})
        assert result == ORIGINAL_CREATED_AT

    def test_falls_back_when_nothing_usable(self):
        from database.repository import inherited_created_at

        now = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        assert inherited_created_at(now) == now
        assert inherited_created_at(now, None, {}, {"created_at": None}) == now
