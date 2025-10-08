import pytest


@pytest.mark.asyncio
async def test_job_results_running_path(monkeypatch):
    bc = __import__('batch_commands')

    class _Q:
        data = 'job_results:jid-1'
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            self.edited = True
            return None
    class _Upd:
        def __init__(self):
            self.callback_query = _Q()
            class _U: id = 7
            self.effective_user = _U()
    class _Ctx:
        user_data = {}

    class _Job:
        def __init__(self):
            self.user_id = 7
            self.status = 'running'
            self.operation = 'analyze'
            self.results = {}
    class _BP:
        def get_job_status(self, jid):
            return _Job()
        def format_job_summary(self, job):
            return 'running summary'
    monkeypatch.setattr(bc, 'batch_processor', _BP(), raising=True)

    await bc.handle_batch_callbacks(_Upd(), _Ctx())

