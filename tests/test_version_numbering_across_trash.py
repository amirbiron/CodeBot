"""מספר גרסה ייחודי לכל קובץ — גם כשגרסאות יושבות בסל המיחזור.

**למה זה קיים.** מחיקה רכה אינה מוחקת: המסמכים נשארים עם ``is_active``
כבוי ויכולים לחזור לחיים בשחזור מהסל. ``_fetch_latest_version`` מסנן
``is_active: True``, ולכן שמירה בזמן שהקובץ בסל לא ראתה את הגרסאות
המחוקות וקיבלה ``version = 1`` — מספר שכבר תפוס.

התוצאה הייתה אובדן שקט: שחזור מהסל החזיר את הגרסאות הישנות, הבחירה
לפי הגרסה הגבוהה ביותר נתנה לתוכן **הישן** לגבור, והתוכן שנשמר אחריו
נקבר בלי שום סימן.
"""

from datetime import datetime, timezone

import pytest

pytest.importorskip("pymongo")

pytestmark = pytest.mark.usefixtures("wired_mongo")

USER_ID = 4242
FILE = "x.py"


class _Manager:
    """מנהל דק מעל מסד הבדיקה המחווט.

    ‏``DatabaseManager()`` היה מתחבר ל-URI של הקונפיג ולא ל-DB של
    ה-fixture. התבנית הזו כבר בשימוש ב-``tests/test_repository_favorites``,
    וכאן היא מצביעה על **מונגו אמיתי** ולא על אחסון בזיכרון.
    """

    def __init__(self, db):
        self.db = db
        self.collection = db.code_snippets
        self.large_files_collection = db.large_files


def _repo(db):
    from database.repository import Repository
    return Repository(_Manager(db))


def _save(repo, code):
    from database.models import CodeSnippet
    return repo.save_code_snippet(CodeSnippet(
        user_id=USER_ID, file_name=FILE, code=code, programming_language="python"))


def _versions(db):
    return sorted(d["version"] for d in db.code_snippets.find({"user_id": USER_ID}))


def test_a_save_while_the_file_is_in_the_trash_does_not_reuse_a_version(wired_mongo):
    """התוכן שנשמר אחרון הוא זה שנשאר, גם אחרי שחזור מהסל."""
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    mgr = _repo(db)

    for i in (1, 2, 3):
        _save(mgr, f"# ישן {i}")
    assert _versions(db) == [1, 2, 3], _versions(db)

    mgr.delete_file(USER_ID, FILE)
    _save(mgr, "# חדש לגמרי")

    # המספר החדש אינו מתנגש עם אף גרסה שבסל
    vs = _versions(db)
    assert len(vs) == len(set(vs)), f"מספרי גרסה כפולים: {vs}"
    assert vs == [1, 2, 3, 4], vs

    # שחזור מהסל — בדיוק כפי שהראוט עושה
    db.code_snippets.update_many(
        {"user_id": USER_ID, "is_active": False},
        {"$set": {"is_active": True},
         "$unset": {"deleted_at": "", "deleted_expires_at": ""}},
    )

    latest = mgr.get_latest_version(USER_ID, FILE)
    assert latest is not None
    assert "חדש" in (latest.get("code") or ""), (
        "התוכן הישן גבר על מה שנשמר אחריו: " + repr(latest.get("code")))


def test_metadata_is_not_inherited_from_a_trashed_file(wired_mongo):
    """מספור חוצה את הסל — הירושה לא.

    קובץ חדש שקיבל שם ממוחזר אינו אמור לרשת את ``created_at`` של קובץ
    אחר שנמחק; אחרת "נוצר" היה מציג תאריך של קובץ שהמשתמש כבר זרק.
    """
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    mgr = _repo(db)

    old_stamp = datetime(2019, 3, 7, 9, 15, tzinfo=timezone.utc)
    _save(mgr, "# ישן")
    db.code_snippets.update_many({"user_id": USER_ID}, {"$set": {"created_at": old_stamp}})
    mgr.delete_file(USER_ID, FILE)

    _save(mgr, "# קובץ חדש לגמרי באותו שם")

    fresh = db.code_snippets.find_one({"user_id": USER_ID, "is_active": True})
    assert fresh is not None
    assert fresh["created_at"] != old_stamp, \
        "התאריך נורש מקובץ שנמחק — 'נוצר' יציג תאריך של קובץ שנזרק"
