import sys
import types
import pytest


@pytest.mark.asyncio
async def test_job_status_and_results_running_and_completed(monkeypatch):
    # טען batch_commands וצרוב מצב עבודה running ואז completed
    sys.modules.pop('batch_commands', None)
    mod = __import__('batch_commands')

    # Stub application and telegram message
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _User: id = 42
    class _Upd:
        effective_user = _User()
        message = _Msg()
        class _Q:
            data = ''
            message = _Msg()
            async def answer(self, *a, **k): return None
            async def edit_message_text(self, *a, **k): return None
        callback_query = _Q()
    class _Ctx:
        args = []
        class _App:
            job_queue = types.SimpleNamespace(run_once=lambda f, when=0: None)
        application = _App()

    # צור עבודה ידנית דרך הprocessor
    bp = __import__('batch_processor').batch_processor
    job_id = bp.create_job(_Upd.effective_user.id, 'analyze', ['a.py','b.py'])
    job = bp.get_job_status(job_id)
    job.status = 'running'
    job.progress = 1
    # בדיקת פקודת סטטוס ללא פרמטרים (רשימת עבודות)
    await mod.job_status_command(_Upd(), _Ctx())

    # בדיקת callback של job_status (running)
    _Upd.callback_query.data = f'job_status:{job_id}'
    await mod.handle_batch_callbacks(_Upd(), _Ctx())

    # סמן עבודה כ-completed והוסף תוצאות
    job.status = 'completed'
    job.progress = job.total
    job.results = {'a.py': {'success': True}, 'b.py': {'success': False}}

    # בדיקת callback של job_status (completed) ואז job_results
    _Upd.callback_query.data = f'job_status:{job_id}'
    await mod.handle_batch_callbacks(_Upd(), _Ctx())
    _Upd.callback_query.data = f'job_results:{job_id}'
    await mod.handle_batch_callbacks(_Upd(), _Ctx())

