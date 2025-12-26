# tests/test_job_tracker.py
"""
Unit Tests עבור JobTracker ו-JobRegistry.
"""

import pytest
from unittest.mock import MagicMock

from services.job_tracker import (
    JobTracker,
    JobStatus,
    JobAlreadyRunningError,
    get_job_tracker,
    reset_job_tracker,
)
from services.job_registry import (
    JobRegistry,
    register_job,
    JobCategory,
    JobType,
)


# === Mock DB classes ===

class MockCollection:
    """Mock MongoDB collection"""
    def __init__(self):
        self.docs: dict = {}

    def update_one(self, query, update, upsert=False):
        run_id = query.get("run_id")
        if run_id:
            self.docs[run_id] = update.get("$set", {})
        return MagicMock(acknowledged=True, modified_count=1)

    def find_one(self, query):
        run_id = query.get("run_id")
        return self.docs.get(run_id)

    def find(self, query):
        job_id = query.get("job_id")
        status = query.get("status")
        results = []
        for doc in self.docs.values():
            if job_id and doc.get("job_id") != job_id:
                continue
            if status and doc.get("status") != status:
                continue
            results.append(doc)
        return MockCursor(results)


class MockCursor:
    """Mock MongoDB cursor"""
    def __init__(self, docs):
        self._docs = docs

    def sort(self, *args):
        return self

    def limit(self, n):
        self._docs = self._docs[:n]
        return self

    def __iter__(self):
        return iter(self._docs)


class MockDB:
    """Mock database manager"""
    def __init__(self):
        self._collections: dict = {}
        self.db_name = "test"

    @property
    def client(self):
        return {self.db_name: self}

    def __getitem__(self, name: str):
        if name not in self._collections:
            self._collections[name] = MockCollection()
        return self._collections[name]


# === Fixtures ===

@pytest.fixture
def tracker():
    """Tracker with mock DB"""
    mock_db = MockDB()
    return JobTracker(mock_db)


@pytest.fixture
def registry():
    """Clean registry for each test"""
    reg = JobRegistry()
    reg.clear()
    return reg


# === JobTracker Tests ===

class TestJobTracker:
    """Tests for JobTracker"""

    def test_start_and_complete_run(self, tracker):
        """Test starting and completing a job run"""
        run = tracker.start_run("test_job")

        assert run.status == JobStatus.RUNNING
        assert run.run_id in [r.run_id for r in tracker.get_active_runs()]

        tracker.complete_run(run.run_id, result={"count": 5})

        assert run.run_id not in [r.run_id for r in tracker.get_active_runs()]

    def test_fail_run(self, tracker):
        """Test failing a job run"""
        run = tracker.start_run("test_job")
        tracker.fail_run(run.run_id, "Test error")

        assert run.status == JobStatus.FAILED
        assert run.error_message == "Test error"

    def test_track_context_manager_success(self, tracker):
        """Test track context manager on success"""
        with tracker.track("test_job") as run:
            tracker.add_log(run.run_id, "info", "Processing...")

        assert run.status == JobStatus.COMPLETED
        assert run.progress == 100

    def test_track_context_manager_failure(self, tracker):
        """Test track context manager on error"""
        with pytest.raises(ValueError):
            with tracker.track("test_job") as run:
                raise ValueError("Oops")

        assert run.status == JobStatus.FAILED
        assert "Oops" in run.error_message

    def test_update_progress(self, tracker):
        """Test updating progress"""
        run = tracker.start_run("test_job", total_items=100)

        tracker.update_progress(run.run_id, processed=50)
        assert run.progress == 50
        assert run.processed_items == 50

        tracker.update_progress(run.run_id, processed=100)
        assert run.progress == 100

    def test_add_log(self, tracker):
        """Test adding logs"""
        run = tracker.start_run("test_job")

        tracker.add_log(run.run_id, "info", "Step 1")
        tracker.add_log(run.run_id, "warning", "Step 2")
        tracker.add_log(run.run_id, "error", "Step 3 failed")

        assert len(run.logs) == 3
        assert run.logs[0].level == "info"
        assert run.logs[2].level == "error"

    def test_prevent_concurrent_runs(self, tracker):
        """Test that concurrent runs are prevented by default"""
        run1 = tracker.start_run("singleton_job")

        with pytest.raises(JobAlreadyRunningError):
            tracker.start_run("singleton_job")

        # After completing, should allow new run
        tracker.complete_run(run1.run_id)
        run2 = tracker.start_run("singleton_job")
        assert run2.run_id != run1.run_id

    def test_allow_concurrent_runs(self, tracker):
        """Test that concurrent runs can be allowed"""
        run1 = tracker.start_run("parallel_job", allow_concurrent=True)
        run2 = tracker.start_run("parallel_job", allow_concurrent=True)

        assert run1.run_id != run2.run_id
        assert len(tracker.get_active_runs()) == 2

    def test_get_active_runs(self, tracker):
        """Test getting active runs"""
        run1 = tracker.start_run("job1", allow_concurrent=True)
        run2 = tracker.start_run("job2", allow_concurrent=True)

        active = tracker.get_active_runs()
        assert len(active) == 2
        assert run1.run_id in [r.run_id for r in active]
        assert run2.run_id in [r.run_id for r in active]

        tracker.complete_run(run1.run_id)
        active = tracker.get_active_runs()
        assert len(active) == 1

    def test_run_with_user_id(self, tracker):
        """Test run with user_id"""
        run = tracker.start_run("user_job", user_id=12345, trigger="manual")

        assert run.user_id == 12345
        assert run.trigger == "manual"


class TestJobTrackerPersistence:
    """Tests for JobTracker persistence"""

    def test_persist_run_to_db(self, tracker):
        """Test that runs are persisted to DB"""
        run = tracker.start_run("test_job")
        tracker.add_log(run.run_id, "info", "Test message")
        tracker.complete_run(run.run_id)

        # Check that doc was saved - access through the mock structure
        collection = tracker._db._collections.get("job_runs")
        assert collection is not None
        doc = collection.docs.get(run.run_id)
        assert doc is not None
        assert doc["job_id"] == "test_job"
        assert doc["status"] == "completed"

    def test_get_run_from_db(self, tracker):
        """Test getting a run from DB"""
        run = tracker.start_run("test_job")
        tracker.complete_run(run.run_id)

        # Remove from active runs to force DB lookup
        tracker._active_runs.clear()

        retrieved = tracker.get_run(run.run_id)
        assert retrieved is not None
        assert retrieved.job_id == "test_job"

    def test_get_job_history(self, tracker):
        """Test getting job history"""
        # Create multiple runs
        for i in range(3):
            run = tracker.start_run("history_job", allow_concurrent=True)
            tracker.complete_run(run.run_id)

        history = tracker.get_job_history("history_job", limit=10)
        assert len(history) == 3


# === JobRegistry Tests ===

class TestJobRegistry:
    """Tests for JobRegistry"""

    def test_registry_singleton(self, registry):
        """Test that JobRegistry is a singleton"""
        reg1 = JobRegistry()
        reg2 = JobRegistry()
        assert reg1 is reg2

    def test_register_and_get_job(self, registry):
        """Test registering and getting a job"""
        register_job(
            job_id="test_backup",
            name="Test Backup",
            description="A test job",
            category=JobCategory.BACKUP,
            job_type=JobType.REPEATING,
            interval_seconds=3600
        )

        retrieved = registry.get("test_backup")
        assert retrieved is not None
        assert retrieved.job_id == "test_backup"
        assert retrieved.name == "Test Backup"
        assert retrieved.interval_seconds == 3600

    def test_list_all_jobs(self, registry):
        """Test listing all jobs"""
        register_job(
            job_id="job1",
            name="Job 1",
            description="First job",
            category=JobCategory.CACHE,
            job_type=JobType.REPEATING
        )
        register_job(
            job_id="job2",
            name="Job 2",
            description="Second job",
            category=JobCategory.BACKUP,
            job_type=JobType.ONCE
        )

        jobs = registry.list_all()
        assert len(jobs) == 2

    def test_list_by_category(self, registry):
        """Test listing jobs by category"""
        register_job(
            job_id="cache1",
            name="Cache 1",
            description="Cache job",
            category=JobCategory.CACHE,
            job_type=JobType.REPEATING
        )
        register_job(
            job_id="backup1",
            name="Backup 1",
            description="Backup job",
            category=JobCategory.BACKUP,
            job_type=JobType.REPEATING
        )

        cache_jobs = registry.list_by_category(JobCategory.CACHE)
        assert len(cache_jobs) == 1
        assert cache_jobs[0].job_id == "cache1"

    def test_is_enabled_default(self, registry):
        """Test is_enabled with default enabled=True"""
        register_job(
            job_id="enabled_job",
            name="Enabled Job",
            description="Should be enabled",
            category=JobCategory.OTHER,
            job_type=JobType.ONCE,
            enabled=True
        )

        assert registry.is_enabled("enabled_job") is True

    def test_is_enabled_with_env_toggle(self, registry, monkeypatch):
        """Test is_enabled with env_toggle"""
        register_job(
            job_id="toggle_job",
            name="Toggle Job",
            description="Controlled by env",
            category=JobCategory.OTHER,
            job_type=JobType.ONCE,
            env_toggle="MY_JOB_ENABLED"
        )

        # Not set - should be disabled
        monkeypatch.delenv("MY_JOB_ENABLED", raising=False)
        assert registry.is_enabled("toggle_job") is False

        # Set to true
        monkeypatch.setenv("MY_JOB_ENABLED", "true")
        assert registry.is_enabled("toggle_job") is True

        # Set to false
        monkeypatch.setenv("MY_JOB_ENABLED", "false")
        assert registry.is_enabled("toggle_job") is False

    def test_is_enabled_nonexistent_job(self, registry):
        """Test is_enabled for nonexistent job"""
        assert registry.is_enabled("nonexistent") is False


# === Integration Tests ===

class TestJobTrackerRegistryIntegration:
    """Integration tests for JobTracker and JobRegistry"""

    def test_tracker_with_registered_job(self, tracker, registry):
        """Test using tracker with a registered job"""
        register_job(
            job_id="integrated_job",
            name="Integrated Job",
            description="Test integration",
            category=JobCategory.MONITORING,
            job_type=JobType.REPEATING,
            interval_seconds=60
        )

        job = registry.get("integrated_job")
        assert job is not None

        with tracker.track(job.job_id) as run:
            tracker.add_log(run.run_id, "info", f"Running {job.name}")

        assert run.status == JobStatus.COMPLETED


# === Global Singleton Tests ===

class TestGlobalSingleton:
    """Tests for global singleton functions"""

    def test_get_job_tracker_singleton(self):
        """Test that get_job_tracker returns singleton"""
        reset_job_tracker()

        tracker1 = get_job_tracker()
        tracker2 = get_job_tracker()

        assert tracker1 is tracker2

    def test_reset_job_tracker(self):
        """Test resetting the tracker singleton"""
        tracker1 = get_job_tracker()
        reset_job_tracker()
        tracker2 = get_job_tracker()

        assert tracker1 is not tracker2
