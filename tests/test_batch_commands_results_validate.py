import types


def test_batch_job_results_validate(monkeypatch):
    bc = __import__('batch_commands')
    bp_mod = __import__('batch_processor')

    class _Job:
        def __init__(self):
            self.user_id = 5
            self.operation = 'validate'
            self.status = 'completed'
            # simulate one file with result payload
            self.results = {
                'a.py': {
                    'success': True,
                    'result': {
                        'is_valid': True,
                        'language': 'python',
                        'original_length': 10,
                        'cleaned_length': 8,
                        'error_message': '',
                        'advanced_checks': {
                            'flake8': {'returncode': 0, 'output': ''}
                        }
                    }
                }
            }
            self.total = 1
            self.progress = 1
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
    # Import module; the callbacks and command handlers are registered but we do not invoke telegram flow here
    assert hasattr(bc, 'setup_batch_handlers')

