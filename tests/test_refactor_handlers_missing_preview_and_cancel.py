import sys
import pytest


@pytest.mark.asyncio
async def test_handle_proposal_callback_cancel_without_pending(monkeypatch):
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
        data = 'refactor_action:cancel'
        message = _Msg()
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
    class _User: id = 222
    class _Upd:
        effective_user = _User()
        callback_query = _Q()
    class _Ctx: pass

    rh = RH(_App())
    await rh.handle_proposal_callback(_Upd(), _Ctx())

