"""המתנה שגדלה בין ניסיונות, ומועד שהמשתמש קבע בזמן גיבוי — מול **מונגו אמיתי**, ולא מול stub.

``tests/test_webapp_backup_retry_backoff.py`` בודק את הרצף מעל ``_fake_mongo``. כאן אותו רצף מול שרת: התפיסה (``find_one_and_update``) מחזירה את המסמך שלפני העדכון, כך שהמונה נקרא ממנו כמו שהוא; ``$set`` על נתיב עם נקודה כותב לתוך ההעדפות; והכתיבה המותנית בסנטינל (``_finish_claim``) לא תואמת מסמך שבו המשתמש שינה את המועד.

מתי הן רצות: כש-``NOTE_FONTS_TEST_MONGO_URI``, או ``MONGODB_URL`` כשהוא ריק, מצביע לשרת נגיש. כשאין שם שרת הן מדלגות; כשיש שרת והחיבור נכשל מסיבה אחרת הן נכשלות (``mongo_client``, כמו ב-``tests/test_recycle_bin_ttl_index_mongo.py``).

**בטיחות מחיקה:** כל בדיקה עובדת על מסד עם שם ייחודי משלה, וה-teardown מוחק רק מסד שמתחיל בתחילית שלמטה.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pymongo = pytest.importorskip("pymongo")

from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

#: תחילית מסדי הבדיקה. ה-teardown מוחק **רק** מסד שמתחיל בה.
_TEST_DB_PREFIX = "codebot_backup_retry_it_"

_MONGO_URL = (
    os.environ.get("NOTE_FONTS_TEST_MONGO_URI") or os.environ.get("MONGODB_URL") or ""
).strip()

pytestmark = pytest.mark.skipif(
    not _MONGO_URL,
    reason="דורש NOTE_FONTS_TEST_MONGO_URI או MONGODB_URL",
)

USER_ID = 9090
T0 = datetime(2026, 10, 17, 2, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def mongo_client():
    """לקוח מחובר, או דילוג — **רק** כשאין שרת בקצה השני (``ServerSelectionTimeoutError``). כל חריגה אחרת עולה; סיבת הדילוג אינה מצטטת את החריגה, כי הכתובת יכולה לשאת סיסמה (K13)."""
    client = pymongo.MongoClient(_MONGO_URL, serverSelectionTimeoutMS=2000, tz_aware=True, tzinfo=timezone.utc)
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
def disk(mongo_client, monkeypatch):
    import webapp.backup_scheduler as bs

    name = f"{_TEST_DB_PREFIX}{uuid.uuid4().hex[:12]}"
    db = mongo_client[name]
    clock = {"now": T0}
    events = []
    result = {"ok": False, "during": None}

    def _perform(uid):
        if result["during"]:
            result["during"]()
        return result["ok"]

    monkeypatch.setattr(bs, "_now_utc", lambda: clock["now"])
    monkeypatch.setattr(bs, "SCAN_INTERVAL_SECONDS", 300)
    monkeypatch.setattr(bs, "_perform_disk_backup", _perform)
    monkeypatch.setattr(bs, "emit_event", lambda event, severity="info", **fields: events.append((event, fields)))

    def prefs():
        return (db.users.find_one({"user_id": USER_ID}) or {}).get("disk_backup_prefs") or {}

    def scan_at(when):
        clock["now"] = when
        bs._scan_disk_backups(SimpleNamespace(db=db), when.isoformat())

    try:
        yield SimpleNamespace(bs=bs, db=db, prefs=prefs, scan_at=scan_at, events=events, result=result)
    finally:
        # סורג בטיחות: מוחקים רק מסד שנוצר כאן
        if name.startswith(_TEST_DB_PREFIX):
            mongo_client.drop_database(name)


def test_the_waits_grow_and_the_last_failure_moves_to_the_regular_slot(disk):
    d = disk
    d.db.users.insert_one({"user_id": USER_ID, "disk_backup_prefs": {"schedule_key": "daily", "schedule_next_at": (T0 - timedelta(minutes=1)).isoformat()}})

    now = T0
    for attempt in range(1, d.bs.RETRY_MAX_ATTEMPTS + 1):
        d.scan_at(now)
        prefs = d.prefs()
        assert prefs["consecutive_failures"] == attempt
        nxt = datetime.fromisoformat(prefs["schedule_next_at"])
        assert nxt - now == timedelta(seconds=300 * 2 ** (attempt - 1))
        now = nxt + timedelta(seconds=1)

    d.scan_at(now)
    prefs = d.prefs()
    assert prefs["consecutive_failures"] == 0
    assert datetime.fromisoformat(prefs["schedule_next_at"]) == now + timedelta(days=1)
    assert [e for e, _ in d.events] == ["webapp_backup_retries_exhausted"]


def test_a_success_keeps_a_schedule_the_user_changed_during_the_backup(disk):
    d = disk
    d.db.users.insert_one({"user_id": USER_ID, "disk_backup_prefs": {"schedule_key": "daily", "schedule_next_at": (T0 - timedelta(minutes=1)).isoformat(), "consecutive_failures": 2}})
    user_choice = "2099-01-01T00:00:00+00:00"
    d.result["ok"] = True
    d.result["during"] = lambda: d.db.users.update_one({"user_id": USER_ID}, {"$set": {"disk_backup_prefs.schedule_next_at": user_choice}})

    d.scan_at(T0)

    prefs = d.prefs()
    assert prefs["schedule_next_at"] == user_choice
    # הגיבוי עצמו קרה, ולכן last_backup_at נכתב גם כשהתזמון לא נדרס
    assert prefs["last_backup_at"] == T0.isoformat()
