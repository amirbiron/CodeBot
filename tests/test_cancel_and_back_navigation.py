import types
import pytest

import conversation_handlers as ch


class _Query:
    def __init__(self):
        self.edits = []
    async def answer(self, *a, **k):
        return None
    async def edit_message_text(self, text=None, reply_markup=None, parse_mode=None):
        self.edits.append((text, reply_markup, parse_mode))


@pytest.mark.asyncio
async def test_submit_flows_cancel_snippet_path(monkeypatch):
    # neutralize safe_answer wrapper
    monkeypatch.setattr(ch, '_safe_answer', lambda *a, **k: None, raising=False)
    q = _Query()
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={'sn_item': {'title': 'x'}})

    state = await ch.submit_flows_cancel(upd, ctx)
    # should clear state and navigate back to snippets menu (edit occurs)
    assert 'sn_item' not in ctx.user_data
    assert q.edits
    assert state == ch.ConversationHandler.END


@pytest.mark.asyncio
async def test_submit_flows_cancel_community_path(monkeypatch):
    monkeypatch.setattr(ch, '_safe_answer', lambda *a, **k: None, raising=False)
    q = _Query()
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={'cl_item': {'title': 'y'}})

    state = await ch.submit_flows_cancel(upd, ctx)
    assert 'cl_item' not in ctx.user_data
    assert q.edits
    assert state == ch.ConversationHandler.END


@pytest.mark.asyncio
async def test_community_hub_callback(monkeypatch):
    monkeypatch.setattr(ch, '_safe_answer', lambda *a, **k: None, raising=False)
    q = _Query()
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={})

    state = await ch.community_hub_callback(upd, ctx)
    assert q.edits
    assert state == ch.ConversationHandler.END
