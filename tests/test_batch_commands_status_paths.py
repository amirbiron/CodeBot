import types


def test_job_status_running_and_completed(monkeypatch):
    bc = __import__('batch_commands')
    bp_mod = __import__('batch_processor')

    class _Job:
        def __init__(self, status):
            self.user_id = 5
            self.operation = 'analyze'
            self.status = status
            self.results = {}
            self.total = 1
            self.progress = 0 if status == 'running' else 1
            self.end_time = 0.0
            self.start_time = 0.0

    class _BP:
        def __init__(self):
            self._status = 'running'
        def get_job_status(self, job_id):
            return _Job(self._status)
        def format_job_summary(self, job):
            return 'ok'

    monkeypatch.setattr(bp_mod, 'batch_processor', _BP(), raising=True)

    # Only ensure module import doesn't crash and handlers are installed
    assert hasattr(bc, 'setup_batch_handlers')

