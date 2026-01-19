import sys
import pytest


@pytest.mark.asyncio
async def test_approve_uses_save_code_when_available(monkeypatch):
    sys.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    class _Facade:
        def __init__(self):
            self.save_file_called = False
        def get_latest_version(self, user_id, filename):
            code = (
                "def user_a():\n    return 1\n\n"
                "def data_b():\n    return 2\n"
            )
            return {"code": code, "file_name": filename, "programming_language": "python"}
        def save_file(self, *a, **k):
            self.save_file_called = True
            return True
        def insert_refactor_metadata(self, doc):
            return True
    inst = _Facade()
    monkeypatch.setattr(mod, "_get_files_facade_or_none", lambda: inst)

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
    class _User: id = 10
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

    assert inst.save_file_called is True

