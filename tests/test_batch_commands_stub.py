import types
import pytest


@pytest.fixture(autouse=True)
def stub_batch(monkeypatch):
    # Stub batch_processor with predictable job
    bp_mod = __import__('batch_processor')
    class _BP:
        class _Job:
            def __init__(self):
                self.user_id = 1
                self.operation = 'analyze'
                self.status = 'completed'
                self.results = {}
                self.total = 1
                self.progress = 1
                self.end_time = 1.0
                self.start_time = 0.0
        def get_job_status(self, job_id):
            return self._Job()
        def format_job_summary(self, job):
            return "ok"
    monkeypatch.setattr(bp_mod, 'batch_processor', _BP(), raising=True)
    return bp_mod.batch_processor


def test_batch_commands_imports_only():
    __import__('batch_commands')

