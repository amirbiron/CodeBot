""""נוצר" של קובץ שורד עריכה — מול **מונגו אמיתי**, באותה תבנית של
``test_note_boards_mongo``: רץ כש-``MONGODB_URL`` נגיש (ב-CI תמיד), מדלג
מקומית.

הרקע: כל עריכת תוכן יוצרת מסמך גרסה חדש, וה-UI מציג את הגרסה האחרונה.
בלי הורשת ``created_at`` ב-``save_code_snippet``, "נוצר" קפץ לתאריך
העריכה בכל שמירה — בעוד שעריכת תיאור (עדכון-במקום) שימרה אותו. ההורשה
מצטרפת לבלוק שכבר מעתיק מועדפים ונעיצה מהגרסה הקודמת.

כל בדיקה כאן הופלה על הקוד שלפני התיקון (ריצת בקרה מתועדת ב-PR) —
בדיקה שלא הורצה על הקוד הישן אינה ראיה.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pymongo = pytest.importorskip("pymongo")

from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

_TEST_DB_PREFIX = "codebot_created_it_"
_MONGO_URL = os.environ.get("MONGODB_URL", "").strip()


def _server_is_reachable(url: str) -> bool:
    try:
        client = pymongo.MongoClient(url, serverSelectionTimeoutMS=2000, tz_aware=True, tzinfo=timezone.utc)
        client.admin.command("ping")
        client.close()
        return True
    except (ServerSelectionTimeoutError, Exception):
        return False


pytestmark = pytest.mark.skipif(
    not _MONGO_URL or not _server_is_reachable(_MONGO_URL),
    reason="דורש MONGODB_URL עם שרת מונגו נגיש (קיים ב-CI, לא בהכרח מקומית)",
)


@pytest.fixture
def mongo_db():
    name = f"{_TEST_DB_PREFIX}{uuid.uuid4().hex[:12]}"
    client = pymongo.MongoClient(_MONGO_URL, tz_aware=True, tzinfo=timezone.utc)
    db = client[name]
    try:
        yield db
    finally:
        # סורג בטיחות: מוחקים רק מסד שנוצר כאן
        assert name.startswith(_TEST_DB_PREFIX), f"סירוב למחוק מסד שאינו של הבדיקות: {name}"
        try:
            client.drop_database(name)
        finally:
            client.close()


@pytest.fixture
def repo(mongo_db):
    """``Repository`` אמיתי מעל המסד הזמני.

    ``Repository`` נוגע במנהל רק דרך ``manager.collection``, ולכן שים
    (shim) דק מספיק — ובלי סטאב לכתיבות: ה-insert וה-find הם של מונגו.
    """
    from database.repository import Repository

    class _Mgr:
        collection = mongo_db.code_snippets
        db = mongo_db

    return Repository(_Mgr())


def _snippet(name: str, code: str, **kw):
    from database.models import CodeSnippet

    return CodeSnippet(user_id=42, file_name=name, code=code, programming_language="python", **kw)


def test_new_version_inherits_created_at(repo, mongo_db):
    """גרסה 2 נולדת עם ה"נוצר" של גרסה 1 — ועם "עודכן" משלה."""
    assert repo.save_code_snippet(_snippet("a.py", "v1"))
    v1 = mongo_db.code_snippets.find_one({"file_name": "a.py", "version": 1})
    assert v1 is not None

    assert repo.save_code_snippet(_snippet("a.py", "v2"))
    v2 = mongo_db.code_snippets.find_one({"file_name": "a.py", "version": 2})
    assert v2 is not None

    assert v2["created_at"] == v1["created_at"], "עריכה אינה לידה מחדש"
    assert v2["updated_at"] > v1["updated_at"], "תאריך הגרסה חי ב-updated_at"


def test_inheritance_survives_a_chain_of_edits(repo, mongo_db):
    """שרשרת: גם גרסה 4 נושאת את ה"נוצר" של גרסה 1, לא של קודמתה בלבד."""
    for body in ("v1", "v2", "v3", "v4"):
        assert repo.save_code_snippet(_snippet("chain.py", body))
    docs = {d["version"]: d for d in mongo_db.code_snippets.find({"file_name": "chain.py"})}
    assert len(docs) == 4
    origin = docs[1]["created_at"]
    assert all(docs[v]["created_at"] == origin for v in (2, 3, 4))


def test_legacy_version_without_created_at_does_not_erase_default(repo, mongo_db):
    """מסמך ותיק בלי ``created_at`` — הגרסה החדשה לא יורשת ריק.

    זה ה-``or`` בהורשה: ירושה של None הייתה משאירה את הגרסה החדשה בלי
    תאריך בכלל, גרוע מהבאג המקורי.
    """
    mongo_db.code_snippets.insert_one(
        {"user_id": 42, "file_name": "legacy.py", "code": "old", "programming_language": "python",
         "version": 1, "is_active": True, "updated_at": datetime.now(timezone.utc)}
    )
    assert repo.save_code_snippet(_snippet("legacy.py", "new"))
    v2 = mongo_db.code_snippets.find_one({"file_name": "legacy.py", "version": 2})
    assert isinstance(v2.get("created_at"), datetime)


def test_migration_dry_run_reads_only_and_apply_fixes_latest_only(mongo_db):
    """שירות המיגרציה: dry-run לא כותב; ההחלה מיישרת רק את האחרונה."""
    from services import created_at_migration as mig

    utc = timezone.utc
    t0 = datetime(2024, 1, 1, tzinfo=utc)
    t1 = t0 + timedelta(days=100)
    t2 = t0 + timedelta(days=500)
    for v, t in ((1, t0), (2, t1), (3, t2)):
        mongo_db.code_snippets.insert_one(
            {"user_id": 1, "file_name": "old.py", "version": v,
             "created_at": t, "updated_at": t, "is_active": True}
        )

    d = mig.dry_run(mongo_db)
    assert d["affected_count"] == 1 and d["total_files"] == 1
    # dry-run אינו כותב — אימות בקריאה חוזרת, לא בערך ההחזרה
    latest = mongo_db.code_snippets.find_one({"file_name": "old.py", "version": 3})
    assert latest["created_at"] == t2

    a = mig.apply(mongo_db)
    assert a == {**a, "planned": 1, "modified": 1, "remaining_after": 0}
    latest = mongo_db.code_snippets.find_one({"file_name": "old.py", "version": 3})
    assert latest["created_at"] == t0, "האחרונה קיבלה את המוקדם"
    v2 = mongo_db.code_snippets.find_one({"file_name": "old.py", "version": 2})
    assert v2["created_at"] == t1, "גרסה ישנה נגועה — ההיסטוריה שובשה"

    # אידמפוטנטי: החלה שנייה לא מוצאת מה לתקן
    again = mig.apply(mongo_db)
    assert again["planned"] == 0 and again["modified"] == 0


def test_migration_audit_records_both_modes(mongo_db):
    from services import created_at_migration as mig

    mig.dry_run(mongo_db)
    mig.apply(mongo_db)
    modes = [d["mode"] for d in mongo_db[mig.AUDIT_COLLECTION].find()]
    assert modes == ["dry_run", "apply"]
