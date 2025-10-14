import sys
import types
import pytest


@pytest.mark.asyncio
async def test_refactor_preview_truncates_long_content(monkeypatch):
    sys.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # DB returns code that causes split to succeed
    class _DB:
        def __init__(self):
            class _C:
                def insert_one(self, doc):
                    return types.SimpleNamespace(inserted_id="1")
            self._c = _C()
        def get_file(self, user_id, filename):
            code = (
                "def user_a():\n    return True\n\n"
                "def user_b():\n    return True\n\n"
                "def data_a():\n    return []\n\n"
                "def data_b():\n    return []\n"
            )
            return {"code": code, "file_name": filename, "programming_language": "python"}
        def collection(self, name):
            return self._c
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

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
    class _User: id = 2
    class _Upd:
        def __init__(self):
            self.effective_user = _User()
            self.callback_query = _Q()
            self.message = _Msg()
    class _Ctx: pass

    rh = RH(_App())
    upd = _Upd()
    # build proposal
    upd.callback_query.data = 'refactor_type:split_functions:file.py'
    await rh.handle_refactor_type_callback(upd, _Ctx())
    # force long preview by duplicating content inside proposal
    prop = rh.pending_proposals[upd.effective_user.id]
    for k in list(prop.new_files.keys()):
        prop.new_files[k] = prop.new_files[k] * 200  # make it > 3000 chars
    upd.callback_query.data = 'refactor_action:preview'
    await rh.handle_proposal_callback(upd, _Ctx())


@pytest.mark.asyncio
async def test_refactor_approve_with_save_error(monkeypatch):
    sys.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # DB fails on save_file to exercise error aggregation
    class _DB:
        def __init__(self):
            class _C:
                def insert_one(self, doc):
                    return types.SimpleNamespace(inserted_id="1")
            self._c = _C()
        def get_file(self, user_id, filename):
            code = (
                "def user_a():\n    return True\n\n"
                "def user_b():\n    return True\n\n"
                "def data_a():\n    return []\n\n"
                "def data_b():\n    return []\n"
            )
            return {"code": code, "file_name": filename, "programming_language": "python"}
        def save_file(self, *a, **k):
            raise RuntimeError("db error")
        def collection(self, name):
            return self._c
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

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
    class _User: id = 3
    class _Upd:
        def __init__(self):
            self.effective_user = _User()
            self.callback_query = _Q()
            self.message = _Msg()
    class _Ctx: pass

    rh = RH(_App())
    upd = _Upd()
    upd.callback_query.data = 'refactor_type:split_functions:file.py'
    await rh.handle_refactor_type_callback(upd, _Ctx())
    upd.callback_query.data = 'refactor_action:approve'
    await rh.handle_proposal_callback(upd, _Ctx())

