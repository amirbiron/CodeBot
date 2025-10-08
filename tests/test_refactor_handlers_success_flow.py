import sys
import types
import pytest


@pytest.mark.asyncio
async def test_refactor_split_preview_approve_success(monkeypatch):
    sys.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def __init__(self):
            self.handlers = []
        def add_handler(self, *a, **k):
            self.handlers.append((a, k))

    # DB stub: code designed to split by prefix into 2 groups (user_*, data_*)
    class _DB:
        def __init__(self):
            self.saved = {}
            class _Coll:
                def insert_one(self, doc):
                    return types.SimpleNamespace(inserted_id="1")
            self._coll = _Coll()
        def get_file(self, user_id, filename):
            code = (
                "def user_login(x):\n    return True\n\n"
                "def user_logout(x):\n    return True\n\n"
                "def data_fetch(q):\n    return []\n\n"
                "def data_save(d):\n    return True\n"
            )
            return {"code": code, "file_name": filename, "programming_language": "python"}
        def save_file(self, user_id: int, file_name: str, code: str, programming_language: str, extra_tags=None):
            self.saved[file_name] = code
            return True
        def collection(self, name):
            return self._coll
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    # Stubs for telegram
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _Q:
        def __init__(self):
            self.data = ''
            self.message = _Msg()
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _User: id = 77
    class _Upd:
        def __init__(self):
            self.effective_user = _User()
            self.callback_query = _Q()
            self.message = _Msg()
    class _Ctx: pass

    rh = RH(_App())

    upd = _Upd()
    # trigger menu via command
    class _CtxArgs:
        args = ["file.py"]
    await rh.refactor_command(upd, _CtxArgs())

    # choose split
    upd.callback_query.data = 'refactor_type:split_functions:file.py'
    await rh.handle_refactor_type_callback(upd, _Ctx())
    # preview
    upd.callback_query.data = 'refactor_action:preview'
    await rh.handle_proposal_callback(upd, _Ctx())
    # approve
    upd.callback_query.data = 'refactor_action:approve'
    await rh.handle_proposal_callback(upd, _Ctx())


@pytest.mark.asyncio
async def test_refactor_type_cancel_flow(monkeypatch):
    sys.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _Q:
        data = 'refactor_type:cancel'
        message = _Msg()
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _User: id = 88
    class _Upd:
        effective_user = _User()
        callback_query = _Q()
    class _Ctx: pass

    rh = RH(_App())
    await rh.handle_refactor_type_callback(_Upd(), _Ctx())

