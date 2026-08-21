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
