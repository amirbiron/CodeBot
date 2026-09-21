"""``/jobs`` — פקודת ה-ChatOps, דרך הממשק שהמשתמש מפעיל.

הקובץ ``chatops/jobs_commands.py`` לא היה לו אף טסט. הטסטים כאן עוברים דרך
``handle_jobs_command`` האמיתי, מול ``JobTracker`` אמיתי ודמת מונגו
משותפת — כי מה שהפקודה מדפיסה נגזר ממה שנכתב למסד, ולא מהאובייקט בזיכרון.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import chatops.jobs_commands as jobs_commands
from services.job_orphan_reconciler import ORPHANED_ERROR_MESSAGE, ORPHANED_FAILURE_REASON
from services.job_registry import JobCategory, JobRegistry, JobType, register_job
from services.job_tracker import JobTracker

# ‏``tests`` אינו חבילה, וב-CI יש חבילת ``tests`` זרה שמאפילה עליו —
# ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeTrackerDB

JOB_ID = "orphan_probe"  # הפקודה מנרמלת ל-lowercase, ולכן גם המזהה


@pytest.fixture
def tracker(monkeypatch):
    db = FakeTrackerDB()
    t = JobTracker(db)
    monkeypatch.setattr(jobs_commands, "get_job_tracker", lambda: t)
    JobRegistry()._jobs.clear()
    register_job(
        job_id=JOB_ID,
        name="Orphan probe",
        description="probe",
        category=JobCategory.OTHER,
        job_type=JobType.REPEATING,
        interval_seconds=60,
    )
    return t


def _close_as_orphan(tracker: JobTracker, run_id: str, *, started_at: datetime | None = None) -> None:
    """מה שהפיוס עושה לרשומה, בלי להריץ את הפיוס: כתיבה חיצונית + שכחה מהזיכרון."""
    now = datetime.now(timezone.utc)
    fields = {
        "status": "failed",
        "ended_at": now,
        "error_message": ORPHANED_ERROR_MESSAGE,
        "failure_reason": ORPHANED_FAILURE_REASON,
    }
    if started_at is not None:
        fields["started_at"] = started_at
    tracker.db.runs.update_one({"run_id": run_id}, {"$set": fields})
    tracker._active_runs.pop(run_id, None)


def test_failed_marks_an_orphan_with_a_ghost_and_a_real_failure_with_a_cross(tracker):
    real = tracker.start_run(JOB_ID, allow_concurrent=True)
    tracker.fail_run(real.run_id, "boom")
    orphan = tracker.start_run(JOB_ID, allow_concurrent=True)
    _close_as_orphan(tracker, orphan.run_id)

    out = jobs_commands.handle_jobs_command("failed")

    ghost_block = out[out.index("👻"):]
    cross_block = out[out.index("❌ `"):]
    assert ORPHANED_ERROR_MESSAGE in ghost_block.split("\n   [")[0]
    assert "boom" in cross_block.split("\n   [")[0]


def test_a_specific_jobs_history_marks_the_same_orphan_the_same_way(tracker):
    """אותה הרצה, שתי פקודות שכנות, אותו סימון — אחרת ההבחנה תלויה באיזו פקודה שאלו."""
    real = tracker.start_run(JOB_ID, allow_concurrent=True)
    tracker.fail_run(real.run_id, "boom")
    orphan = tracker.start_run(JOB_ID, allow_concurrent=True)
    _close_as_orphan(tracker, orphan.run_id)

    out = jobs_commands.handle_jobs_command(JOB_ID)

    history = out[out.index("הרצות אחרונות"):]
    assert history.count("👻") == 1
    assert history.count("❌") == 1


def test_a_long_run_is_shown_in_days_not_in_a_million_seconds(tracker):
    """הרצה שנתקעה שלושה שבועות ונסגרה בפיוס — לא ``(1814400.0s)``.

    הפורמט נגזר מ-``_format_interval`` שכבר יושב באותו קובץ, ולא מכלל שני.
    """
    run = tracker.start_run(JOB_ID)
    _close_as_orphan(tracker, run.run_id, started_at=datetime.now(timezone.utc) - timedelta(days=21))

    out = jobs_commands.handle_jobs_command(JOB_ID)

    assert "21 ימים" in out
    assert "1814400" not in out


def test_no_failures_says_so(tracker):
    assert "אין כשלים" in jobs_commands.handle_jobs_command("failed")
