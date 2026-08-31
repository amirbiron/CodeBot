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

from datetime import datetime, timedelta, timezone

import pytest

from mongo_it import make_mongo_db_fixture, requires_mongo

pytestmark = requires_mongo

#: תחילית ייעודית לקובץ הזה — סורג המחיקה ב-``mongo_it`` נשען עליה.
mongo_db = make_mongo_db_fixture("codebot_created_it_")


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
    # ``>=`` ולא ``>``: שתי שמירות ברצף יכולות ליפול על אותה חותמת אם
    # רזולוציית השעון מגסה. הטענה שנבדקת כאן היא ש-``updated_at`` **אינו
    # יורש** מהגרסה הקודמת אלא נקבע מחדש — ולכן הוא לעולם לא נסוג אחורה.
    assert v2["updated_at"] >= v1["updated_at"], "תאריך הגרסה חי ב-updated_at"


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
    assert a["files_in_batch"] == 1
    assert a["documents_planned"] == 1
    assert a["modified"] == 1
    assert a["remaining_after"] == 0
    assert a["done"] is True
    assert a["audit_error"] is None
    latest = mongo_db.code_snippets.find_one({"file_name": "old.py", "version": 3})
    assert latest["created_at"] == t0, "האחרונה קיבלה את המוקדם"
    v2 = mongo_db.code_snippets.find_one({"file_name": "old.py", "version": 2})
    assert v2["created_at"] == t1, "גרסה ישנה נגועה — ההיסטוריה שובשה"

    # אידמפוטנטי: החלה שנייה לא מוצאת מה לתקן
    again = mig.apply(mongo_db)
    assert again["documents_planned"] == 0
    assert again["modified"] == 0
    assert again["remaining_after"] == 0


def test_migration_audit_records_both_modes(mongo_db):
    from services import created_at_migration as mig

    mig.dry_run(mongo_db)
    mig.apply(mongo_db)
    modes = [d["mode"] for d in mongo_db[mig.AUDIT_COLLECTION].find()]
    assert modes == ["dry_run", "apply"]


def test_migration_fixes_latest_version_without_created_at(mongo_db):
    """הגרסה האחרונה בלי ``created_at`` — הקובץ שהצינור הישן דילג עליו.

    ``$gt`` מול ``null`` מחזיר ``false`` (נמדד מול mongod 7.0.14), ולכן
    תנאי הפער לבדו הסתיר בדיוק את הקבצים השבורים ביותר: אלה שאין להם
    תאריך כלל. ההורשה קדימה הייתה נותנת להם ``now`` בעריכה הבאה.
    """
    from services import created_at_migration as mig

    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mongo_db.code_snippets.insert_one(
        {"user_id": 7, "file_name": "nodate.py", "version": 1, "is_active": True, "created_at": t0}
    )
    mongo_db.code_snippets.insert_one(
        {"user_id": 7, "file_name": "nodate.py", "version": 2, "is_active": True}
    )

    assert mig.count_affected(mongo_db) == 1, "הקובץ לא זוהה כמושפע"
    a = mig.apply(mongo_db)
    assert a["modified"] == 1 and a["remaining_after"] == 0

    latest = mongo_db.code_snippets.find_one({"file_name": "nodate.py", "version": 2})
    assert latest["created_at"] == t0


def test_migration_fixes_every_document_at_the_highest_version(mongo_db):
    """שני מסמכים באותה גרסה — שניהם מתוקנים, בלי לנחש מי "האחרון".

    מרוץ כתיבה ידוע מייצר תאומים, והאפליקציה בוחרת ביניהם עם ``$sort``
    בלי שובר-שוויון — כלומר הבחירה אינה יציבה. תיקון של אחד מהם היה
    משאיר את ה-UI מציג לפעמים את התאריך הישן.
    """
    from services import created_at_migration as mig

    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    mongo_db.code_snippets.insert_many([
        {"user_id": 8, "file_name": "twin.py", "version": 1, "is_active": True, "created_at": t0},
        {"user_id": 8, "file_name": "twin.py", "version": 2, "is_active": True,
         "created_at": t0 + timedelta(days=9)},
        {"user_id": 8, "file_name": "twin.py", "version": 2, "is_active": True,
         "created_at": t0 + timedelta(days=3)},
    ])

    a = mig.apply(mongo_db)
    assert a["files_in_batch"] == 1
    assert a["documents_planned"] == 2, "רק אחד מהתאומים תוקן"
    assert a["modified"] == 2

    twins = [d["created_at"] for d in mongo_db.code_snippets.find({"file_name": "twin.py", "version": 2})]
    assert twins == [t0, t0]


def test_migration_leaves_files_that_have_no_date_to_inherit(mongo_db):
    """קובץ שלאף גרסה שלו אין ``created_at`` — אין ממה לרשת, לא נוגעים."""
    from services import created_at_migration as mig

    mongo_db.code_snippets.insert_many([
        {"user_id": 9, "file_name": "blank.py", "version": 1, "is_active": True},
        {"user_id": 9, "file_name": "blank.py", "version": 2, "is_active": True},
    ])

    assert mig.count_affected(mongo_db) == 0
    a = mig.apply(mongo_db)
    assert a["documents_planned"] == 0

    for doc in mongo_db.code_snippets.find({"file_name": "blank.py"}):
        assert doc.get("created_at") is None


def test_migration_applies_in_batches(mongo_db):
    """אצווה חסומה בגודל, ודיווח יתרה — כדי שלא תחסום בקשת HTTP."""
    from services import created_at_migration as mig

    t0 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(3):
        mongo_db.code_snippets.insert_many([
            {"user_id": 10, "file_name": f"b{i}.py", "version": 1, "is_active": True, "created_at": t0},
            {"user_id": 10, "file_name": f"b{i}.py", "version": 2, "is_active": True,
             "created_at": t0 + timedelta(days=5)},
        ])

    first = mig.apply(mongo_db, batch_size=2)
    assert first["files_in_batch"] == 2
    assert first["remaining_after"] == 1
    assert first["done"] is False

    second = mig.apply(mongo_db, batch_size=2)
    assert second["files_in_batch"] == 1
    assert second["remaining_after"] == 0
    assert second["done"] is True

    for i in range(3):
        latest = mongo_db.code_snippets.find_one({"file_name": f"b{i}.py", "version": 2})
        assert latest["created_at"] == t0


def test_migration_reports_audit_failure_instead_of_swallowing_it(mongo_db):
    """כשל בכתיבת ה-audit חוזר בתוצאה — לא נבלע מאחורי דיווח הצלחה.

    זהו הדפוס שכבר עלה בריפו הזה: פעולה שהכשל שלה מוחזר כערך ולא נזרק,
    ומעליה דיווח "הצליח". ה-audit הוא חלק מהחוזה של מיגרציה, ולכן
    הכישלון שלו חייב להגיע לעיני האדמין.
    """
    from services import created_at_migration as mig

    class _FailingAudit:
        def __init__(self, real):
            self._real = real

        def __getitem__(self, name):
            if name == mig.AUDIT_COLLECTION:
                class _Broken:
                    def insert_one(self, *a, **k):
                        raise RuntimeError("audit collection is read-only")
                return _Broken()
            return self._real[name]

        def __getattr__(self, name):
            return getattr(self._real, name)

    db = _FailingAudit(mongo_db)
    assert mig.dry_run(db)["audit_error"] == "audit collection is read-only"
    assert mig.apply(db)["audit_error"] == "audit collection is read-only"
