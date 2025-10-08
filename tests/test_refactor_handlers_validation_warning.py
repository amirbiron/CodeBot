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

    # Stub DB and build a proposal עם ולידציה שקרית
    class _DB:
        def __init__(self):
            class _C:
                def insert_one(self, doc):
                    return types.SimpleNamespace(inserted_id="1")
            self._c = _C()
        def get_file(self, user_id, filename):
            return {"code": "def a():\n    return 1\n\n", "file_name": filename}
        def collection(self, name):
            return self._c
    db_mod = __import__('database', fromlist=['db'])
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    rh = RH(_App())
    upd = _Upd()
    upd.callback_query.data = 'refactor_type:split_functions:file.py'
    await rh.handle_refactor_type_callback(upd, _Ctx())
    # נכריח ולידציה להחשב כ-false ע"י הכנסת קובץ לא חוקי
    prop = rh.pending_proposals[upd.effective_user.id]
    # הפיכת אחד הקבצים ללא תקין
    for k in list(prop.new_files.keys()):
        if k.endswith('.py'):
            prop.new_files[k] = 'def broken('
            break
    # הצגה – כדי להגיע לענף האזהרה, נקרא לפונקציה הפרטית דרך המסלול הציבורי preview
    upd.callback_query.data = 'refactor_action:preview'
    await rh.handle_proposal_callback(upd, _Ctx())

