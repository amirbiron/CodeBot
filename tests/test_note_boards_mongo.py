"""בדיקות שרצות מול **מונגו אמיתי**, ולא מול stub.

מתי הן רצות: כש-``MONGODB_URL`` מוגדר והשרת נענה. ב-CI זה תמיד — הג'וב
``Unit Tests`` מרים ``mongo:6.0`` כשירות (ראו ``.github/workflows/ci.yml``).
מקומית הן מדלגות, כדי שהרצה רגילה תישאר מהירה.

**למה הן חייבות להתקיים בנפרד מבדיקות ה-stub**

יש דברים שסטאב לא יכול לבדוק — לא כי הוא לא מספיק טוב, אלא כי הם **אינם
בקוד**. הם התנהגות של המסד:

``one_default_per_user`` הוא אינדקס ייחודי-חלקי, והוא הדבר היחיד שסוגר את
המרוץ שבו שתי בקשות מקבילות מגלות שאין לוח ברירת מחדל ושתיהן יוצרות אחד.
הגנת קוד לבדה לא מספיקה שם — **המסד חייב לדחות**. אבל ה-stub שבבדיקות
מגדיר ``create_index`` שמחזיר ``None``, ויצירת האינדקס בפרודקשן עטופה
בשלוש שכבות של ``except Exception: pass``. כלומר: אם האינדקס לעולם לא
נוצר, **כל בדיקות ה-stub עוברות** והמרוץ פתוח לרווחה.

זה בדיוק הדפוס מ-``amir-bug-patterns``: כתיבה שהכשל שלה נבלע, ודיווח
הצלחה שנשען עליה.

**בטיחות מחיקה:** כל הרצה עובדת על מסד עם שם ייחודי משלה, וה-teardown
מוודא שהשם תואם לתחילית הצפויה לפני ``drop_database``. מסד שלא נוצר כאן
לא נמחק כאן.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

pymongo = pytest.importorskip("pymongo")

from pymongo.errors import DuplicateKeyError, ServerSelectionTimeoutError  # noqa: E402

#: תחילית מסדי הבדיקה. ה-teardown מוחק **רק** מסד שמתחיל בה.
_TEST_DB_PREFIX = "codebot_notes_it_"

_MONGO_URL = os.environ.get("MONGODB_URL", "").strip()


def _server_is_reachable(url: str) -> bool:
    """האם יש שרת בקצה השני. בלי זה הבדיקות היו נתלות עד timeout ארוך."""
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
    """מסד חד-פעמי, עם ``tz_aware=True`` בדיוק כמו בפרודקשן.

    ``tz_aware`` אינו פרט טכני: בלעדיו pymongo מחזיר ``datetime`` נאיבי,
    וההשוואה שמחליטה על 409 (``prev_dt < note['updated_at']``) זורקת
    ``TypeError`` — שנבלע ב-``except Exception``. כלומר בדיקת הקונקרנטיות
    הייתה מפסיקה לרוץ בשקט. יש על כך בדיקה בהמשך הקובץ.
    """
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
def indexed_db(mongo_db, monkeypatch):
    """מריץ את ``_ensure_indexes`` האמיתי מול המסד הזמני."""
    from webapp import sticky_notes_api

    monkeypatch.setattr(sticky_notes_api, "get_db", lambda: mongo_db)
    # הדגלים שמונעים בנייה כפולה — מאפסים כדי שהבנייה באמת תרוץ
    monkeypatch.setattr(sticky_notes_api, "_INDEX_READY", False, raising=False)
    monkeypatch.setattr(sticky_notes_api, "_INDEX_CACHE_LAST_CHECK", 0.0, raising=False)
    # ...וגם את הדגל **המשותף** ברדיס.
    #
    # ``_ensure_indexes`` יוצא מוקדם גם על ``_cache_flag_ready()``, שקורא דגל
    # מ-``cache_manager``. ב-CI רדיס פעיל (``REDIS_URL`` מוגדר בג'וב), ולכן דגל
    # שנשאר מהרצה קודמת היה הופך את הבנייה ל-no-op — והבדיקות כאן היו נופלות
    # על מסד ריק, מסיבה שאין לה שום קשר לקוד שנבדק.
    #
    # אירוניה קטנה: איפוס ``_INDEX_CACHE_LAST_CHECK`` ל-0 דווקא **פותח** את
    # הדלת לקריאת הקאש, כי הוא מבטל את חלון 30 השניות. שוחזר בפועל — בלי
    # השורה הבאה נוצרו אפס אינדקסים.
    monkeypatch.setattr(sticky_notes_api, "_cache_flag_ready", lambda: False, raising=False)

    sticky_notes_api._ensure_indexes()
    return mongo_db


# ---------- האינדקס שסוגר את המרוץ ----------


def test_the_unique_partial_index_is_actually_created(indexed_db):
    """``create_index`` שהחזיר בלי לזרוק אינו ראיה שהאינדקס קיים.

    זו הבדיקה היחידה בריפו שקוראת את האינדקס בחזרה מהמסד. עד היום היצירה
    עטופה ב-``except Exception: pass``, ולכן כשל היה שקט לחלוטין.
    """
    info = indexed_db.note_boards.index_information()

    assert "one_default_per_user" in info, f"האינדקס לא נוצר. קיימים: {sorted(info)}"
    spec = info["one_default_per_user"]
    assert spec.get("unique") is True, f"האינדקס אינו ייחודי: {spec}"
    assert spec.get("partialFilterExpression") == {"is_default": True}, (
        f"ה-partialFilterExpression אינו כמצופה: {spec.get('partialFilterExpression')}"
    )


def test_a_second_default_board_is_rejected_by_the_database(indexed_db):
    """**זה כל תפקידו של האינדקס.**

    שתי בקשות מקבילות יכולות שתיהן לגלות שאין לוח ברירת מחדל. הקוד לבדו
    לא יכול למנוע את זה — רק המסד יכול, ורק אם האינדקס באמת שם.
    """
    boards = indexed_db.note_boards
    boards.insert_one({"user_id": 7, "name": "לוח עבודה", "is_default": True})

    with pytest.raises(DuplicateKeyError):
        boards.insert_one({"user_id": 7, "name": "עוד ברירת מחדל", "is_default": True})

    assert boards.count_documents({"user_id": 7, "is_default": True}) == 1


def test_the_index_does_not_block_ordinary_boards(indexed_db):
    """האילוץ חל רק על ``is_default: True``.

    בלי ה-``partialFilterExpression`` האינדקס היה ייחודי על ``user_id``
    לבדו — כלומר משתמש היה יכול להחזיק **לוח אחד בסך הכל**. תקלה חמורה
    בהרבה מזו שהוא בא למנוע, ולכן היא נבדקת במפורש.
    """
    boards = indexed_db.note_boards
    boards.insert_one({"user_id": 7, "name": "ברירת מחדל", "is_default": True})

    boards.insert_one({"user_id": 7, "name": "לוח שני", "is_default": False})
    boards.insert_one({"user_id": 7, "name": "לוח שלישי"})  # בלי השדה כלל

    assert boards.count_documents({"user_id": 7}) == 3


def test_another_user_may_have_their_own_default(indexed_db):
    """האילוץ הוא לכל משתמש, לא גלובלי."""
    boards = indexed_db.note_boards
    boards.insert_one({"user_id": 7, "name": "של שבע", "is_default": True})
    boards.insert_one({"user_id": 99, "name": "של תשעים ותשע", "is_default": True})

    assert boards.count_documents({"is_default": True}) == 2


# ---------- אינדקסים של הפתקים ----------


def test_board_notes_index_exists_and_is_used(indexed_db):
    """אינדקס שקיים ואינו בשימוש שווה לאינדקס שלא קיים.

    ``explain`` הוא הדרך היחידה לדעת. סטאב מחזיר תוצאה נכונה גם כששאילתה
    סורקת את כל האוסף.
    """
    notes = indexed_db.sticky_notes
    assert "user_board_idx" in notes.index_information()

    notes.insert_many([{"user_id": 7, "board_id": f"b{i}", "content": "x"} for i in range(50)])
    plan = notes.find({"user_id": 7, "board_id": "b3"}).explain()

    stage = plan["queryPlanner"]["winningPlan"]
    flat = str(stage)
    assert "IXSCAN" in flat, f"השאילתה סורקת את כל האוסף: {flat[:300]}"
    assert "user_board_idx" in flat, f"נבחר אינדקס אחר: {flat[:300]}"


# ---------- סמנטיקה של BSON שהסטאב לא רואה ----------


def test_updated_at_round_trips_timezone_aware(mongo_db):
    """בלי ``tz_aware`` ההשוואה שמחליטה על 409 זורקת TypeError — ונבלעת.

    ה-stub מחזיק אובייקט ``datetime`` של פייתון, ולכן הוא **תמיד** aware.
    רק מונגו אמיתי יכול להראות את זה.
    """
    coll = mongo_db.sticky_notes
    written = datetime.now(timezone.utc)
    coll.insert_one({"_id": 1, "updated_at": written})

    read_back = coll.find_one({"_id": 1})["updated_at"]

    assert read_back.tzinfo is not None, "מונגו החזיר datetime נאיבי — ההשוואה ל-409 תזרוק"
    # וההשוואה עצמה, זו שרצה בפועל ב-``update_note``, לא זורקת
    assert (written < read_back) in (True, False)


def test_mongo_truncates_datetime_to_milliseconds(mongo_db):
    """BSON שומר מילישניות, פייתון יוצר מיקרו-שניות.

    התיעוד של ההתנהגות הזו הוא הערך של הבדיקה: התשובה ל-API מחזירה את
    הערך **שבזיכרון** (עם מיקרו-שניות), בעוד שהמסד מחזיק ערך קטום. שתי
    חותמות שנראות זהות אינן בהכרח שוות.
    """
    coll = mongo_db.sticky_notes
    written = datetime(2026, 8, 21, 6, 28, 12, 690976, tzinfo=timezone.utc)
    coll.insert_one({"_id": 1, "updated_at": written})

    read_back = coll.find_one({"_id": 1})["updated_at"]

    assert read_back.microsecond == 690000, f"ציפיתי לקטימה למילישניות, קיבלתי {read_back.microsecond}"
    assert read_back < written, "הערך שבמסד קטן או שווה לזה שנשלח"


# ---------- ה-aggregation של מוני הפתקים ----------


def test_note_count_aggregation_runs_on_real_mongo(indexed_db):
    """ה-stub מבין רק את הצורה המדויקת שכתבתי ביד.

    צינור עם שגיאת תחביר אמיתית היה עובר שם ונופל רק בפרודקשן.
    """
    notes = indexed_db.sticky_notes
    notes.insert_many([
        {"user_id": 7, "board_id": "b1"},
        {"user_id": 7, "board_id": "b1"},
        {"user_id": 7, "board_id": "b2"},
        {"user_id": 99, "board_id": "b1"},   # משתמש אחר — לא נספר
        {"user_id": 7, "file_id": "f1"},     # פתק קובץ — אין לו board_id
    ])

    rows = list(notes.aggregate([
        {"$match": {"user_id": 7, "board_id": {"$in": ["b1", "b2"]}}},
        {"$group": {"_id": "$board_id", "n": {"$sum": 1}}},
    ]))

    counts = {row["_id"]: row["n"] for row in rows}
    assert counts == {"b1": 2, "b2": 1}


# ---------- כלי ה-MCP ללוחות ----------
#
# ה-handlers נבדקים מול stub בקובץ ``test_mcp_notes_handlers.py``. מה שאי
# אפשר לבדוק שם הוא **בעלות** — היא נשענת על שאילתה למסד — ו**תקרה שנכשלת**,
# שדורשת אוסף אמיתי שאפשר להפיל בו את הספירה.


@pytest.fixture
def mcp_backend(mongo_db):
    """``ProductionBackend`` אמיתי מול המסד הזמני, בלי ה-``__init__`` הכבד."""
    from mcp_server.backend import ProductionBackend

    backend = ProductionBackend.__new__(ProductionBackend)
    backend._notes_idx_done = True          # מדלגים על בניית אינדקסים חד-פעמית
    backend._raw_mongo = lambda: mongo_db
    backend._notes_coll = lambda: mongo_db.sticky_notes
    return backend


def _make_board(db, user_id: int, name: str = "לוח", is_default: bool = False) -> str:
    from bson import ObjectId

    oid = ObjectId()
    db.note_boards.insert_one({"_id": oid, "user_id": user_id, "name": name, "is_default": is_default, "order": 0})
    return str(oid)


def test_a_board_of_another_user_is_not_readable(mcp_backend, mongo_db):
    """**זו הבדיקה שלא ניתן לכתוב מול stub.**

    ``board_id`` שרירותי לא מחזיר רשימה ריקה אלא ``board_not_found`` — ההבדל
    חשוב: רשימה ריקה אומרת "הלוח שלך ריק", וזה שקר.
    """
    foreign = _make_board(mongo_db, user_id=99, name="של מישהו אחר")
    mongo_db.sticky_notes.insert_one({"user_id": 99, "board_id": foreign, "content": "סוד"})

    res = mcp_backend.list_board_notes(7, board_id=foreign)

    assert res == {"ok": False, "error": "board_not_found"}


def test_creating_on_a_foreign_board_is_refused(mcp_backend, mongo_db):
    foreign = _make_board(mongo_db, user_id=99)
    before = mongo_db.sticky_notes.count_documents({})

    res = mcp_backend.create_board_note(7, board_id=foreign, content="נסיון", color="#FFFFCC", mode="surface")

    assert res == {"ok": False, "error": "board_not_found"}
    assert mongo_db.sticky_notes.count_documents({}) == before, "לא נוצר פתק"


def test_create_and_read_back_a_board_note(mcp_backend, mongo_db):
    """``ok: True`` אינו ראיה — קוראים את המסמך מהמסד."""
    board = _make_board(mongo_db, user_id=7)

    res = mcp_backend.create_board_note(7, board_id=board, content="פתק מ-MCP", color="#FFFFCC", mode="screen")
    assert res["ok"] is True

    doc = mongo_db.sticky_notes.find_one({"user_id": 7, "board_id": board})
    assert doc is not None, "הפתק לא הגיע למסד"
    assert doc["content"] == "פתק מ-MCP"
    assert doc["mode"] == "screen"
    assert "file_id" not in doc and "scope_id" not in doc, "פתק לוח אינו נושא יעד קובץ"

    listed = mcp_backend.list_board_notes(7, board_id=board)
    assert listed["count"] == 1
    assert listed["notes"][0]["board_id"] == board


def test_the_quota_rejects_when_the_count_fails(mcp_backend, mongo_db, monkeypatch):
    """כשל ספירה → **דחייה**, לא מעבר.

    זו סטייה מכוונת מ-``create_note`` של הקובץ, שם כשל ספירה מעביר את
    היצירה (soft-cap). תקרה שנפתחת לרווחה בדיוק כשהמסד מתקשה היא לא תקרה.
    """
    board = _make_board(mongo_db, user_id=7)

    class _Broken:
        def __getattr__(self, name):
            return getattr(mongo_db.sticky_notes, name)

        def count_documents(self, *_a, **_k):
            raise RuntimeError("count failed")

    monkeypatch.setattr(mcp_backend, "_notes_coll", lambda: _Broken())

    res = mcp_backend.create_board_note(7, board_id=board, content="x", color="#FFFFCC", mode="surface")

    assert res["ok"] is False
    assert res["error"] == "note_quota_unknown"
    assert mongo_db.sticky_notes.count_documents({"board_id": board}) == 0


def test_the_board_quota_is_enforced(mcp_backend, mongo_db, monkeypatch):
    import sticky_notes_target

    monkeypatch.setattr(sticky_notes_target, "MAX_NOTES_PER_BOARD", 1)
    board = _make_board(mongo_db, user_id=7)
    mongo_db.sticky_notes.insert_one({"user_id": 7, "board_id": board, "content": "ראשון"})

    res = mcp_backend.create_board_note(7, board_id=board, content="שני", color="#FFFFCC", mode="surface")

    assert res["error"] == "too_many_notes"
    assert res["max"] == 1
    assert mongo_db.sticky_notes.count_documents({"board_id": board}) == 1


def test_list_boards_creates_the_default_and_counts_notes(mcp_backend, mongo_db):
    board = _make_board(mongo_db, user_id=7, name="ידני")
    mongo_db.sticky_notes.insert_many([
        {"user_id": 7, "board_id": board, "content": "a"},
        {"user_id": 7, "board_id": board, "content": "b"},
        {"user_id": 99, "board_id": board, "content": "של אחר"},   # לא נספר
    ])

    res = mcp_backend.list_boards(7)

    assert res["ok"] is True
    by_name = {b["name"]: b for b in res["boards"]}
    assert "ידני" in by_name
    assert by_name["ידני"]["note_count"] == 2, "המונה סופר רק את הפתקים של המשתמש"
    # לוח ברירת המחדל נוצר אוטומטית בקריאה הראשונה
    assert any(b["is_default"] for b in res["boards"]), f"אין ברירת מחדל: {res['boards']}"


def test_uppercase_board_id_does_not_orphan_the_note(mcp_backend, mongo_db):
    """**באג שנתפס בריוויו ושוחזר.**

    ``ObjectId`` מקבל גם הקסה גדולה, אבל ``str(ObjectId)`` תמיד קטנה — וזה
    מה שהוובאפ שומר ומחפש לפיו. פתק שנוצר עם מזהה באותיות גדולות נשמר כך,
    ו**נעלם מהלוח**: הוובאפ מחפש באותיות קטנות ולא מוצא כלום.

    התיקון: המזהה הקנוני מגיע מ-``board["_id"]`` ולא ממה שהקורא הקליד.
    """
    from mcp_server import handlers as _mh

    board = _make_board(mongo_db, user_id=7)
    upper = board.upper()
    assert upper != board, "המזהה חייב להכיל אותיות כדי שהבדיקה תהיה משמעותית"

    res = _mh.create_board_note(mcp_backend, 7, board_id=upper, content="פתק")
    assert res["ok"] is True

    doc = mongo_db.sticky_notes.find_one({"user_id": 7})
    assert doc["board_id"] == board, "נשמר בצורה שהוובאפ לא ימצא"
    # והצד השני: קריאה באותיות קטנות מוצאת אותו
    assert _mh.list_board_notes(mcp_backend, 7, board_id=board)["count"] == 1


def test_note_count_tells_zero_apart_from_unknown(mcp_backend, mongo_db, monkeypatch):
    """``0`` הוא "ידוע שריק"; ``None`` הוא "הספירה נכשלה".

    ערבוב ביניהם גורם למשתמש להאמין שאיבד פתקים.
    """
    _make_board(mongo_db, user_id=7, name="ריק")

    ok = mcp_backend.list_boards(7)
    assert all(b["note_count"] == 0 for b in ok["boards"]), f"לוח ריק אינו 'לא ידוע': {ok['boards']}"

    class _NoAggregate:
        def __getattr__(self, name):
            return getattr(mongo_db.sticky_notes, name)

        def aggregate(self, *_a, **_k):
            raise RuntimeError("aggregate failed")

    monkeypatch.setattr(mcp_backend, "_notes_coll", lambda: _NoAggregate())
    unknown = mcp_backend.list_boards(7)
    assert all(b["note_count"] is None for b in unknown["boards"]), "כשל ספירה חייב להיות None"


def test_default_board_failure_is_reported_not_swallowed(mcp_backend, mongo_db, monkeypatch):
    """כשל ביצירת לוח ברירת המחדל אינו נבלע בשקט.

    בלי דיווח, משתמש נשאר בלי לוח ברירת מחדל ואיש לא יודע למה.
    """
    import note_boards

    monkeypatch.setattr(note_boards, "ensure_default_board",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("boom")))

    res = mcp_backend.list_boards(7)

    assert res["ok"] is True, "רשימה חלקית עדיפה על כלי שנופל"
    assert res.get("default_board_error") == "RuntimeError"


def test_admin_is_exempt_from_the_board_quota(mcp_backend, mongo_db, monkeypatch):
    """אותה מדיניות כמו בוובאפ. בלעדיה אדמין פטור בדפדפן ונחסם ב-MCP."""
    import sticky_notes_target
    import user_roles

    monkeypatch.setattr(sticky_notes_target, "MAX_NOTES_PER_BOARD", 1)
    board = _make_board(mongo_db, user_id=7)
    mongo_db.sticky_notes.insert_one({"user_id": 7, "board_id": board, "content": "ראשון"})

    # לא אדמין → נחסם
    monkeypatch.setattr(user_roles, "is_admin", lambda uid: False)
    blocked = mcp_backend.create_board_note(7, board_id=board, content="שני", color="#FFFFCC", mode="surface")
    assert blocked["error"] == "too_many_notes"

    # אדמין → עובר
    monkeypatch.setattr(user_roles, "is_admin", lambda uid: True)
    allowed = mcp_backend.create_board_note(7, board_id=board, content="שני", color="#FFFFCC", mode="surface")
    assert allowed["ok"] is True, allowed
    assert mongo_db.sticky_notes.count_documents({"board_id": board}) == 2


# ---------- שם ייחודי לפתק בתוך לוח ----------
#
# שם מזהה פתק אחד בתוך לוח, בדיוק כמו ששם קובץ מזהה קובץ אחד. האכיפה היא
# במסד ולא בקוד, ולכן היא נבדקת כאן ולא מול stub.


def test_the_title_index_is_created_with_the_right_partial_filter(indexed_db):
    """``$ne`` **אינו נתמך** ב-``partialFilterExpression``.

    נבדק מול מונגו 7.0 ונדחה ב-``Error in specification``; ``$exists`` נתמך.
    לכן פתק בלי שם משמיט את השדה במקום לשמור ``""`` — שני פתקים עם מחרוזת
    ריקה היו מתנגשים זה בזה.

    ההשוואה היא מול :data:`ONE_TITLE_PER_BOARD_INDEX` ולא מול מילון מוקלד
    כאן: מפרט שכתוב פעמיים הוא מפרט שיתפצל, וזו בדיוק הדרך שבה ``board_id``
    נשמט מהפילטר מלכתחילה.
    """
    from sticky_notes_target import ONE_TITLE_PER_BOARD_INDEX as WANT

    info = indexed_db.sticky_notes.index_information()

    assert WANT["name"] in info, f"האינדקס לא נוצר. קיימים: {sorted(info)}"
    spec = info[WANT["name"]]
    assert spec.get("unique") is True
    assert spec.get("partialFilterExpression") == WANT["partialFilterExpression"]
    assert [(f, v) for f, v in spec["key"]] == WANT["keys"]


def test_two_notes_cannot_share_a_title_on_one_board(indexed_db):
    notes = indexed_db.sticky_notes
    notes.insert_one({"user_id": 7, "board_id": "b1", "title": "טודו", "content": "a"})

    with pytest.raises(DuplicateKeyError):
        notes.insert_one({"user_id": 7, "board_id": "b1", "title": "טודו", "content": "b"})


def test_the_same_title_is_free_on_another_board_and_for_another_user(indexed_db):
    notes = indexed_db.sticky_notes
    notes.insert_one({"user_id": 7, "board_id": "b1", "title": "טודו", "content": "a"})

    notes.insert_one({"user_id": 7, "board_id": "b2", "title": "טודו", "content": "b"})
    notes.insert_one({"user_id": 99, "board_id": "b1", "title": "טודו", "content": "c"})

    assert notes.count_documents({"title": "טודו"}) == 3


def test_notes_without_a_title_are_unaffected(indexed_db):
    """**זה מה שהאינדקס היה שובר אילו נבנה בלי הפילטר החלקי.**

    רוב הפתקים הם בלי שם, וללא ה-``partialFilterExpression`` המשתמש היה
    יכול להחזיק פתק אחד בלבד ללא שם בכל לוח.
    """
    notes = indexed_db.sticky_notes

    for i in range(5):
        notes.insert_one({"user_id": 7, "board_id": "b1", "content": f"בלי שם {i}"})
    for i in range(3):
        notes.insert_one({"user_id": 7, "file_id": "f1", "content": f"פתק קובץ {i}"})

    assert notes.count_documents({"user_id": 7}) == 8


def test_clearing_a_title_removes_the_field(indexed_db):
    """שם ריק **מוחק** את השדה ולא שומר ``""``.

    בלי זה, שני פתקים ששמם נוקה היו מתנגשים — שניהם ``title: ""`` והאינדקס
    כולל אותם, כי ``$exists`` מתקיים גם למחרוזת ריקה.
    """
    notes = indexed_db.sticky_notes
    notes.insert_one({"_id": 1, "user_id": 7, "board_id": "b1", "title": "ראשון"})
    notes.insert_one({"_id": 2, "user_id": 7, "board_id": "b1", "title": "שני"})

    notes.update_one({"_id": 1}, {"$unset": {"title": ""}})
    notes.update_one({"_id": 2}, {"$unset": {"title": ""}})

    assert notes.count_documents({"user_id": 7, "board_id": "b1"}) == 2
    assert "title" not in notes.find_one({"_id": 1})


def test_mcp_refuses_a_duplicate_title(mcp_backend, mongo_db, indexed_db):
    """הכלי מחזיר ``duplicate_title`` ולא קורס על החריגה."""
    board = _make_board(mongo_db, user_id=7)
    ok = mcp_backend.create_board_note(7, board_id=board, content="a", color="#FFFFCC", mode="surface", title="טודו")
    assert ok["ok"] is True

    dup = mcp_backend.create_board_note(7, board_id=board, content="b", color="#FFFFCC", mode="surface", title="טודו")

    assert dup == {"ok": False, "error": "duplicate_title"}
    assert mongo_db.sticky_notes.count_documents({"board_id": board}) == 1


def test_two_file_notes_may_share_a_title(indexed_db):
    """**הבאג שהאינדקס ייצר, ולא מנע.**

    האינדקס הוא ``(user_id, board_id, title)``, ולפתק **קובץ** אין
    ``board_id`` כלל. עם פילטר שמסתכל על ``title`` בלבד, כל פתקי הקבצים
    נכנסים אליו עם אותו ערך מפתח חסר — ושני קבצים שונים עם אותו שם פתק
    נדחים ב-E11000. נמדד מול מונגו 7.0.14 לפני התיקון: ההוספה השנייה
    נכשלה.

    זו גם ההתנהגות שנקבעה במפורש: בקבצים אותו שם הוא גרסה נוספת, לא
    התנגשות. הייחודיות היא **בתוך לוח**, ולכן ``board_id`` חייב להיות
    בפילטר.

    נופלת בלי ``board_id`` ב-``partialFilterExpression``.
    """
    notes = indexed_db.sticky_notes

    notes.insert_one({"user_id": 7, "file_id": "f1", "title": "רשימת מטלות"})
    notes.insert_one({"user_id": 7, "file_id": "f2", "title": "רשימת מטלות"})
    # וגם שניים על **אותו** קובץ — שם אינו מזהה ייחודי בעולם הקבצים
    notes.insert_one({"user_id": 7, "file_id": "f1", "title": "רשימת מטלות"})

    assert notes.count_documents({"user_id": 7, "title": "רשימת מטלות"}) == 3


def test_the_old_index_name_is_superseded_without_losing_uniqueness(indexed_db):
    """**זה מסלול השדרוג האמיתי בפרודקשן — והבדיקה שלו היא על הסדר.**

    מונגו אינו יודע לשנות שם של אינדקס, ואינדקס בשם קיים עם אפשרויות
    שונות נדחה ב-``code 86``. עדכון "במקום" מחייב אפוא להפיל ואז לבנות,
    ובין השניים אין ייחודיות כלל — ושתי בקשות מקבילות יכולות להכניס שני
    שמות זהים לאותו לוח, ואז הבנייה החדשה נכשלת והאכיפה נשארת מושבתת.

    השם הממוספר הופך את הסדר: בונים את החדש, ורק אז מפילים את הישן.
    הבדיקה עוקבת אחרי **כל** פעולת אינדקס ומוודאת שהייחודיות נאכפה גם
    אחריה. נופלת אם ההפלה מקדימה את הבנייה.
    """
    from sticky_notes_target import ONE_TITLE_PER_BOARD_INDEX as WANT
    from sticky_notes_target import SUPERSEDED_TITLE_INDEX_NAMES, ensure_title_index

    notes = indexed_db.sticky_notes
    old_name = SUPERSEDED_TITLE_INDEX_NAMES[0]
    notes.drop_index(WANT["name"])
    notes.create_index(
        [("user_id", 1), ("board_id", 1), ("title", 1)],
        name=old_name, unique=True, partialFilterExpression={"title": {"$exists": True}},
    )

    def uniqueness_is_live() -> bool:
        notes.delete_many({"user_id": 4242})
        notes.insert_one({"user_id": 4242, "board_id": "b", "title": "בדיקה"})
        try:
            notes.insert_one({"user_id": 4242, "board_id": "b", "title": "בדיקה"})
            live = False
        except DuplicateKeyError:
            live = True
        notes.delete_many({"user_id": 4242})
        return live

    seen = []

    class _Watched:
        """עוטף את האוסף ובודק אכיפה אחרי כל פעולת אינדקס."""

        def index_information(self):
            return notes.index_information()

        def create_index(self, *a, **k):
            out = notes.create_index(*a, **k)
            seen.append((f"create {k.get('name')}", uniqueness_is_live()))
            return out

        def drop_index(self, name):
            out = notes.drop_index(name)
            seen.append((f"drop {name}", uniqueness_is_live()))
            return out

    assert ensure_title_index(_Watched()) is True

    assert seen, "לא בוצעה שום פעולת אינדקס — השדרוג לא רץ"
    gaps = [step for step, live in seen if not live]
    assert not gaps, f"היה רגע בלי ייחודיות אחרי: {gaps} (הרצף: {seen})"

    info = notes.index_information()
    assert WANT["name"] in info
    assert old_name not in info, "האינדקס הישן שרד — שני אינדקסים על אותם מפתחות"


def test_the_title_index_upgrades_an_older_version_of_itself(indexed_db):
    """**בלי היישוב הזה התיקון לא מגיע לפרודקשן.**

    בפרודקשן כבר יושב האינדקס עם הפילטר הישן. מונגו דוחה יצירה מחדש של
    אינדקס בשם קיים עם אפשרויות שונות — ``code 86``, נמדד — והדחייה
    נבלעת ב-``except Exception``. כלומר בלי ההפלה-ובנייה, הקוד היה
    מתעדכן וההתנהגות לא.

    נופלת אם ``ensure_title_index`` רק יוצר ולא משווה.
    """
    from sticky_notes_target import ONE_TITLE_PER_BOARD_INDEX, ensure_title_index

    notes = indexed_db.sticky_notes
    name = ONE_TITLE_PER_BOARD_INDEX["name"]

    # משחזרים את המצב שבשדה: אותו שם, פילטר ישן
    notes.drop_index(name)
    notes.create_index(
        [("user_id", 1), ("board_id", 1), ("title", 1)],
        name=name, unique=True, partialFilterExpression={"title": {"$exists": True}},
    )
    assert notes.index_information()[name]["partialFilterExpression"] == {"title": {"$exists": True}}

    assert ensure_title_index(notes) is True

    assert (
        notes.index_information()[name]["partialFilterExpression"]
        == ONE_TITLE_PER_BOARD_INDEX["partialFilterExpression"]
    )
    # ולראיה שההתנהגות באמת השתנתה, ולא רק המפרט
    notes.insert_one({"user_id": 7, "file_id": "f1", "title": "אחרי שדרוג"})
    notes.insert_one({"user_id": 7, "file_id": "f2", "title": "אחרי שדרוג"})
    assert notes.count_documents({"title": "אחרי שדרוג"}) == 2


# ---------- היעד השלישי: פתקי ריפו, מול מסד אמיתי ----------
#
# מה שסטאב לא יכול לבדוק כאן: הפילטר החלקי של האינדקס. ``create_index``
# ב-stub מחזיר ``None``, ולכן **כל** בדיקת כפילות עוברת בו — גם אם האינדקס
# מעולם לא נוצר. רק מסד אמיתי מחזיר E11000.


def test_repo_title_index_is_created_by_ensure_indexes(indexed_db):
    """``_ensure_indexes`` האמיתי בונה גם את אינדקס הריפו, לא רק את זה של הלוח."""
    names = set(indexed_db.sticky_notes.index_information().keys())
    assert "one_title_per_repo_file_v1" in names
    assert "user_repo_idx" in names


def test_repo_note_duplicate_title_rejected(indexed_db):
    """שם כפול על אותו קובץ בריפו נדחה — **על ידי המסד**.

    נופלת בלי ``ONE_TITLE_PER_REPO_FILE_INDEX``: בלעדיו פתקי ריפו נופלים
    מחוץ לאינדקס הלוח (שהפילטר שלו דורש ``board_id``) ומקבלים אפס
    ייחודיות שם, בשקט.
    """
    from sticky_notes_target import build_note_target

    base = {"user_id": 7, "content": "x", "title": "לבדוק"}
    target = build_note_target(repo_name="CodeBot", repo_path="webapp/app.py")
    indexed_db.sticky_notes.insert_one({**base, **target})

    with pytest.raises(DuplicateKeyError):
        indexed_db.sticky_notes.insert_one({**base, **target})


def test_same_title_on_a_different_file_or_repo_is_allowed(indexed_db):
    """הייחודיות היא פר-קובץ, לא פר-ריפו ולא גלובלית."""
    from sticky_notes_target import build_note_target

    base = {"user_id": 7, "content": "x", "title": "לבדוק"}
    indexed_db.sticky_notes.insert_one(
        {**base, **build_note_target(repo_name="CodeBot", repo_path="webapp/app.py")}
    )
    indexed_db.sticky_notes.insert_one(
        {**base, **build_note_target(repo_name="CodeBot", repo_path="webapp/other.py")}
    )
    indexed_db.sticky_notes.insert_one(
        {**base, **build_note_target(repo_name="OtherRepo", repo_path="webapp/app.py")}
    )
    assert indexed_db.sticky_notes.count_documents({"title": "לבדוק"}) == 3


def test_unnormalized_path_collides_with_its_normalized_form(indexed_db):
    """**הנורמליזציה היא מה שמגן על הייחודיות עצמה.**

    בלעדיה ``docs/x.rst`` ו-``/docs//x.rst`` הם שני מפתחות שונים באינדקס,
    והייחודיות פשוט לא נאכפת ביניהם — שני פתקים עם אותו שם על אותו קובץ.

    נופלת אם ``build_note_target`` מפסיק לנרמל בכתיבה.
    """
    from sticky_notes_target import build_note_target

    base = {"user_id": 7, "content": "x", "title": "לבדוק"}
    indexed_db.sticky_notes.insert_one(
        {**base, **build_note_target(repo_name="CodeBot", repo_path="docs/x.rst")}
    )
    with pytest.raises(DuplicateKeyError):
        indexed_db.sticky_notes.insert_one(
            {**base, **build_note_target(repo_name="CodeBot", repo_path="/docs//x.rst")}
        )


def test_file_and_board_notes_stay_outside_the_repo_index(indexed_db):
    """פתקי קובץ/לוח אין להם ``repo_path``, ולכן הפילטר החלקי מדיר אותם.

    בלי ``repo_path`` בפילטר, כולם היו נכנסים לאינדקס עם ערך חסר, חולקים
    מפתח, ושני פתקים על שני קבצים שונים עם אותו שם היו נדחים ב-E11000 —
    בדיוק התקלה שתוקנה פעם באינדקס הלוח.
    """
    from sticky_notes_target import build_note_target

    base = {"user_id": 7, "content": "x", "title": "שם זהה"}
    indexed_db.sticky_notes.insert_one({**base, **build_note_target(file_id="f1")})
    indexed_db.sticky_notes.insert_one({**base, **build_note_target(file_id="f2")})
    assert indexed_db.sticky_notes.count_documents({"title": "שם זהה"}) == 2


def test_repo_filter_finds_the_note_written_unnormalized(indexed_db):
    """שני הקצוות מתכנסים — מול מסד אמיתי, לא מול השוואת מילונים."""
    from sticky_notes_target import build_note_target, repo_notes_filter

    indexed_db.sticky_notes.insert_one({
        "user_id": 7, "content": "x",
        **build_note_target(repo_name="CodeBot", repo_path="/docs//guide.rst"),
    })
    for lookup in ("docs/guide.rst", "/docs//guide.rst", "./docs/guide.rst"):
        assert indexed_db.sticky_notes.count_documents(
            repo_notes_filter(7, "CodeBot", lookup)
        ) == 1, lookup
