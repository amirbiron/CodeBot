import pytest


@pytest.mark.asyncio
async def test_batch_analyze_and_validate_args_paths(monkeypatch):
    bc = __import__('batch_commands')

    class _DB:
        def get_user_files(self, user_id, limit=1000):
            return [{"file_name": "a.py", "programming_language": "python"}, {"file_name": "b.js", "programming_language": "javascript"}]
    monkeypatch.setattr(bc, 'db', _DB(), raising=True)

    class _BP:
        async def analyze_files_batch(self, user_id, files):
            return 'job-analyze'
        async def validate_files_batch(self, user_id, files):
            return 'job-validate'
    monkeypatch.setattr(bc, 'batch_processor', _BP(), raising=True)

    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _Upd:
        effective_user = type('U', (), {'id': 1})()
        message = _Msg()

    # analyze: all
    class _CtxAll:
        args = ['all']
        application = None
    await bc.batch_analyze_command(_Upd(), _CtxAll())

    # analyze: python
    class _CtxPy:
        args = ['python']
        application = None
    await bc.batch_analyze_command(_Upd(), _CtxPy())

    # validate: explicit list
    class _CtxVal:
        args = ['a.py', 'b.js']
        application = None
    await bc.batch_validate_command(_Upd(), _CtxVal())

