"""גיבוי מתוזמן שנכשל מנוסה שוב אחרי המתנה שגדלה, ואחרי ``RETRY_MAX_ATTEMPTS`` עובר למועד הרגיל — ולא כל חמש דקות בלי סוף.

**מה נשבר.** כל כשל של גיבוי מתוזמן בוובאפ — Drive או דיסק — קבע ניסיון חוזר בעוד ``SCAN_INTERVAL_SECONDS`` (``_retry_next_at``), בלי מונה ובלי סוף. כשל שאינו חולף הפך לגיבוי מלא כל חמש דקות. וכתיבת המועד הבא בסוף הגיבוי נעשתה לפי ``user_id`` בלבד, ולכן דרסה תזמון שהמשתמש קבע בזמן שהגיבוי רץ.

**מה נבדק כאן.** הסורקים האמיתיים (``_scan_drive_backups``, ``_scan_disk_backups``) מעל ``_fake_mongo``, עם שעון שהבדיקה מזיזה (``_now_utc``): רצף ההמתנות, המעבר למועד הרגיל, איפוס המונה בהצלחה ובהשהיה, והכתיבה המותנית בסנטינל.
"""

from __future__ import annotations

import io
import logging
import sys
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from _fake_mongo import FakeDB

USER_ID = 8080
T0 = datetime(2026, 10, 17, 2, 0, tzinfo=timezone.utc)
WEEK = timedelta(days=7)


class _Clock:
    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def env(monkeypatch):
    import services.google_drive_service as gds
    import services.personal_backup_service as pbs
    import webapp.backup_scheduler as bs
    from database.repository import Repository

    fdb = FakeDB()
    repo = Repository(SimpleNamespace(db=fdb))
    dbm = SimpleNamespace(db=fdb, get_drive_prefs=repo.get_drive_prefs)
    clock = _Clock(T0)
    events = []
    answer = {"check": gds.ConnectionCheck(gds.CONNECTION_TRANSIENT), "disk_ok": False}

    def _check(uid, *, owner):
        result = answer["check"]
        return result(uid) if callable(result) else result

    monkeypatch.setattr(bs, "_now_utc", clock)
    monkeypatch.setattr(bs, "SCAN_INTERVAL_SECONDS", 300)
    monkeypatch.setattr(gds, "check_connection", _check)
    monkeypatch.setattr(pbs.PersonalBackupService, "export_user_data", lambda self, uid: io.BytesIO(b"PK-zip"))
    monkeypatch.setattr(gds, "upload_bytes", lambda *a, **k: "file-id")
    monkeypatch.setattr(bs, "_perform_disk_backup", lambda uid: answer["disk_ok"])
    monkeypatch.setattr(bs, "emit_event", lambda event, severity="info", **fields: events.append((event, fields)))
    monkeypatch.setitem(sys.modules, "database", SimpleNamespace(db=dbm))

    def drive_prefs():
        return (fdb.users.find_one({"user_id": USER_ID}) or {}).get("webapp_drive_prefs") or {}

    def disk_prefs():
        return (fdb.users.find_one({"user_id": USER_ID}) or {}).get("disk_backup_prefs") or {}

    def scan_at(when):
        clock.now = when
        bs._scan_drive_backups(dbm, when.isoformat())
        bs._scan_disk_backups(dbm, when.isoformat())

    return SimpleNamespace(bs=bs, gds=gds, db=fdb, clock=clock, events=events, answer=answer, drive_prefs=drive_prefs, disk_prefs=disk_prefs, scan_at=scan_at)


def _parse(iso):
    return datetime.fromisoformat(iso)


def _exhausted(events):
    return [fields for event, fields in events if event == "webapp_backup_retries_exhausted"]


@pytest.mark.parametrize("target", ["drive", "disk"])
def test_failures_wait_longer_each_time_and_then_move_to_the_next_regular_slot(env, target):
    e = env
    prefs_key, read = ("webapp_drive_prefs", e.drive_prefs) if target == "drive" else ("disk_backup_prefs", e.disk_prefs)
    e.db.users.insert_one({"user_id": USER_ID, prefs_key: {"schedule_key": "weekly", "schedule_next_at": (T0 - timedelta(minutes=1)).isoformat()}})

    now = T0
    waits = []
    for attempt in range(1, e.bs.RETRY_MAX_ATTEMPTS + 1):
        e.scan_at(now)
        prefs = read()
        assert prefs["consecutive_failures"] == attempt
        nxt = _parse(prefs["schedule_next_at"])
        waits.append(nxt - now)
        now = nxt + timedelta(seconds=1)

    # 5, 10, 20, 40, 80, 160 דקות: כל המתנה כפולה מקודמתה, החל ממרווח הסריקה
    assert waits == [timedelta(seconds=300 * 2 ** i) for i in range(e.bs.RETRY_MAX_ATTEMPTS)]
    assert _exhausted(e.events) == []

    # הכשל הבא כבר לא מנוסה שוב: הגיבוי עובר למועד הרגיל של התזמון, והמונה מתאפס
    e.scan_at(now)
    prefs = read()
    assert _parse(prefs["schedule_next_at"]) == now + WEEK
    assert prefs["consecutive_failures"] == 0
    assert _exhausted(e.events) == [{"user_id": USER_ID, "target": target, "attempts": e.bs.RETRY_MAX_ATTEMPTS}]


def test_a_success_after_failures_resets_the_count(env):
    e = env
    e.db.users.insert_one({"user_id": USER_ID, "webapp_drive_prefs": {"schedule_key": "weekly", "schedule_next_at": (T0 - timedelta(minutes=1)).isoformat()}})
    e.scan_at(T0)
    e.scan_at(_parse(e.drive_prefs()["schedule_next_at"]) + timedelta(seconds=1))
    assert e.drive_prefs()["consecutive_failures"] == 2

    e.answer["check"] = e.gds.ConnectionCheck(e.gds.CONNECTION_OK)
    later = _parse(e.drive_prefs()["schedule_next_at"]) + timedelta(seconds=1)
    e.scan_at(later)

    prefs = e.drive_prefs()
    assert prefs["consecutive_failures"] == 0
    assert _parse(prefs["schedule_next_at"]) == later + WEEK


def test_pausing_a_rejected_connection_resets_the_count(env):
    e = env
    e.db.users.insert_one({"user_id": USER_ID, "webapp_drive_prefs": {"schedule_key": "weekly", "schedule_next_at": (T0 - timedelta(minutes=1)).isoformat(), "consecutive_failures": 3}})
    e.answer["check"] = e.gds.ConnectionCheck(e.gds.CONNECTION_AUTH_REQUIRED, "invalid_grant")

    e.scan_at(T0)

    prefs = e.drive_prefs()
    assert prefs["schedule_next_at"] is None
    assert prefs["consecutive_failures"] == 0


@pytest.mark.parametrize("stored", ["3", True, -2, 2.5, None])
def test_a_count_that_is_not_a_non_negative_integer_reads_as_zero(env, stored):
    """ההעדפות יכולות להגיע מגיבוי ששוחזר, כמו שהן — ``True`` הוא ``int`` בפייתון, ו-``"3"`` אינו מספר."""
    e = env
    e.db.users.insert_one({"user_id": USER_ID, "webapp_drive_prefs": {"schedule_key": "weekly", "schedule_next_at": (T0 - timedelta(minutes=1)).isoformat(), "consecutive_failures": stored}})

    e.scan_at(T0)

    prefs = e.drive_prefs()
    # ``type(...) is int`` ולא רק ``== 1``: בפייתון ``True == 1``, ובלי זה הפרמטר ``True`` עבר גם על קוד שלא כתב את המונה בכלל
    assert type(prefs["consecutive_failures"]) is int and prefs["consecutive_failures"] == 1
    assert _parse(prefs["schedule_next_at"]) == T0 + timedelta(seconds=300)


@pytest.mark.parametrize("target", ["drive", "disk"])
@pytest.mark.parametrize("outcome", ["success", "failure"])
def test_a_schedule_the_user_changed_during_the_backup_is_not_overwritten(env, monkeypatch, target, outcome):
    e = env
    prefs_key, read = ("webapp_drive_prefs", e.drive_prefs) if target == "drive" else ("disk_backup_prefs", e.disk_prefs)
    e.db.users.insert_one({"user_id": USER_ID, prefs_key: {"schedule_key": "weekly", "schedule_next_at": (T0 - timedelta(minutes=1)).isoformat()}})
    user_choice = "2099-01-01T00:00:00+00:00"

    def _user_changes_the_schedule():
        e.db.users.update_one({"user_id": USER_ID}, {"$set": {f"{prefs_key}.schedule_next_at": user_choice}})

    if target == "drive":
        result = e.gds.ConnectionCheck(e.gds.CONNECTION_OK if outcome == "success" else e.gds.CONNECTION_TRANSIENT)
        e.answer["check"] = lambda uid: _user_changes_the_schedule() or result
    else:
        monkeypatch.setattr(e.bs, "_perform_disk_backup", lambda uid: _user_changes_the_schedule() or (outcome == "success"))

    e.scan_at(T0)

    prefs = read()
    assert prefs["schedule_next_at"] == user_choice
    if outcome == "success":
        # הגיבוי הצליח: המונה מתאפס גם כשהמועד נשאר של המשתמש (_record_success)
        assert prefs["consecutive_failures"] == 0
    else:
        # כשל על תזמון שהמשתמש כתב מחדש אינו נספר: התזמון החדש מתחיל לספור מאפס
        assert "consecutive_failures" not in prefs


def _fail_once(monkeypatch, collection, should_fail):
    """הכתיבה הראשונה ל-``users`` ש-``should_fail(filter, update)`` מתאים לה נכשלת בשגיאת מסד; כל השאר עוברות לדמות כרגיל."""
    from pymongo.errors import AutoReconnect

    real_update_one = collection.update_one
    state = {"failed": False}

    def _update_one(q, u, *args, **kwargs):
        if not state["failed"] and should_fail(q, u):
            state["failed"] = True
            raise AutoReconnect("primary stepped down")
        return real_update_one(q, u, *args, **kwargs)

    monkeypatch.setattr(collection, "update_one", _update_one)
    return state


def _holds_a_sentinel(q, prefs_key):
    return f"{prefs_key}.schedule_next_at" in q


@pytest.mark.parametrize("target", ["drive", "disk"])
def test_a_backup_that_succeeded_is_not_counted_as_a_failure_when_its_schedule_write_fails(env, monkeypatch, caplog, target):
    """עד כאן כשל בכתיבת המועד שאחרי גיבוי מוצלח נפל ל-``except`` של הסורק, שקרא ל-``_record_failed_attempt``: הגיבוי שהצליח נספר ככשל, ועם מונה מלא — נשלח ``webapp_backup_retries_exhausted``. עכשיו הכשל נרשם, והסנטינל נשאר עד שהוא פג."""
    e = env
    prefs_key, read = ("webapp_drive_prefs", e.drive_prefs) if target == "drive" else ("disk_backup_prefs", e.disk_prefs)
    e.db.users.insert_one({"user_id": USER_ID, prefs_key: {"schedule_key": "weekly", "schedule_next_at": (T0 - timedelta(minutes=1)).isoformat(), "consecutive_failures": e.bs.RETRY_MAX_ATTEMPTS}})
    e.answer["check"] = e.gds.ConnectionCheck(e.gds.CONNECTION_OK)
    e.answer["disk_ok"] = True
    failed = _fail_once(monkeypatch, e.db.users, lambda q, u: _holds_a_sentinel(q, prefs_key))

    with caplog.at_level(logging.ERROR, logger="webapp.backup_scheduler"):
        e.scan_at(T0)

    assert failed["failed"], "הכתיבה המותנית לא נוסתה בכלל"
    assert _exhausted(e.events) == []
    prefs = read()
    assert prefs["consecutive_failures"] == e.bs.RETRY_MAX_ATTEMPTS
    assert _parse(prefs["schedule_next_at"]) >= T0 + timedelta(seconds=e.bs.SENTINEL_TTL_SECONDS - 60), "הסנטינל הוחלף"
    label = "Drive" if target == "drive" else "Disk"
    assert any(r.getMessage().startswith(f"Failed to write the {label} schedule of user {USER_ID}") for r in caplog.records)


@pytest.mark.parametrize("target", ["drive", "disk"])
def test_a_success_resets_the_count_even_when_the_schedule_changed_during_the_backup(env, monkeypatch, target):
    """הכתיבה המותנית בסנטינל לא תואמת כשהמועד השתנה בזמן הגיבוי, והמועד החדש נשאר. עד כאן גם המונה נשאר — והכשל הבא המשיך לספור מ-3, אחרי גיבוי שהצליח."""
    e = env
    prefs_key, read = ("webapp_drive_prefs", e.drive_prefs) if target == "drive" else ("disk_backup_prefs", e.disk_prefs)
    e.db.users.insert_one({"user_id": USER_ID, prefs_key: {"schedule_key": "weekly", "schedule_next_at": (T0 - timedelta(minutes=1)).isoformat(), "consecutive_failures": 3}})
    elsewhere = "2099-01-01T00:00:00+00:00"

    def _the_schedule_moves():
        e.db.users.update_one({"user_id": USER_ID}, {"$set": {f"{prefs_key}.schedule_next_at": elsewhere}})

    if target == "drive":
        e.answer["check"] = lambda uid: _the_schedule_moves() or e.gds.ConnectionCheck(e.gds.CONNECTION_OK)
    else:
        monkeypatch.setattr(e.bs, "_perform_disk_backup", lambda uid: _the_schedule_moves() or True)

    e.scan_at(T0)

    prefs = read()
    assert prefs["schedule_next_at"] == elsewhere
    assert prefs["consecutive_failures"] == 0
