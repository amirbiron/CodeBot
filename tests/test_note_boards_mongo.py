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
