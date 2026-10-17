"""השהיית הגיבוי של חיבור שגוגל דחה, והחזרתו אחרי חיבור מחדש — מול **מונגו אמיתי**, ולא מול stub.

``tests/test_webapp_drive_auth_required.py`` בודק את הזרימה מעל ``_fake_mongo``. מה שהוא לא יכול להוכיח הוא איך השרת מפרש את המסננים שהזרימה נשענת עליהם:

- ``{field: None}`` — תואם גם שדה שחסר במסמך (תיעוד MongoDB, "Query for Null or Missing Fields"). ``_record_drive_auth_required`` נשען על זה כדי לרשום רק את הדחייה הראשונה, ו-``resume_drive_schedule_after_reconnect`` כדי לזהות תזמון מושהה.
- ``$ne: None`` — מחריג גם שדה שחסר. מסנן התפיסה (``_drive_claim_filter``) נשען על זה כדי לדלג על תזמון מושהה.
- הכתיבה המותנית בסנטינל (``_pause_drive_schedule``) — ``matched_count`` אפס כשהמשתמש שינה את התזמון בינתיים.

מתי הן רצות: כש-``NOTE_FONTS_TEST_MONGO_URI``, או ``MONGODB_URL`` כשהוא ריק, מצביע לשרת נגיש. כשאין שם שרת הן מדלגות; כשיש שרת והחיבור נכשל מסיבה אחרת — אימות, כתובת — הן נכשלות (``mongo_client``, כמו ב-``tests/test_recycle_bin_ttl_index_mongo.py``).

**בטיחות מחיקה:** כל בדיקה עובדת על מסד עם שם ייחודי משלה, וה-teardown מוחק רק מסד שמתחיל בתחילית שלמטה.
"""

from __future__ import annotations

import io
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

pymongo = pytest.importorskip("pymongo")

from pymongo.errors import ServerSelectionTimeoutError  # noqa: E402

import drive_owner  # noqa: E402

#: תחילית מסדי הבדיקה. ה-teardown מוחק **רק** מסד שמתחיל בה.
_TEST_DB_PREFIX = "codebot_drive_pause_it_"

_MONGO_URL = (
    os.environ.get("NOTE_FONTS_TEST_MONGO_URI") or os.environ.get("MONGODB_URL") or ""
).strip()

pytestmark = pytest.mark.skipif(
    not _MONGO_URL,
    reason="דורש NOTE_FONTS_TEST_MONGO_URI או MONGODB_URL",
)

USER_ID = 7070
TOKENS = "webapp_drive_tokens"
PREFS = drive_owner.drive_fields(drive_owner.WEBAPP).prefs


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
def flow(mongo_client, monkeypatch):
    import services.google_drive_service as gds
    import services.personal_backup_service as pbs
    import webapp.backup_scheduler as bs
    from database.repository import Repository

    name = f"{_TEST_DB_PREFIX}{uuid.uuid4().hex[:12]}"
    mongo_db = mongo_client[name]
    repo = Repository(SimpleNamespace(db=mongo_db))
    dbm = SimpleNamespace(db=mongo_db, get_drive_prefs=repo.get_drive_prefs)
    calls = SimpleNamespace(checks=0, exports=0)
    answer = {"check": gds.ConnectionCheck(gds.CONNECTION_OK)}

    def _check(uid, *, owner):
        calls.checks += 1
        result = answer["check"]
        return result(uid) if callable(result) else result

    def _export(self, uid):
        calls.exports += 1
        return io.BytesIO(b"PK-zip")

    monkeypatch.setattr(gds, "check_connection", _check)
    monkeypatch.setattr(pbs.PersonalBackupService, "export_user_data", _export)
    monkeypatch.setattr(gds, "upload_bytes", lambda *a, **k: "file-id")
    monkeypatch.setattr(bs, "emit_event", lambda *a, **k: None)
    monkeypatch.setitem(sys.modules, "database", SimpleNamespace(db=dbm))

    def _prefs():
        doc = mongo_db.users.find_one({"user_id": USER_ID}) or {}
        return doc.get(PREFS) or {}

    def _scan():
        bs._scan_drive_backups(dbm, datetime.now(timezone.utc).isoformat())

    due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    try:
        yield SimpleNamespace(bs=bs, gds=gds, db=mongo_db, dbm=dbm, calls=calls, answer=answer, prefs=_prefs, scan=_scan, due=due)
    finally:
        # סורג בטיחות: מוחקים רק מסד שנוצר כאן
        if name.startswith(_TEST_DB_PREFIX):
            mongo_client.drop_database(name)


def test_a_rejected_connection_is_paused_and_the_claim_skips_it(flow):
    f = flow
    # בלי השדה auth_required_at בכלל — המסנן {field: None} חייב לתפוס גם שדה שחסר
    f.db.users.insert_one({"user_id": USER_ID, PREFS: {"schedule_key": "weekly", "schedule_next_at": f.due}})
    f.answer["check"] = f.gds.ConnectionCheck(f.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")

    f.scan()

    prefs = f.prefs()
    assert prefs["schedule_next_at"] is None
    assert isinstance(prefs["auth_required_at"], str) and prefs["auth_required_at"]
    assert f.calls.exports == 0
    f.scan()
    assert f.calls.checks == 1, "התזמון המושהה נתפס שוב — $ne: None לא דילג עליו"


def test_a_schedule_changed_during_the_check_is_left_as_the_user_set_it(flow):
    f = flow
    f.db.users.insert_one({"user_id": USER_ID, PREFS: {"schedule_key": "weekly", "schedule_next_at": f.due}})
    user_choice = "2099-01-01T00:00:00+00:00"

    def _user_changes_it(uid):
        f.db.users.update_one({"user_id": uid}, {"$set": {f"{PREFS}.schedule_next_at": user_choice}})
        return f.gds.ConnectionCheck(f.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")

    f.answer["check"] = _user_changes_it

    f.scan()

    assert f.prefs()["schedule_next_at"] == user_choice


def test_the_first_rejection_keeps_its_time(flow):
    f = flow
    first = "2026-10-12T12:37:45+00:00"
    f.db.users.insert_one({"user_id": USER_ID, PREFS: {"auth_required_at": first}})

    f.bs._record_drive_auth_required(f.dbm, USER_ID)

    assert f.prefs()["auth_required_at"] == first


def test_the_pause_writes_the_reconnect_mark_itself(flow, monkeypatch):
    """הכתיבה הנפרדת של הסימון יכולה להיכשל (היא רק נרשמת). ההשהיה כותבת אותו בעצמה — כאן מול מונגו אמיתי, כש-``{field: None}`` צריך לתפוס שדה שחסר לגמרי."""
    f = flow
    f.db.users.insert_one({"user_id": USER_ID, PREFS: {"schedule_key": "weekly", "schedule_next_at": f.due}})
    monkeypatch.setattr(f.bs, "_record_drive_auth_required", lambda db, uid: None)
    f.answer["check"] = f.gds.ConnectionCheck(f.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")

    f.scan()

    prefs = f.prefs()
    assert prefs["schedule_next_at"] is None
    assert isinstance(prefs.get("auth_required_at"), str) and prefs["auth_required_at"]


def test_the_pause_keeps_the_time_of_the_first_rejection(flow):
    f = flow
    first = "2026-10-12T12:37:45+00:00"
    f.db.users.insert_one({"user_id": USER_ID, PREFS: {"schedule_key": "weekly", "schedule_next_at": f.due, "auth_required_at": first}})
    f.answer["check"] = f.gds.ConnectionCheck(f.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")

    f.scan()

    prefs = f.prefs()
    assert prefs["schedule_next_at"] is None
    assert prefs["auth_required_at"] == first


def test_the_pause_matches_the_tokens_the_claim_saw(flow):
    """ההשהיה מותנית ב-``obtained_at`` של הטוקנים, שהתפיסה מביאה בהיטלה עם נקודה. כאן מול מונגו אמיתי: בלי חיבור מחדש, הערך שהתפיסה ראתה תואם, וההשהיה נכתבת."""
    f = flow
    f.db.users.insert_one({"user_id": USER_ID, PREFS: {"schedule_key": "weekly", "schedule_next_at": f.due}, TOKENS: {"obtained_at": "2026-10-17T01:00:00+00:00"}})
    f.answer["check"] = f.gds.ConnectionCheck(f.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")

    f.scan()

    assert f.prefs()["schedule_next_at"] is None


def test_a_reconnect_during_the_check_is_not_paused(flow, monkeypatch):
    f = flow
    f.db.users.insert_one({"user_id": USER_ID, PREFS: {"schedule_key": "weekly", "schedule_next_at": f.due}, TOKENS: {"obtained_at": "2026-10-17T01:00:00+00:00"}})
    f.answer["check"] = f.gds.ConnectionCheck(f.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")
    real_record = f.bs._record_drive_auth_required

    def _record_then_the_user_reconnects(db, uid):
        real_record(db, uid)
        f.db.users.update_one({"user_id": uid}, {"$set": {f"{TOKENS}.obtained_at": "2026-10-17T01:00:05+00:00"}})
        f.bs.resume_drive_schedule_after_reconnect(db, uid)

    monkeypatch.setattr(f.bs, "_record_drive_auth_required", _record_then_the_user_reconnects)

    f.scan()

    prefs = f.prefs()
    assert prefs["schedule_next_at"] is not None
    assert not prefs.get("auth_required_at")


def test_reconnecting_resumes_only_a_paused_schedule(flow):
    f = flow
    marked = "2026-10-12T12:37:45+00:00"
    f.db.users.insert_many([
        {"user_id": USER_ID, PREFS: {"schedule_key": "weekly", "schedule_next_at": None, "auth_required_at": marked}},
        {"user_id": USER_ID + 1, PREFS: {"schedule_key": "off", "schedule_next_at": None, "auth_required_at": marked}},
    ])
    before = datetime.now(timezone.utc).isoformat()

    f.bs.resume_drive_schedule_after_reconnect(f.dbm, USER_ID)
    f.bs.resume_drive_schedule_after_reconnect(f.dbm, USER_ID + 1)

    resumed = f.prefs()
    assert resumed["schedule_next_at"] is not None and resumed["schedule_next_at"] >= before
    assert resumed["auth_required_at"] is None
    off = (f.db.users.find_one({"user_id": USER_ID + 1}) or {})[PREFS]
    assert off["schedule_next_at"] is None
    assert off["auth_required_at"] is None

    # והסריקה שאחרי החיבור מריצה את הגיבוי
    f.scan()
    assert f.calls.exports == 1
