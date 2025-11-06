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
async def test_snippet_inline_approve_path(monkeypatch):
    monkeypatch.setenv('ADMIN_USER_IDS', '1')
    called = {}
    monkeypatch.setattr('services.snippet_library_service.approve_snippet', lambda *a, **k: called.update({'ok': True}) or True, raising=False)
    upd = types.SimpleNamespace(callback_query=_Query('snippet_approve:xyz'), effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace()
    state = await ch.snippet_inline_approve(upd, ctx)
    assert state == ch.ConversationHandler.END
    assert upd.callback_query.edits  # message edited


@pytest.mark.asyncio
async def test_snippet_reject_start_and_collect(monkeypatch):
    monkeypatch.setenv('ADMIN_USER_IDS', '1')
    # start
    q = _Query('snippet_reject:abc')
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={})
    state = await ch.snippet_reject_start(upd, ctx)
    assert state == ch.SN_REJECT_REASON and ctx.user_data.get('sn_reject_id') == 'abc'
    # collect
    called = {}
    monkeypatch.setattr('services.snippet_library_service.reject_snippet', lambda *a, **k: called.update({'ok': True}) or True, raising=False)
    msg = types.SimpleNamespace(text='not relevant', reply_text=lambda *a, **k: None)
    upd2 = types.SimpleNamespace(message=msg, effective_user=types.SimpleNamespace(id=1))
    state2 = await ch.snippet_collect_reject_reason(upd2, ctx)
    assert state2 == ch.ConversationHandler.END and called.get('ok') is True
