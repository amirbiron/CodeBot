"""אינדקס ה-TTL של סל המיחזור — מול **מונגו אמיתי**, ולא מול stub.

הבדיקות ב-``test_recycle_bin_ttl_index.py`` מוכיחות שמסלול העלייה **מבקש**
את האינדקס. מה שהן לא יכולות להוכיח הוא מה שהשרת עושה עם הבקשה: האם הוא
מחזיר את המסנן החלקי בצורה ש-``is_recycle_bin_ttl_index`` מזהה, האם עלייה
שנייה היא no-op ולא הפלה-ובנייה בכל פעם, ומה קורה כשכבר יושב על השדה אינדקס
ישן. את אלה רק שרת עונה, ולכן הן כאן.

מה **לא** כאן: המחיקה עצמה. תהליך ה-TTL של השרת רץ פעם ב-60 שניות, ותקרת
הבדיקה ב-``pytest.ini`` היא 60. המחיקה אומתה ידנית מול mongod 8.0.32 עם
``ttlMonitorSleepSecs=1``, יחד עם ריצת בקרה על הקוד שלפני התיקון — ראו
תיאור ה-PR.

מתי הן רצות: כש-``NOTE_FONTS_TEST_MONGO_URI``, או ``MONGODB_URL`` כשהוא ריק,
מצביע לשרת נגיש. כשאין שם שרת הן מדלגות; כשיש שרת והחיבור נכשל מסיבה
אחרת — אימות, כתובת — הן נכשלות. ראו ``mongo_client``.

**בטיחות מחיקה:** כל בדיקה עובדת על מסד עם שם ייחודי משלה, וה-teardown מוחק
רק מסד שמתחיל בתחילית שלמטה.
"""

from __future__ import annotations

import functools
import os
import types
import uuid
from datetime import timezone

import pytest

pymongo = pytest.importorskip("pymongo")

from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

from database.manager import DatabaseManager  # noqa: E402
from file_deletion import is_recycle_bin_ttl_index  # noqa: E402

#: תחילית מסדי הבדיקה. ה-teardown מוחק **רק** מסד שמתחיל בה.
_TEST_DB_PREFIX = "codebot_recycle_ttl_it_"

_MONGO_URL = (
    os.environ.get("NOTE_FONTS_TEST_MONGO_URI") or os.environ.get("MONGODB_URL") or ""
).strip()

#: הדילוג ברמת המודול נשען על ה-ENV בלבד ואינו נוגע ברשת: בדיקת נגישות כאן
#: הייתה פותחת חיבור בכל איסוף של pytest, גם בהרצה שאינה כוללת את הקובץ.
#: הנגישות נבדקת ב-``mongo_client``, כשהבדיקות באמת עומדות לרוץ.
pytestmark = pytest.mark.skipif(
    not _MONGO_URL,
    reason="דורש NOTE_FONTS_TEST_MONGO_URI או MONGODB_URL",
)


@pytest.fixture(scope="module")
def mongo_client():
    """לקוח מחובר, או דילוג — **רק** כשאין שרת בקצה השני.

    ``ServerSelectionTimeoutError`` הוא "אין שרת", וכך גם מארח שאינו נפתר (הג'וב
    ``Unit Tests`` של ה-PR). כל חריגה אחרת עולה ומכשילה: אימות שגוי
    (``OperationFailure``), ``mongodb+srv://`` שאינו נפתר (``ConfigurationError``).
    דילוג עליהן היה מעלים בשקט את הבדיקות האלה, שהן ההוכחה היחידה מול שרת אמיתי
    — אותו כלל כמו ``_connect_or_skip`` ב-``test_profiler_projection_mongo.py``.
    נמדד מול pymongo 4.15.3, הגרסה שב-``requirements/base.txt``.

    סיבת הדילוג אינה מצטטת את החריגה: היא נגזרת מחיבור שהכתובת שלו יכולה לשאת
    סיסמה (K13).
    """
    client = pymongo.MongoClient(
        _MONGO_URL, serverSelectionTimeoutMS=2000, tz_aware=True, tzinfo=timezone.utc
    )
    try:
        client.admin.command("ping")
    except ServerSelectionTimeoutError:
        client.close()
        pytest.skip("אין שרת מונגו נגיש בכתובת שהוגדרה")
    except Exception:
        client.close()
        raise
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def mongo_db(mongo_client):
    name = f"{_TEST_DB_PREFIX}{uuid.uuid4().hex[:12]}"
    try:
        yield mongo_client[name]
    finally:
        # סורג בטיחות: מוחקים רק מסד שנוצר כאן
        if name.startswith(_TEST_DB_PREFIX):
            mongo_client.drop_database(name)


@pytest.fixture
def events(monkeypatch):
    """האירועים של ``safe_create_index`` — נלכדים ב-globals שהוא באמת קורא מהם,
    ולא דרך ``import database.manager``: בהרצה המלאה יכולים לחיות שני עותקים של
    המודול. ההסבר המלא — ב-fixture ``emitted`` שב-``test_recycle_bin_ttl_index.py``.
    """
    captured: list[tuple] = []
    monkeypatch.setitem(
        DatabaseManager.safe_create_index.__globals__,
        "emit_event",
        lambda event, severity="info", **fields: captured.append((event, severity, fields)),
    )
    return captured


def _startup(db) -> dict:
    """אותה פונקציה שמסלול העלייה קורא לה, עם ``safe_create_index`` האמיתי."""
    fake = types.SimpleNamespace(db=db)
    return DatabaseManager._create_recycle_bin_ttl_indexes(
        fake, functools.partial(DatabaseManager.safe_create_index, fake)
    )


def _ttl_indexes(db, collection: str) -> list[dict]:
    rows = [dict(row) for row in db[collection].list_indexes()]
    return [row for row in rows if is_recycle_bin_ttl_index(row)]


def test_the_server_keeps_the_index_in_the_shape_the_check_recognizes(mongo_db):
    """אם השרת היה מחזיר את המסנן בצורה אחרת, ``/admin/verify-indexes`` היה
    מדווח "חסר" על אינדקס תקין — וזו בדיוק אזעקת השווא שמלמדת להתעלם מאזעקות."""
    assert _startup(mongo_db) == {"code_snippets": True, "large_files": True}
    for collection in ("code_snippets", "large_files"):
        found = _ttl_indexes(mongo_db, collection)
        assert [row["name"] for row in found] == ["deleted_ttl"], collection


def test_a_second_startup_does_not_rebuild_the_index(mongo_db, events):
    """כל עלייה קוראת לזה. הפלה ובנייה מחדש בכל עלייה היו בנייה כפויה של אינדקס
    על כל הקולקציה, בכל דיפלוי — ותקלת החירום של ינואר (PR #2524) הייתה סביב
    בניות אינדקסים שנתקעו."""
    _startup(mongo_db)
    events.clear()
    assert _startup(mongo_db) == {"code_snippets": True, "large_files": True}
    assert not [e for e in events if e[0] == "db_index_dropped"]


def test_an_old_ttl_without_the_filter_is_brought_to_the_spec(mongo_db, events):
    """כך נוצר ``deleted_ttl`` עד היום — ב-PR #648 ובפקודה ``/recycle_backfill``."""
    mongo_db.code_snippets.create_index(
        "deleted_expires_at", expireAfterSeconds=0, name="deleted_ttl"
    )

    assert _startup(mongo_db)["code_snippets"] is True
    assert [row["name"] for row in _ttl_indexes(mongo_db, "code_snippets")] == ["deleted_ttl"]


def test_a_plain_index_on_the_field_does_not_block_the_ttl(mongo_db):
    """אינדקס רגיל על אותו שדה, בשם אחר, אינו מונע את ה-TTL: השרת מקבל
    אינדקס חלקי לצידו, והמחיקה עובדת דרכו.

    זו התנהגות של השרת ולא של הקוד, והיא נמדדה מול 8.0.32 — הגרסה של
    הפרודקשן ושל ``mongo:8.0`` ב-CI. מול שרת ישן יותר שמתנהג אחרת הבדיקה
    תיכשל, וזה הכשל הנכון: שם ה-TTL באמת לא היה נבנה.
    """
    mongo_db.code_snippets.create_index("deleted_expires_at")

    assert _startup(mongo_db)["code_snippets"] is True
    assert [row["name"] for row in _ttl_indexes(mongo_db, "code_snippets")] == ["deleted_ttl"]
