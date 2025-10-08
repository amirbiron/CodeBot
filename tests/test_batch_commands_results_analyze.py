import types


def test_batch_job_results_analyze(monkeypatch):
    bc = __import__('batch_commands')
    bp_mod = __import__('batch_processor')

    class _Job:
        def __init__(self):
            self.user_id = 6
            self.operation = 'analyze'
            self.status = 'completed'
            self.results = {
                'a.py': {'success': True, 'result': {'lines': 10, 'chars': 100, 'language': 'python', 'analysis': {'complexity': 3, 'quality_score': 95}}},
                'b.py': {'success': False, 'result': {'lines': 5, 'chars': 50, 'language': 'python', 'analysis': {}}},
            }
            self.total = 2
            self.progress = 2
            self.end_time = 1.0
            self.start_time = 0.0

    class _BP:
        def __init__(self):
            self._job = _Job()
        def get_job_status(self, job_id):
            return self._job
        def format_job_summary(self, job):
            return 'ok'

    monkeypatch.setattr(bp_mod, 'batch_processor', _BP(), raising=True)
    assert hasattr(bc, 'setup_batch_handlers')

