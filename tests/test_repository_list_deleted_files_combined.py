"""‏``Repository.list_deleted_files``: שתי הקולקציות, שורה לכל קובץ, עימוד במסד.

**למה מונגו אמיתי ולא סטאב.** עד אוקטובר 2026 הפונקציה עשתה ``find`` על שתי
הקולקציות, מיזגה בפייתון, מיינה וחתכה ``combined[start:end]`` — וסטאב עם
``find`` בלבד הספיק. היא מריצה עכשיו אגרגציה אחת
(``file_deletion.recycle_bin_rows_pipeline``) עם ``$unionWith``, שני
``$lookup`` ו-``$group``, ואין לסטאב ידני דרך לענות עליה בלי לממש מנוע
אגרגציה — כלומר להמציא תוצאות. ``wired_mongo`` מדלג כשאין מונגו.

**וההחלטה שהטסט הזה מקבע:** כששתי גרסאות של אותו שם נמחקו בזמנים שונים,
השורה מצהירה על ה**מוקדם** מביניהם (``$min``). אינדקס ה-TTL מוחק
מסמך-מסמך, ולכן התאריך המוקדם הוא הרגע שבו הקובץ מפסיק להיות שלם.
"""

from datetime import datetime, timedelta, timezone

import pytest
from bson import ObjectId

pytest.importorskip("pymongo")

USER_ID = 1
NOW = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _repo(wa):
    from database.repository import Repository

    db = wa.get_db()

    class _Manager:
        def __init__(self):
            self.collection = db.code_snippets
            self.large_files_collection = db.large_files
            self.db = db

    return Repository(_Manager())


def _seed(wa, collection_name, file_name, *, deleted_at, versions=1):
    db = wa.get_db()
    collection = db.code_snippets if collection_name == "code_snippets" else db.large_files
    ids = []
    for index in range(versions):
        oid = ObjectId()
        ids.append(oid)
        doc = {
            "_id": oid,
            "user_id": USER_ID,
            "file_name": file_name,
            "is_active": False,
            "deleted_at": deleted_at + timedelta(minutes=index),
            "deleted_expires_at": NOW + timedelta(days=60),
        }
        if collection_name == "code_snippets":
            doc.update({"code": "x", "programming_language": "python",
                        "version": index + 1})
        else:
            doc["content"] = "x"
        collection.insert_one(doc)
    return ids


def _reset(wa):
    wa.get_db().code_snippets.delete_many({})
    wa.get_db().large_files.delete_many({})


def test_list_deleted_files_combined_sort_and_pagination(wired_mongo):
    _reset(wired_mongo)
    # שלושה קבצים, אחד מהם קובץ גדול, בשלושה זמני מחיקה.
    _seed(wired_mongo, "code_snippets", "a.py", deleted_at=NOW - timedelta(minutes=5))
    _seed(wired_mongo, "code_snippets", "b.py", deleted_at=NOW - timedelta(minutes=10))
    _seed(wired_mongo, "large_files", "big.txt", deleted_at=NOW - timedelta(minutes=2))
    repo = _repo(wired_mongo)

    page1, total = repo.list_deleted_files(USER_ID, page=1, per_page=2)

    assert total == 3
    # החדש קודם: big.txt (2 דקות), ואז a.py (5 דקות).
    assert [d.get("file_name") for d in page1] == ["big.txt", "a.py"]

    page2, _total = repo.list_deleted_files(USER_ID, page=2, per_page=2)
    assert [d.get("file_name") for d in page2] == ["b.py"]

    # ‏page<1 ו-per_page<1 מוצמדים ל-1, ולא הופכים ל-``$skip`` שלילי
    # (שהוא שגיאת שרת) או ל-``$limit: 0``.
    clamped, clamped_total = repo.list_deleted_files(USER_ID, page=0, per_page=0)
    assert clamped_total == 3
    assert [d.get("file_name") for d in clamped] == ["big.txt"]


def test_the_row_counts_versions_and_declares_the_earliest_deletion(wired_mongo):
    """קובץ אחד בשלוש גרסאות — שורה אחת, התאריך המוקדם, ומונה גרסאות."""
    _reset(wired_mongo)
    first = NOW - timedelta(days=10)
    _seed(wired_mongo, "code_snippets", "multi.py", deleted_at=first, versions=3)
    repo = _repo(wired_mongo)

    rows, total = repo.list_deleted_files(USER_ID, page=1, per_page=20)

    assert total == 1, "‏``total`` סופר מסמכי גרסה ולא קבצים"
    assert len(rows) == 1
    assert rows[0]["versions"] == 3
    assert rows[0]["deleted_at"] == first, (
        "השורה אינה מצהירה על המחיקה המוקדמת")
    assert rows[0]["source"] == "code_snippets"


def test_the_same_name_in_both_collections_is_two_rows(wired_mongo):
    """קיבוץ לפי שם לבד היה מאחד שתי ישויות נפרדות."""
    _reset(wired_mongo)
    _seed(wired_mongo, "code_snippets", "same.md", deleted_at=NOW - timedelta(hours=1))
    _seed(wired_mongo, "large_files", "same.md", deleted_at=NOW - timedelta(hours=2))
    repo = _repo(wired_mongo)

    rows, total = repo.list_deleted_files(USER_ID, page=1, per_page=20)

    assert total == 2
    assert sorted(d["source"] for d in rows) == ["code_snippets", "large_files"]


def test_a_document_without_deleted_at_still_comes_back(wired_mongo):
    """הסחיפה שהעותק הישן הביא: ``None`` במפתח המיון החזיר סל **ריק**.

    ‏``_key`` החזיר ``(None, None)``, ``sorted`` השווה ``None`` ל-``datetime``,
    ‏``TypeError`` עלה, וה-``except`` החזיר ``([], 0)``. ``$ifNull`` בצינור
    מחליף את ההשוואה הזו במפתח מיון מפורש.
    """
    _reset(wired_mongo)
    _seed(wired_mongo, "code_snippets", "dated.py", deleted_at=NOW)
    wired_mongo.get_db().code_snippets.insert_one({
        "_id": ObjectId(),
        "user_id": USER_ID,
        "file_name": "undated.py",
        "code": "x",
        "programming_language": "python",
        "version": 1,
        "is_active": False,
        "deleted_expires_at": NOW + timedelta(days=60),
    })
    repo = _repo(wired_mongo)

    rows, total = repo.list_deleted_files(USER_ID, page=1, per_page=20)

    assert total == 2, "הרשימה חזרה חסרה או ריקה"
    assert sorted(d["file_name"] for d in rows) == ["dated.py", "undated.py"]
    # ושורה בלי תאריך שוקעת למטה ולא מתפרצת לראש הרשימה.
    assert rows[-1]["file_name"] == "undated.py"


def test_a_failed_query_is_reported_and_not_an_empty_list(wired_mongo, monkeypatch):
    """ערוץ הכשל נשמר ``([], 0)`` — אבל נרשם, ומהסיבה הנכונה."""
    _reset(wired_mongo)
    _seed(wired_mongo, "code_snippets", "a.py", deleted_at=NOW)
    repo = _repo(wired_mongo)

    def _boom(*a, **k):
        raise RuntimeError("aggregate_failed")

    monkeypatch.setattr(repo.manager.collection, "aggregate", _boom, raising=False)

    assert repo.list_deleted_files(USER_ID, page=1, per_page=20) == ([], 0)
