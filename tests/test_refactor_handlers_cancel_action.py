import pytest


@pytest.mark.asyncio
async def test_refactor_handlers_cancel_action(monkeypatch):
    sys_mod = __import__('sys')
    sys_mod.modules.pop('refactor_handlers', None)
    mod = __import__('refactor_handlers')
    RH = getattr(mod, 'RefactorHandlers')

    class _App:
        def add_handler(self, *a, **k):
            return None
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
    class _User: id = 9
    class _Upd:
        def __init__(self):
            self.effective_user = _User()
            self.callback_query = _Q()
            self.message = _Msg()
    class _Ctx: pass

    rh = RH(_App())
    # שים הצעה ממתינה מזויפת
    from refactoring_engine import RefactorProposal, RefactorType
    prop = RefactorProposal(RefactorType.SPLIT_FUNCTIONS, 'f.py', {'a.py': 'x'}, 'd', [])
    rh.pending_proposals[_User.id] = prop

    upd = _Upd()
    upd.callback_query.data = 'refactor_action:cancel'
    await rh.handle_proposal_callback(upd, _Ctx())
    assert _User.id not in rh.pending_proposals

