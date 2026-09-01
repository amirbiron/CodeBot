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


def test_a_failed_version_lookup_aborts_the_save(wired_mongo):
    """כשלא ידוע מה מספר הגרסה הבא — לא שומרים, ולא מנחשים.

    ‏``_max_version_any_state`` החזיר ``0`` בכשל DB, ערך שאינו נבדל
    מ"אין מסמכים": ``version = 1`` בזמן שכבר קיימות 1,2,3 — מספר כפול,
    ואז התוכן הישן גובר בבחירה לפי הגרסה הגבוהה.

    הכשל מוזרק לשאילתה **האמיתית** ולא לפונקציה: זיוף הפונקציה כך
    שתחזיר ``None`` היה עובר גם על הקוד הישן, כי שם ``None + 1`` זורק
    ``TypeError`` שנבלע — כלומר הבדיקה הייתה עוברת מסיבה שגויה.
    """
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    repo = _repo(db)

    for i in range(3):
        assert _save(repo, f"# v{i + 1}")
    assert _versions(db) == [1, 2, 3]

    coll = repo.manager.collection
    real = coll.find_one

    def failing(filter=None, *args, **kwargs):
        # רק שאילתת המספור נכשלת. היא היחידה שאינה מסננת ``is_active``,
        # וכך ``_fetch_latest_version`` ממשיך למצוא גרסה פעילה — בדיוק
        # התרחיש שבו הקוד הישן כותב מספר מתנגש.
        if isinstance(filter, dict) and "is_active" not in filter:
            raise RuntimeError("version lookup down")
        return real(filter, *args, **kwargs)

    coll.find_one = failing
    try:
        ok = _save(repo, "# חדש")
    finally:
        coll.find_one = real

    assert ok is False, "השמירה דיווחה הצלחה בלי מספר גרסה אמין"
    after = _versions(db)
    assert after == [1, 2, 3], f"נכתב מסמך למרות שהמספר לא היה ידוע: {after}"
    assert len(after) == len(set(after)), f"מספרי גרסה כפולים: {after}"


def test_the_version_lookup_does_not_load_the_file_body(wired_mongo):
    """שאלת "מה המספר הגבוה" נשאלת עם היטלה, ולא מושכת את הקובץ.

    בלי ההיטלה כל שמירה מושכת את המסמך המלא — **כולל** ``code`` — רק כדי
    לקרוא מספר אחד. זו הפרה של כלל ה-Smart Projection, והיא על המסלול
    החם ביותר.
    """
    db = wired_mongo.get_db()
    db.code_snippets.delete_many({})
    repo = _repo(db)
    assert _save(repo, "# " + "x" * 5000)

    # מרגלים על ההפניה ש-``repo`` מחזיק, ולא על ``db.code_snippets``:
    # ב-pymongo כל גישה לאטריביוט מייצרת אובייקט ``Collection`` חדש, ולכן
    # השמה עליו נדבקת לאובייקט חולף ולא נראית לקוד.
    coll = repo.manager.collection
    seen = []
    real = coll.find_one

    def spy(filter=None, *args, **kwargs):
        seen.append((filter, args, kwargs))
        return real(filter, *args, **kwargs)

    coll.find_one = spy
    try:
        assert _save(repo, "# עוד תוכן")
    finally:
        coll.find_one = real

    # מזהים את שאילתת המספור לפי **המסנן** ולא לפי מיקומה ברשימה או לפי
    # תוכן ההיטלה שלה: היא היחידה במסלול השמירה שאינה מסננת ``is_active``.
    # זה אותו סימן היכר שמשמש את הבדיקה שמזריקה כשל למעלה, והוא נשאר נכון
    # גם אם שאילתה אחרת במסלול תקבל היטלה משלה — למשל אם
    # ``_fetch_latest_version`` תתחיל לשלול שדות כבדים.
    numbering = [c for c in seen if isinstance(c[0], dict) and "is_active" not in c[0]]
    assert len(numbering) == 1, f"ציפינו לשאילתת מספור אחת: {[c[0] for c in seen]}"

    args = numbering[0][1]
    assert args and isinstance(args[0], dict), \
        f"שאילתת המספור רצה בלי היטלה: {numbering[0]}"
    projection = args[0]

    # ``version`` נבדק כטענה ולא כמסנן: מסנן היה מדלג בשקט על היטלה שהשתנתה
    # ומדווח "רצה בלי היטלה", שזו הודעה מטעה. וזה לבדו אינו מספיק — היטלה
    # כמו ``{"version": 1, "code": 1}`` הייתה עוברת ובכל זאת מושכת את הגוף,
    # ולכן הרשימה הכבדה נלקחת מהריפו עצמו ולא ממחרוזת קשיחה.
    from database.repository import HEAVY_FIELDS_EXCLUDE_PROJECTION

    assert projection.get("version") == 1, projection
    heavy = set(projection) & set(HEAVY_FIELDS_EXCLUDE_PROJECTION)
    assert not heavy, f"ההיטלה נוגעת בשדות כבדים: {sorted(heavy)} ← {projection}"


def test_the_index_for_the_version_lookup_is_created_by_production_code(wired_mongo):
    """האינדקס נוצר על ידי מסלול הייצור, ולא על ידי הבדיקה עצמה.

    גרסה ראשונה של הבדיקה קראה ל-``safe_create_index`` בעצמה ואז בדקה
    שהאינדקס קיים — כלומר יצרה את מה שבדקה, ועברה גם על הקוד שלפני
    התיקון. כאן מורץ ``_create_indexes`` האמיתי.

    ומול מונגו אמיתי בכוונה: ``create_index`` על סטאב מחזיר ``None``, וכל
    טענה על קיום אינדקס עוברת בו בלי קשר למה שקרה.
    """
    from database.manager import DatabaseManager

    db = wired_mongo.get_db()
    try:
        db.code_snippets.drop_index("idx_snippets_version_any_state")
    except Exception:
        pass

    mgr = DatabaseManager.__new__(DatabaseManager)
    mgr.db = db
    mgr.client = None
    DatabaseManager._create_indexes(mgr)

    info = db.code_snippets.index_information()
    assert "idx_snippets_version_any_state" in info, sorted(info)
    keys = [k for k, _ in info["idx_snippets_version_any_state"]["key"]]
    assert keys == ["user_id", "file_name", "version"], keys
