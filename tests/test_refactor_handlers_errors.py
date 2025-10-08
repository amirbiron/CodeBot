import pytest


@pytest.mark.asyncio
async def test_refactor_callback_missing_file(monkeypatch):
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # DB שמחזיר None
    class _DB:
        def get_file(self, user_id, filename):
            return None
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

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
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # DB בסיסי
    class _DB:
        def get_file(self, user_id, filename):
            return {"code": "def a():\n    return 1\n", "file_name": filename}
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

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

