"""פיוס הרצות יתומות — הבדיקות.

כל הבדיקות כאן עוברות דרך ``reconcile_orphan_runs`` ו-``_persist_run``
האמיתיים, מול דמת האוסף המשותפת (``tests/_fake_mongo``) שמעריכה את המסנן
באמת ומחזירה ``matched_count`` אמיתי. דמה שמתעלמת מהמסנן הייתה מאשרת גם
קוד שאין לו מסנן בכלל.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.job_orphan_reconciler import (
    ORPHANED_ERROR_MESSAGE,
    ORPHANED_FAILURE_REASON,
    reconcile_delay_seconds,
    reconcile_enabled,
    reconcile_orphan_runs,
)
from services.job_tracker import JobStatus, JobTracker
from tests._fake_mongo import AsyncFakeCollection, FakeDB

LOCK_AT = datetime(2026, 9, 21, 12, 0, 0, tzinfo=timezone.utc)


def _run_doc(run_id: str, job_id: str, started_at: datetime, status: str = "running", **extra):
    doc = {
        "run_id": run_id,
        "job_id": job_id,
        "started_at": started_at,
        "ended_at": None,
        "status": status,
        "logs": [],
        "result": None,
    }
    doc.update(extra)
    return doc


@pytest.fixture
def coll():
    c = AsyncFakeCollection()
    return c


@pytest.mark.asyncio
async def test_run_from_a_previous_holder_is_closed_with_all_sibling_fields(coll):
    """הרצה שהתחילה לפני רכישת המנעול נסגרת — וכל שדות האחים זזים יחד.

    סטטוס בלי ``ended_at`` היה שובר את חישוב משך ההרצה בדשבורד, וסטטוס בלי
    ``failure_reason`` היה מערבב את ההרצה הזו עם ג'וב שנפל באמת.
    """
    coll.sync.insert_one(_run_doc("old-1", "cache_warming", LOCK_AT - timedelta(minutes=5)))

    summary = await reconcile_orphan_runs(coll, lock_acquired_at=LOCK_AT, now=LOCK_AT + timedelta(minutes=3))

    assert summary["reconciled"] == 1
    doc = coll.sync.find_one({"run_id": "old-1"})
    assert doc["status"] == JobStatus.FAILED.value
    assert doc["failure_reason"] == ORPHANED_FAILURE_REASON
    assert doc["error_message"] == ORPHANED_ERROR_MESSAGE
    assert doc["ended_at"] == LOCK_AT + timedelta(minutes=3)
    assert doc["logs"][-1]["message"] == ORPHANED_ERROR_MESSAGE


@pytest.mark.asyncio
async def test_a_run_started_after_the_lock_was_taken_is_left_alone(coll):
    """הרצה של המחזיק הנוכחי אינה יתומה — גם אם היא רצה זמן רב.

    זו הבדיקה שמפרידה בין "יתום" לבין "איטי". בלי תנאי הזמן, כל ג'וב ארוך
    של התהליך הנוכחי היה מסומן ככשל תוך כדי ריצה.
    """
    coll.sync.insert_one(_run_doc("mine-1", "repo_sync", LOCK_AT + timedelta(seconds=30)))

    summary = await reconcile_orphan_runs(coll, lock_acquired_at=LOCK_AT)

    assert summary["reconciled"] == 0
    assert coll.sync.find_one({"run_id": "mine-1"})["status"] == JobStatus.RUNNING.value


@pytest.mark.asyncio
async def test_a_previous_holders_run_that_finished_inside_the_delay_keeps_its_result(coll):
    """המחזיק הקודם הספיק לסיים בהצלחה — הפיוס אינו נוגע בו.

    זה המקרה שההשהיה קיימת בשבילו: התהליך הישן מקבל זמן חסד לסגור, והוא
    כותב ``completed`` בעצמו. כשהפיוס מתעורר, המסמך כבר אינו ``running``
    ולכן הוא מחוץ למסנן — והתוצאה האמיתית נשארת.
    """
    coll.sync.insert_one(
        _run_doc(
            "old-done",
            "backups_cleanup",
            LOCK_AT - timedelta(minutes=2),
            status=JobStatus.COMPLETED.value,
            ended_at=LOCK_AT + timedelta(seconds=20),
            result={"deleted": 7},
        )
    )

    summary = await reconcile_orphan_runs(coll, lock_acquired_at=LOCK_AT, now=LOCK_AT + timedelta(minutes=3))

    assert summary["scanned"] == 0
    assert summary["reconciled"] == 0
    doc = coll.sync.find_one({"run_id": "old-done"})
    assert doc["status"] == JobStatus.COMPLETED.value
    assert doc["result"] == {"deleted": 7}
    assert "failure_reason" not in doc
    assert doc["ended_at"] == LOCK_AT + timedelta(seconds=20)


@pytest.mark.asyncio
async def test_a_run_that_ends_between_the_find_and_the_update_is_not_overwritten(coll):
    """‏CAS: ההרצה נסגרה בעצמה אחרי השליפה — התוצאה שלה שורדת, והדחייה נרשמת."""

    class _RacingCollection(AsyncFakeCollection):
        """סוגר את ההרצה ברגע שבין השליפה לעדכון — בדיוק החלון של TOCTOU."""

        def __init__(self, sync):
            super().__init__(sync)
            self.raced = False

        async def update_one(self, q, u, upsert=False):
            if not self.raced:
                self.raced = True
                self.sync.update_one(
                    {"run_id": "old-race"},
                    {"$set": {"status": JobStatus.COMPLETED.value, "result": {"ok": True}}},
                )
            return await super().update_one(q, u, upsert=upsert)

    racing = _RacingCollection(coll.sync)
    racing.sync.insert_one(_run_doc("old-race", "drive_sync", LOCK_AT - timedelta(minutes=1)))

    summary = await reconcile_orphan_runs(racing, lock_acquired_at=LOCK_AT)

    assert summary["reconciled"] == 0
    assert summary["skipped"] == 1
    doc = racing.sync.find_one({"run_id": "old-race"})
    assert doc["status"] == JobStatus.COMPLETED.value
    assert doc["result"] == {"ok": True}
    assert "failure_reason" not in doc


@pytest.mark.asyncio
async def test_a_naive_lock_timestamp_is_refused_before_any_query(coll):
    """זמן בלי אזור זמן נדחה **לפני** שנוגעים במסד.

    ‏``pytest.raises(TypeError)`` לבדו אינו מספיק כאן: בלי הבדיקה המפורשת
    ההשוואה בין מודע לנאיבי זורקת ``TypeError`` בעצמה, בתוך השאילתה —
    ולכן טסט שרק בודק את סוג החריגה עובר גם על קוד שאין בו שום שומר.
    ‏(נמדד: הרצת מוטציה שהסירה את הבדיקה עברה.) מה שמבדיל הוא **מתי**:
    שומר שפועל מסנן החוצה לפני כל עבודה, ולא נופל באמצעה.
    """

    class _RefusingCollection(AsyncFakeCollection):
        def find(self, *a, **k):
            raise AssertionError("השאילתה רצה למרות שהזמן נאיבי")

    refusing = _RefusingCollection(coll.sync)
    refusing.sync.insert_one(_run_doc("old-2", "cache_warming", LOCK_AT - timedelta(minutes=5)))

    with pytest.raises(TypeError, match="timezone-aware"):
        await reconcile_orphan_runs(refusing, lock_acquired_at=LOCK_AT.replace(tzinfo=None))

    assert refusing.sync.find_one({"run_id": "old-2"})["status"] == JobStatus.RUNNING.value


@pytest.mark.asyncio
async def test_the_summary_event_carries_the_count_and_a_named_sample(coll, monkeypatch):
    """אירוע מסכם אחד, לא אחד לכל זומבי — והרשימה מוצהרת כמדגם."""
    import observability

    captured = []
    monkeypatch.setattr(observability, "emit_event", lambda e, **f: captured.append((e, f)))

    for i in range(3):
        coll.sync.insert_one(_run_doc(f"old-{i}", f"job_{i}", LOCK_AT - timedelta(minutes=i + 1)))

    await reconcile_orphan_runs(coll, lock_acquired_at=LOCK_AT)

    assert len(captured) == 1
    name, fields = captured[0]
    assert name == "job_runs_reconciled"
    assert fields["count"] == 3
    assert sorted(fields["job_ids_sample"]) == ["job_0", "job_1", "job_2"]


@pytest.mark.asyncio
async def test_nothing_to_do_emits_nothing(coll, monkeypatch):
    """עלייה רגילה בלי זומבים שותקת. אחרת כל דיפלוי היה מייצר התראה."""
    import observability

    captured = []
    monkeypatch.setattr(observability, "emit_event", lambda e, **f: captured.append((e, f)))

    await reconcile_orphan_runs(coll, lock_acquired_at=LOCK_AT)

    assert captured == []


@pytest.mark.asyncio
async def test_only_the_projected_fields_are_read(coll):
    """היטלה: ``logs`` ו-``result`` אינם נגררים על כל הרצה שנשלפת."""
    seen = {}

    class _WatchingCollection(AsyncFakeCollection):
        def find(self, q, projection=None, *a, **k):
            seen["projection"] = projection
            return super().find(q, projection, *a, **k)

    watching = _WatchingCollection(coll.sync)
    watching.sync.insert_one(_run_doc("old-p", "job_p", LOCK_AT - timedelta(minutes=1)))

    await reconcile_orphan_runs(watching, lock_acquired_at=LOCK_AT)

    assert seen["projection"], "השליפה חייבת לבקש היטלה מפורשת"
    assert "logs" not in seen["projection"]
    assert "result" not in seen["projection"]


# --------------------------------------------------------------------------
# ‏``_persist_run`` — השומר שמונע תחייה
# --------------------------------------------------------------------------


class _MockDB:
    def __init__(self):
        self.db = FakeDB("test")
        self.client = {"test": self.db}
        self.db_name = "test"

    @property
    def runs(self):
        return self.db["job_runs"]


def test_a_terminal_run_is_not_revived_to_running():
    """אחרי שהפיוס סגר הרצה, עדכון התקדמות מאוחר אינו מחזיר אותה ל-``running``.

    בלי השומר הזה הרשומה הייתה חוזרת להיות ``running`` לנצח: הפיוס רץ פעם
    אחת בעלייה ולא חוזר, ואיש לא היה סוגר אותה שוב.
    """
    db = _MockDB()
    tracker = JobTracker(db)
    run = tracker.start_run("late_job")

    db.runs.update_one(
        {"run_id": run.run_id},
        {"$set": {"status": JobStatus.FAILED.value, "failure_reason": ORPHANED_FAILURE_REASON}},
    )

    tracker.update_progress(run.run_id, processed=5, total=10)

    doc = db.runs.find_one({"run_id": run.run_id})
    assert doc["status"] == JobStatus.FAILED.value
    assert doc["failure_reason"] == ORPHANED_FAILURE_REASON


def test_a_real_result_is_never_blocked_by_the_orphan_marking():
    """המשלים של השומר, וההבטחה שההערה על ההשהיה נשענת עליה.

    כתיבה **סופית** עוברת גם על מסמך שהפיוס כבר סימן — ולכן הרצה שסיימה
    באמת דורסת את הסימון, והייחוס החיצוני מנוקה יחד איתו.
    """
    db = _MockDB()
    tracker = JobTracker(db)
    run = tracker.start_run("slow_job")

    db.runs.update_one(
        {"run_id": run.run_id},
        {
            "$set": {
                "status": JobStatus.FAILED.value,
                "failure_reason": ORPHANED_FAILURE_REASON,
                "error_message": ORPHANED_ERROR_MESSAGE,
            }
        },
    )

    tracker.complete_run(run.run_id, result={"rows": 3})

    doc = db.runs.find_one({"run_id": run.run_id})
    assert doc["status"] == JobStatus.COMPLETED.value
    assert doc["result"] == {"rows": 3}
    # הייחוס החיצוני מתאר מי סגר את ההרצה במקומה. ברגע שההרצה דיווחה על
    # עצמה, זוג ``completed`` + ``orphaned`` הוא סתירה.
    assert "failure_reason" not in doc


def test_the_owner_is_written_on_the_run_and_can_be_read_back():
    db = _MockDB()
    tracker = JobTracker(db)
    tracker.owner_id = "srv-7:4242"

    run = tracker.start_run("owned_job")

    assert db.runs.find_one({"run_id": run.run_id})["owner_id"] == "srv-7:4242"


def test_both_writers_of_the_log_list_cut_it_to_the_same_length():
    """התקרה נגזרת ממקום אחד, ולא מוקלדת פעמיים.

    ‏``_persist_run`` חותך ב-Python ו-הפיוס חותך ב-``$slice``. שני אורכים
    שונים היו הופכים את אורך הרשימה לתלוי במי כתב אחרון.
    """
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    reconciler = (root / "services/job_orphan_reconciler.py").read_text(encoding="utf-8")
    tracker_src = (root / "services/job_tracker.py").read_text(encoding="utf-8")
    main_src = (root / "main.py").read_text(encoding="utf-8")

    assert "$slice\": -JOB_RUN_LOGS_KEPT" in reconciler
    assert "run.logs[-JOB_RUN_LOGS_KEPT:]" in tracker_src
    assert "-_JOB_RUN_LOGS_KEPT" in main_src
    # ואין מספר מוקלד ששרד באחד מהם.
    assert not re.search(r"\$slice\"?:\s*-\d", reconciler + main_src)


def test_the_delay_default_covers_renders_full_shutdown_window():
    """ההשהיה גדולה מחלון הסגירה של Render, ולא רק "מספר עגול".

    המספרים כאן חיצוניים לריפו ולכן אין מזהה לנקוב בשמו — הם מצוטטים
    מ-https://render.com/docs/deploys, ‏21.9.2026: המתנה של 60 שניות לפני
    ‏``SIGTERM``, ועוד shutdown delay שברירת המחדל שלו 30 שניות לפני
    ‏``SIGKILL``. הבדיקה היא גלאי הסחיפה: אם מישהו יקטין את ברירת המחדל
    מתחת לחלון, הפיוס ירוץ בזמן ששני התהליכים חיים.
    """
    render_sigterm_wait_secs = 60
    render_shutdown_delay_secs = 30

    assert reconcile_delay_seconds() >= render_sigterm_wait_secs + render_shutdown_delay_secs
    assert reconcile_enabled() is True
