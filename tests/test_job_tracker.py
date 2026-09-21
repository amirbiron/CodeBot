from datetime import datetime, timezone

import pytest

from services.job_tracker import JOB_RUN_LOGS_KEPT, JobStatus, JobTracker
# ‏``tests`` אינו חבילה, וב-CI יש חבילת ``tests`` זרה שמאפילה עליו —
# ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeCollection, FakeTrackerDB
from services.job_registry import JobRegistry, register_job, JobCategory, JobType


@pytest.fixture
def mock_db():
    return FakeTrackerDB()


@pytest.fixture
def tracker(mock_db):
    """Tracker מול דמת מונגו משותפת.

    הדמה שהייתה כאן קודם החזירה ``None`` מ-``update_one`` והתעלמה מכל
    מסנן פרט ל-``run_id``. כלומר ברגע ש-``_persist_run`` התחיל לבדוק
    ``matched_count``, כל כתיבה בטסטים נראתה כדחייה — והטסטים המשיכו
    לעבור, כי אף אחד מהם לא קרא את הרשומה בחזרה. ‏``tests/_fake_mongo``
    מעריך את המסנן באמת ומחזיר ספירות אמיתיות.
    """
    return JobTracker(mock_db)


def test_start_and_complete_run(tracker, mock_db):
    run = tracker.start_run("test_job")
    assert run.status == JobStatus.RUNNING
    assert run.run_id in [r.run_id for r in tracker.get_active_runs()]

    tracker.complete_run(run.run_id, result={"count": 5})

    assert run.run_id not in [r.run_id for r in tracker.get_active_runs()]

    # נקרא מהמסד ולא מהאובייקט בזיכרון: כתיבה שנדחתה נראית זהה לכתיבה
    # שנחתה, אם בודקים רק את ה-dataclass.
    doc = mock_db.runs.find_one({"run_id": run.run_id})
    assert doc is not None
    assert doc["status"] == "completed"
    assert doc["result"] == {"count": 5}
    assert doc["ended_at"] is not None


def test_fail_run(tracker, mock_db):
    run = tracker.start_run("test_job")
    tracker.fail_run(run.run_id, "Test error")

    assert run.status == JobStatus.FAILED
    assert run.error_message == "Test error"

    doc = mock_db.runs.find_one({"run_id": run.run_id})
    assert doc["status"] == "failed"
    assert doc["error_message"] == "Test error"


def test_skip_run(tracker):
    run = tracker.start_run("test_job")
    tracker.skip_run(run.run_id, "disabled_by_env")
    assert run.status == JobStatus.SKIPPED
    assert run.run_id not in [r.run_id for r in tracker.get_active_runs()]


def test_record_skipped(tracker):
    run = tracker.record_skipped(job_id="test_job", trigger="manual", user_id=123, reason="already_running")
    assert run.status == JobStatus.SKIPPED
    assert run.run_id not in [r.run_id for r in tracker.get_active_runs()]


def test_track_context_manager(tracker):
    with tracker.track("test_job") as run:
        tracker.add_log(run.run_id, "info", "Processing...")

    assert run.status == JobStatus.COMPLETED


def test_track_context_manager_on_error(tracker):
    with pytest.raises(ValueError):
        with tracker.track("test_job") as run:
            raise ValueError("Oops")

    assert run.status == JobStatus.FAILED


def test_registry_singleton():
    reg1 = JobRegistry()
    reg2 = JobRegistry()
    assert reg1 is reg2


def test_register_and_list_jobs():
    JobRegistry()._jobs.clear()  # reset for test

    register_job(
        job_id="test_backup",
        name="Test Backup",
        description="A test job",
        category=JobCategory.BACKUP,
        job_type=JobType.REPEATING,
        interval_seconds=3600,
    )

    jobs = JobRegistry().list_all()
    assert len(jobs) == 1
    assert jobs[0].job_id == "test_backup"


class _FailsOnFirstWrite(FakeCollection):
    """כתיבה ראשונה זורקת — חריגת מסד רגעית בדיוק ב-``start_run``."""

    def __init__(self):
        super().__init__()
        self.calls = 0

    def update_one(self, *a, **k):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("transient mongo error")
        return super().update_one(*a, **k)


class _AlwaysFails(FakeCollection):
    def update_one(self, *a, **k):
        raise RuntimeError("mongo is down")


class _CapturesUpdates(FakeCollection):
    def __init__(self):
        super().__init__()
        self.updates = []

    def update_one(self, q, u, **k):
        self.updates.append(u)
        return super().update_one(q, u, **k)


def _db_with(coll):
    db = FakeTrackerDB()
    db.db.c["job_runs"] = coll
    return db


def test_a_run_whose_opening_write_failed_still_lands_when_it_finishes():
    """הכתיבה היוצרת נכשלה — הסיום עדיין יוצר את המסמך.

    לפני השומר כל כתיבה הייתה ``upsert=True`` וריפאה מסמך חסר בעצמה. הגרסה
    הראשונה של השומר הורידה את זה גם מהמסלול הסופי — ושם אין במה להתנגש:
    המסנן הוא שוויון על ``run_id``, ואי-התאמה פירושה שאין מסמך בכלל. בלי
    ``upsert`` שם, הרצה שהתחילה בשגיאת מסד רגעית נעלמת מההיסטוריה לגמרי.
    """
    coll = _FailsOnFirstWrite()
    tracker = JobTracker(_db_with(coll))

    run = tracker.start_run("flaky_start")
    assert coll.find_one({"run_id": run.run_id}) is None  # הכתיבה הראשונה באמת נכשלה

    tracker.complete_run(run.run_id, result={"rows": 7})

    doc = coll.find_one({"run_id": run.run_id})
    assert doc is not None, "ההרצה הסתיימה בהצלחה ואין לה שום רשומה"
    assert doc["status"] == "completed"
    assert doc["result"] == {"rows": 7}


def test_a_persist_failure_is_reported_in_the_return_value_and_never_raised(caplog):
    """ערוץ הכשל של ``_persist_run`` הוא ערך ההחזרה — והוא נרשם, לא נבלע."""
    tracker = JobTracker(_db_with(_AlwaysFails()))

    run = tracker.start_run("no_db")  # לא זורק: גבול המסד אינו מפיל את הג'וב

    assert tracker._persist_run(run) is False
    assert "Failed to persist job run" in caplog.text


def test_a_log_line_pushed_by_another_writer_survives_the_runs_own_writes(tracker, mock_db):
    """הפיוס דוחף שורת לוג מבחוץ; הכתיבות של ההרצה עצמה אינן מוחקות אותה.

    ``$set`` על כל מערך ה-``logs`` מהזיכרון היה דורס כל מה שמישהו אחר דחף
    בינתיים — ואז, אחרי שהסטטוס תיקן את עצמו, לא נשאר שום זכר לכך שההרצה
    סומנה יתומה בטעות.
    """
    run = tracker.start_run("audited_job")
    stamp = datetime.now(timezone.utc)
    mock_db.runs.update_one(
        {"run_id": run.run_id},
        {
            "$push": {
                "logs": {
                    "$each": [{"timestamp": stamp, "level": "error", "message": "orphan-audit", "details": None}],
                    "$slice": -JOB_RUN_LOGS_KEPT,
                }
            }
        },
    )

    tracker.add_log(run.run_id, "info", "still working")
    tracker.complete_run(run.run_id)

    messages = [entry["message"] for entry in mock_db.runs.find_one({"run_id": run.run_id})["logs"]]
    assert messages == ["orphan-audit", "still working"]


def test_the_runs_own_log_lines_are_written_once_across_repeated_persists(tracker, mock_db):
    """כתיבה מצטברת אינה משכפלת: ``add_log`` שומר כל עשר שורות, ואז הסיום שומר שוב."""
    run = tracker.start_run("chatty_job")
    for i in range(12):
        tracker.add_log(run.run_id, "info", f"step {i}")
    tracker.complete_run(run.run_id)

    messages = [entry["message"] for entry in mock_db.runs.find_one({"run_id": run.run_id})["logs"]]
    assert messages == [f"step {i}" for i in range(12)]


def test_the_log_list_in_the_database_is_capped_at_the_shared_limit(tracker, mock_db):
    run = tracker.start_run("verbose_job")
    for i in range(JOB_RUN_LOGS_KEPT + 10):
        tracker.add_log(run.run_id, "info", f"step {i}")
    tracker.complete_run(run.run_id)

    logs = mock_db.runs.find_one({"run_id": run.run_id})["logs"]
    assert len(logs) == JOB_RUN_LOGS_KEPT
    assert logs[-1]["message"] == f"step {JOB_RUN_LOGS_KEPT + 9}"


def test_a_reconciled_run_read_back_carries_its_failure_reason(tracker, mock_db):
    """מי שקורא הרצה מהמסד רואה מי סגר אותה — לא רק שהיא ``failed``.

    ``/jobs <job_id>`` עובר דרך ``get_job_history`` ולכן דרך ``JobRun``; בלי
    השדה עליו, אותה הרצה נראית יתומה בפקודה אחת וכשל רגיל בפקודה השכנה.
    """
    run = tracker.start_run("orphaned_job")
    mock_db.runs.update_one(
        {"run_id": run.run_id},
        {"$set": {"status": "failed", "failure_reason": "orphaned"}},
    )
    tracker._active_runs.pop(run.run_id)  # תהליך חדש: אין כלום בזיכרון

    history = tracker.get_job_history("orphaned_job")

    assert history[0].failure_reason == "orphaned"
    assert tracker.get_run(run.run_id).failure_reason == "orphaned"


def test_the_runs_own_writes_never_carry_failure_reason():
    """ל-``failure_reason`` יש כותב אחד — הפיוס. ההרצה רק מנקה אותו.

    ``_persist_run`` שולח ``$unset`` על השדה בכל כתיבה. אילו היה גם ב-``$set``
    של אותו עדכון, מונגו הייתה דוחה את הכתיבה כולה על התנגשות נתיבים — וזו
    בדיוק רגרסיה שהדמה, שמחילה את שניהם בשקט, לא הייתה תופסת.
    """
    coll = _CapturesUpdates()
    tracker = JobTracker(_db_with(coll))
    run = tracker.start_run("relay_job")
    run.failure_reason = "orphaned"  # הרצה שנטענה ממסמך שכבר פויס נושאת אותו בזיכרון

    tracker.complete_run(run.run_id)

    last = coll.updates[-1]
    assert "failure_reason" not in last["$set"]
    assert "failure_reason" in last["$unset"]
    assert "failure_reason" not in coll.find_one({"run_id": run.run_id})
