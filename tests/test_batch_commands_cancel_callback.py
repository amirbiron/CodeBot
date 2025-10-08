import pytest


@pytest.mark.asyncio
async def test_batch_callbacks_job_cancel(monkeypatch):
    bc = __import__('batch_commands')

    class _Q:
        data = 'job_cancel:job-1'
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _User:
        id = 1
    class _Upd:
        def __init__(self):
            self.callback_query = _Q()
            self.effective_user = _User()
    class _Ctx:
        user_data = {}

    cancelled = {}
    class _BP:
        def cancel_job(self, job_id):
            cancelled['id'] = job_id
            return True
    monkeypatch.setattr(bc, 'batch_processor', _BP(), raising=True)

    await bc.handle_batch_callbacks(_Upd(), _Ctx())
    assert cancelled.get('id') == 'job-1'

