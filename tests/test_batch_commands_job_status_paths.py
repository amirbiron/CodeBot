import types
import pytest


@pytest.mark.asyncio
async def test_job_status_list_and_not_found(monkeypatch):
    mod = __import__('batch_commands')
    bp_mod = __import__('batch_processor')

    class _Job:
        def __init__(self):
            self.user_id = 111
            self.operation = 'analyze'
            self.status = 'running'
            self.results = {}
            self.total = 1
            self.progress = 0
            self.end_time = 0.0
            self.start_time = 0.0

    class _BP:
        def __init__(self):
            self.active_jobs = {'job1': _Job()}
        def get_job_status(self, job_id):
            return None if job_id == 'unknown' else self.active_jobs.get(job_id)
        def format_job_summary(self, job):
            return 'ok'

    monkeypatch.setattr(bp_mod, 'batch_processor', _BP(), raising=True)

    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _User: id = 111
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        args = []

    # list active jobs path
    await mod.job_status_command(_Upd(), _Ctx())

    # not found path
    class _CtxNF:
        args = ['unknown']
    await mod.job_status_command(_Upd(), _CtxNF())

