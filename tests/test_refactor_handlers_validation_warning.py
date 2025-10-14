import sys
import types
import pytest


@pytest.mark.asyncio
async def test_display_proposal_with_validation_warning(monkeypatch):
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
        def __init__(self):
            self.data = ''
            self.message = _Msg()
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _User: id = 55
    class _Upd:
        def __init__(self):
            self.effective_user = _User()
            self.callback_query = _Q()
            self.message = _Msg()
    class _Ctx: pass

    # Stub DB and build a proposal; נכריח ולידציה להחשב False באמצעות monkeypatch
    class _DB:
        def __init__(self):
            class _C:
                def insert_one(self, doc):
                    return types.SimpleNamespace(inserted_id="1")
            self._c = _C()
        def get_file(self, user_id, filename):
            code = (
                "def user_a():\n    return 1\n\n"
                "def data_b():\n    return 2\n"
            )
            return {"code": code, "file_name": filename, "programming_language": "python"}
        def collection(self, name):
            return self._c
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    # כפה ולידציה False בזמן יצירת ההצעה
    rh_engine = getattr(mod, 'refactoring_engine')
    monkeypatch.setattr(rh_engine, '_validate_proposal', lambda p: False, raising=True)

    rh = RH(_App())
    upd = _Upd()
    upd.callback_query.data = 'refactor_type:split_functions:file.py'
    await rh.handle_refactor_type_callback(upd, _Ctx())

