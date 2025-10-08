import types


def test_batch_callbacks_status_and_results(monkeypatch):
    bc = __import__('batch_commands')
    bp_mod = __import__('batch_processor')

    class _Job:
        def __init__(self, op, status):
            self.user_id = 9
            self.operation = op
            self.status = status
            self.results = {}
            self.total = 1
            self.progress = 0 if status == 'running' else 1
            self.end_time = 1.0
            self.start_time = 0.0

    class _BP:
        def __init__(self):
            self._job = _Job('analyze', 'running')
        def get_job_status(self, job_id):
            return self._job
        def format_job_summary(self, job):
            return 'ok'

    monkeypatch.setattr(bp_mod, 'batch_processor', _BP(), raising=True)
    assert hasattr(bc, 'setup_batch_handlers')

