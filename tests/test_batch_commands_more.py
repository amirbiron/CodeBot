import types


def test_batch_validate_and_export_imports(monkeypatch):
    bc = __import__('batch_commands')
    bp_mod = __import__('batch_processor')

    class _Job:
        def __init__(self, op, status='completed'):
            self.user_id = 3
            self.operation = op
            self.status = status
            self.results = {}
            self.total = 1
            self.progress = 1
            self.end_time = 1.0
            self.start_time = 0.0

    class _BP:
        def __init__(self):
            self._job = _Job('validate')
        def get_job_status(self, job_id):
            return self._job
        def format_job_summary(self, job):
            return 'ok'
    monkeypatch.setattr(bp_mod, 'batch_processor', _BP(), raising=True)

    # module import check
    assert hasattr(bc, 'setup_batch_handlers')

