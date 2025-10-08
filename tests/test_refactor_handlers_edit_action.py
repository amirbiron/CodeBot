import pytest


@pytest.mark.asyncio
async def test_refactor_action_edit_alert(monkeypatch):
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            pass

    # Stub DB to ensure a proposal is created first
    class _DB:
        def get_file(self, user_id, filename):
            return {"code": "def x():\n    return 1\n\ndef y():\n    return 2\n", "file_name": filename, "programming_language": "python"}
        def collection(self, name):
            class _C:
                def insert_one(self, doc):
                    return type('R', (), {"inserted_id": "1"})
            return _C()
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
    class _User: id = 101
    class _Upd:
        effective_user = _User()
        callback_query = _Q()
    class _Ctx: pass

    rh = RH(_App())
    # Create proposal
    _Upd.callback_query.data = 'refactor_type:split_functions:file.py'
    await rh.handle_refactor_type_callback(_Upd, _Ctx())
    # Trigger edit action (should only show alert and return)
    _Upd.callback_query.data = 'refactor_action:edit'
    await rh.handle_proposal_callback(_Upd, _Ctx())

