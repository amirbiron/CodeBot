import types
import pytest

import conversation_handlers as ch


class _Msg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, text, **kwargs):
        self.sent.append(text)


@pytest.mark.asyncio
async def test_snippet_reject_reason_failure_branch(monkeypatch):
    # Force reject_snippet to fail so we hit the 'not ok' branch
    class _Svc:
        @staticmethod
        def reject_snippet(*a, **k):
            raise RuntimeError('fail')
    monkeypatch.setitem(ch.__dict__, 'ConversationHandler', ch.ConversationHandler)
    # Patch service import in function scope
    import services.snippet_library_service as svc
    monkeypatch.setattr(svc, 'reject_snippet', lambda *a, **k: False, raising=True)

    upd = types.SimpleNamespace(message=_Msg(), effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={'sn_reject_id': 'abc'})

    state = await ch.snippet_collect_reject_reason(upd, ctx)
    assert any('❌' in s for s in upd.message.sent)
    assert 'sn_reject_id' not in ctx.user_data
    assert state == ch.ConversationHandler.END
