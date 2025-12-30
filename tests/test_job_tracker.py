import pytest

from services.job_tracker import JobTracker, JobStatus
from services.job_registry import JobRegistry, register_job, JobCategory, JobType


@pytest.fixture
def tracker():
    """Tracker עם mock DB"""

    class MockCollection:
        def __init__(self):
            self.docs = {}

        def update_one(self, query, update, upsert=False):  # noqa: ARG002
            self.docs[query["run_id"]] = update["$set"]

        def find_one(self, query):
            return self.docs.get(query["run_id"])

        def find(self, query):
            return MockCursor(
                [d for d in self.docs.values() if d.get("job_id") == query.get("job_id")]
            )

    class MockCursor:
        def __init__(self, docs):
            self._docs = docs

        def sort(self, *args):  # noqa: ARG002
            return self

        def limit(self, n):
            self._docs = self._docs[:n]
            return self

        def __iter__(self):
            return iter(self._docs)

    class MockDB:
        def __init__(self):
            self.client = {"test": {"job_runs": MockCollection()}}
            self.db_name = "test"

    return JobTracker(MockDB())


def test_start_and_complete_run(tracker):
    run = tracker.start_run("test_job")
    assert run.status == JobStatus.RUNNING
    assert run.run_id in [r.run_id for r in tracker.get_active_runs()]

    tracker.complete_run(run.run_id, result={"count": 5})

    assert run.run_id not in [r.run_id for r in tracker.get_active_runs()]


def test_fail_run(tracker):
    run = tracker.start_run("test_job")
    tracker.fail_run(run.run_id, "Test error")

    assert run.status == JobStatus.FAILED
    assert run.error_message == "Test error"


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

