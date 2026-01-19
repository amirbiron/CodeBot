import sys
import pytest


@pytest.mark.asyncio
async def test_refactor_callback_missing_file(monkeypatch):
    sys.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # Facade שמחזיר None
    class _Facade:
        def get_latest_version(self, user_id, filename):
            return None
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
    class _User: id = 9
    class _Upd:
        effective_user = _User()
        callback_query = _Q()
    class _Ctx: pass

    rh = RH(_App())
    _Upd.callback_query.data = 'refactor_type:split_functions:missing.py'
    await rh.handle_refactor_type_callback(_Upd, _Ctx())


@pytest.mark.asyncio
async def test_refactor_callback_invalid_type(monkeypatch):
    sys.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # Facade בסיסי
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
    class _User: id = 11
    class _Upd:
        effective_user = _User()
        callback_query = _Q()
    class _Ctx: pass

    rh = RH(_App())
    _Upd.callback_query.data = 'refactor_type:not_supported:file.py'
    await rh.handle_refactor_type_callback(_Upd, _Ctx())


@pytest.mark.asyncio
async def test_refactor_command_no_args(monkeypatch):
    sys.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _User: id = 1
    class _Upd:
        effective_user = _User()
        message = _Msg()
    class _Ctx:
        args = []

    rh = RH(_App())
    await rh.refactor_command(_Upd(), _Ctx())

