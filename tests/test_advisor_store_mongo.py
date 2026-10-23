"""האחסון של היועץ מול **מונגו אמיתי**: המכסה היומית, זיכרון השיחה והאינדקסים.

את אלה סטאב לא יכול לבדוק: שהמכסה נאכפת גם כשכמה בקשות מגיעות יחד (הדחייה
של ``_id`` כפול היא של השרת), סדר ומיון של מסמכים שנכתבו באותה מילישנייה,
ומה השרת באמת יצר מבקשת האינדקס. את המחיקה עצמה של ה-TTL הבדיקות לא ממתינות
לה: תהליך ה-TTL של השרת רץ פעם ב-60 שניות, ותקרת הבדיקה ב-``pytest.ini`` היא 60.

מתי הן רצות: כש-``NOTE_FONTS_TEST_MONGO_URI``, או ``MONGODB_URL`` כשהוא ריק,
מצביע לשרת נגיש — כמו ``test_recycle_bin_ttl_index_mongo.py``. כשאין שרת הן
מדלגות; כשיש שרת והחיבור נכשל מסיבה אחרת הן נכשלות. ראו ``mongo_client``.

**בטיחות מחיקה:** כל בדיקה עובדת על מסד עם שם ייחודי משלה, וה-teardown מוחק
רק מסד שמתחיל בתחילית שלמטה.
"""

from __future__ import annotations

import functools
import os
import threading
import types
import uuid
from datetime import datetime, timedelta, timezone

import pytest

pymongo = pytest.importorskip("pymongo")

from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

import advisor_collections  # noqa: E402
import database  # noqa: E402
from database.manager import DatabaseManager  # noqa: E402
from services import advisor_store  # noqa: E402

#: תחילית מסדי הבדיקה. ה-teardown מוחק **רק** מסד שמתחיל בה.
_TEST_DB_PREFIX = "codebot_advisor_it_"

_MONGO_URL = (
    os.environ.get("NOTE_FONTS_TEST_MONGO_URI") or os.environ.get("MONGODB_URL") or ""
).strip()

#: הדילוג ברמת המודול נשען על ה-ENV בלבד ואינו נוגע ברשת; הנגישות נבדקת ב-``mongo_client``.
pytestmark = pytest.mark.skipif(
    not _MONGO_URL,
    reason="דורש NOTE_FONTS_TEST_MONGO_URI או MONGODB_URL",
)


@pytest.fixture(scope="module")
def mongo_client():
    """לקוח מחובר, או דילוג — **רק** כשאין שרת בקצה השני (``ServerSelectionTimeoutError``).

    כל חריגה אחרת — אימות שגוי, ``mongodb+srv://`` שאינו נפתר — עולה ומכשילה. סיבת
    הדילוג אינה מצטטת את החריגה: הכתובת יכולה לשאת סיסמה (K13).
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
def mongo_db(mongo_client, monkeypatch):
    """מסד ייחודי, מחובר למנהל המסד שהמודול קורא ממנו — אותו מסלול כמו בייצור."""
    name = f"{_TEST_DB_PREFIX}{uuid.uuid4().hex[:12]}"
    db = mongo_client[name]
    monkeypatch.setattr(database.db, "db", db)
    try:
        yield db
    finally:
        # סורג בטיחות: מוחקים רק מסד שנוצר כאן
        if name.startswith(_TEST_DB_PREFIX):
            mongo_client.drop_database(name)


_NOW = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def test_daily_quota_holds_under_concurrent_requests(mongo_db, monkeypatch):
    """שש-עשרה בקשות באותו רגע, מכסה של חמש: בדיוק חמש מאושרות.

    רצות במקביל, בחוטים שמשתחררים יחד, כי בדיקה ברצף לא הייתה מגיעה לחלון שבין
    יצירת המסמך הראשון לבין הקריאה המקבילה שמנסה ליצור אותו שוב.
    """
    monkeypatch.setattr(advisor_store, "DAILY_QUESTION_LIMIT", 5)
    barrier = threading.Barrier(16)
    results: list[bool] = []
    errors: list[BaseException] = []

    def worker():
        barrier.wait()
        try:
            results.append(advisor_store.take_daily_question(42, now=_NOW))
        except BaseException as exc:  # noqa: BLE001 - הבדיקה מדווחת כל חריגה מחוט
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert errors == []
    assert sorted(results) == [False] * 11 + [True] * 5
    doc = mongo_db[advisor_collections.USAGE_COLLECTION].find_one({"_id": "42:2026-10-22"})
    assert doc["count"] == 5 and doc["user_id"] == 42 and doc["day"] == "2026-10-22"
    assert isinstance(doc["created_at"], datetime)  # שדה ה-TTL נשמר כתאריך, אחרת הוא לא פג


def test_quota_resets_at_israel_midnight_and_is_per_user(mongo_db, monkeypatch):
    monkeypatch.setattr(advisor_store, "DAILY_QUESTION_LIMIT", 1)
    before_midnight = datetime(2026, 10, 22, 20, 30, tzinfo=timezone.utc)  # 23:30 בישראל
    after_midnight = datetime(2026, 10, 22, 21, 30, tzinfo=timezone.utc)  # 00:30 בישראל
    assert advisor_store.take_daily_question(1, now=before_midnight) is True
    assert advisor_store.take_daily_question(1, now=before_midnight + timedelta(minutes=10)) is False
    assert advisor_store.take_daily_question(2, now=before_midnight) is True
    assert advisor_store.take_daily_question(1, now=after_midnight) is True


def test_history_returns_the_latest_exchanges_oldest_first(mongo_db):
    limit = 3
    for i in range(limit + 2):
        advisor_store.save_exchange(1, f"ש{i}", f"ת{i}", now=_NOW + timedelta(minutes=i))
    advisor_store.save_exchange(2, "של גולש אחר", "לא שלך", now=_NOW)

    history = advisor_store.get_history(1, limit, now=_NOW + timedelta(hours=1))
    expected_indexes = range(2, limit + 2)
    assert [m["content"] for m in history] == [x for i in expected_indexes for x in (f"ש{i}", f"ת{i}")]
    assert [m["role"] for m in history[:2]] == ["user", "assistant"]


def test_history_ties_on_the_same_timestamp_keep_insertion_order(mongo_db):
    """שתי שמירות באותה מילישנייה: ``_id`` שובר את השוויון, ולא הסדר שהשרת בחר."""
    for i in range(3):
        advisor_store.save_exchange(1, f"ש{i}", f"ת{i}", now=_NOW)
    history = advisor_store.get_history(1, 3, now=_NOW)
    assert [m["content"] for m in history if m["role"] == "user"] == ["ש0", "ש1", "ש2"]


def test_history_hides_exchanges_older_than_the_retention(mongo_db):
    """תהליך ה-TTL אינו מיידי, ולכן השאילתה עצמה לא מחזירה ישן."""
    days = advisor_collections.HISTORY_RETENTION_DAYS
    advisor_store.save_exchange(1, "ישנה", "ישנה", now=_NOW - timedelta(days=days, minutes=1))
    advisor_store.save_exchange(1, "חדשה", "חדשה", now=_NOW - timedelta(days=days - 1))
    assert [m["content"] for m in advisor_store.get_history(1, 5, now=_NOW)] == ["חדשה", "חדשה"]


def test_startup_creates_the_ttl_indexes_on_the_server(mongo_db):
    """מה השרת באמת יצר — ושעלייה שנייה מוצאת את אותו מצב."""
    fake = types.SimpleNamespace(db=mongo_db)
    create = functools.partial(DatabaseManager.safe_create_index, fake)
    for _ in range(2):
        results = DatabaseManager._create_advisor_indexes(fake, create)
        assert set(results.values()) == {True}

    history_indexes = {ix["name"]: ix for ix in mongo_db[advisor_collections.HISTORY_COLLECTION].list_indexes()}
    assert history_indexes["advisor_history_ttl"]["expireAfterSeconds"] == advisor_collections.HISTORY_RETENTION_DAYS * 86400
    assert dict(history_indexes["advisor_history_ttl"]["key"]) == {"created_at": 1}
    assert dict(history_indexes["advisor_history_user_recent"]["key"]) == {"user_id": 1, "created_at": -1, "_id": -1}
    usage_indexes = {ix["name"]: ix for ix in mongo_db[advisor_collections.USAGE_COLLECTION].list_indexes()}
    assert "expireAfterSeconds" in usage_indexes["advisor_daily_usage_ttl"]
