import types
import pytest

import conversation_handlers as ch


class _Query:
    def __init__(self, data):
        self.data = data
        self.edits = []
    async def answer(self):
        return None
    async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
        self.edits.append(text)


@pytest.mark.asyncio
async def test_snippet_inline_reject_transitions_to_reason(monkeypatch):
    monkeypatch.setenv('ADMIN_USER_IDS', '1')
    monkeypatch.setattr(ch, '_safe_edit_message_text', lambda *a, **k: None, raising=False)
    upd = types.SimpleNamespace(callback_query=_Query('snippet_reject:RID'), effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={})
    state = await ch.snippet_inline_approve(upd, ctx)
    assert state == ch.SN_REJECT_REASON
    assert ctx.user_data.get('sn_reject_id') == 'RID'


@pytest.mark.asyncio
async def test_snippet_inline_approve_non_admin(monkeypatch):
    # no ADMIN_USER_IDS set → not admin by default
    upd = types.SimpleNamespace(callback_query=_Query('snippet_approve:RID'), effective_user=types.SimpleNamespace(id=999))
    ctx = types.SimpleNamespace()
    state = await ch.snippet_inline_approve(upd, ctx)
    assert state == ch.ConversationHandler.END
    assert upd.callback_query.edits == []
