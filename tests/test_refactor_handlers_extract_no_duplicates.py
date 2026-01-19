import sys
import pytest


@pytest.mark.asyncio
async def test_extract_functions_no_duplicates_shows_error(monkeypatch):
    sys.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass
    class _Facade:
        def get_latest_version(self, user_id, filename):
            return {"code": "def a():\n    return 1\n", "file_name": filename}
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: _Facade())
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _Q:
        data = 'refactor_type:extract_functions:file.py'
        message = _Msg()
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _User: id = 12
    class _Upd:
        effective_user = _User()
        callback_query = _Q()
    class _Ctx: pass

    rh = RH(_App())
    await rh.handle_refactor_type_callback(_Upd(), _Ctx())

