import sys
import pytest


@pytest.mark.asyncio
async def test_handlers_engine_failure_message(monkeypatch):
    sys.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # Facade returns minimal code but we'll force engine to error by choosing feature not implemented
    class _Facade:
        def get_latest_version(self, user_id, filename):
            return {"code": "def a():\n    return 1\n", "file_name": filename}
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())

    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _Q:
        data = ''
        message = _Msg()
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _User: id = 42
    class _Upd:
        effective_user = _User()
        callback_query = _Q()
    class _Ctx: pass

    rh = RH(_App())
    _Upd.callback_query.data = 'refactor_type:merge_similar:file.py'
    await rh.handle_refactor_type_callback(_Upd, _Ctx())

