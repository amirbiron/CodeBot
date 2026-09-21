import pytest

from services.job_tracker import JobTracker, JobStatus
# ‏``tests`` אינו חבילה, וב-CI יש חבילת ``tests`` זרה שמאפילה עליו —
# ראה את ה-docstring של ``tests/conftest.py``.
from _fake_mongo import FakeDB
from services.job_registry import JobRegistry, register_job, JobCategory, JobType


class _MockDB:
    """‏``db.client[db_name]["job_runs"]`` — הדרך שבה ``JobTracker`` מגיע לאוסף."""

    def __init__(self):
        self.db = FakeDB("test")
        self.client = {"test": self.db}
        self.db_name = "test"

    @property
    def runs(self):
        return self.db["job_runs"]


@pytest.fixture
def mock_db():
    return _MockDB()


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

