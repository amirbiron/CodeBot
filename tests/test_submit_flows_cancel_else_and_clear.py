import types
import pytest

import conversation_handlers as ch


class _Capture:
    def __init__(self):
        self.calls = []
    async def edit(self, query, text, reply_markup=None, parse_mode=None):
        self.calls.append((text, reply_markup, parse_mode))


@pytest.mark.asyncio
async def test_submit_flows_cancel_else_path(monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(ch, '_safe_edit_message_text', cap.edit, raising=True)
    monkeypatch.setattr(ch, '_safe_answer', lambda *a, **k: None, raising=False)

    q = types.SimpleNamespace()
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={})

    state = await ch.submit_flows_cancel(upd, ctx)
    # Should route to community_hub_callback and edit once
    assert cap.calls
    text, markup, _ = cap.calls[-1]
    assert 'בחר/י קטגוריה' in (text or '')
    # back button in that screen is to main_menu
    btn = markup.inline_keyboard[-1][0]
    assert btn.callback_data == 'main_menu'
    assert state == ch.ConversationHandler.END


@pytest.mark.asyncio
async def test_submit_flows_cancel_clears_long_collect_and_goes_back(monkeypatch):
    cap = _Capture()
    monkeypatch.setattr(ch, '_safe_edit_message_text', cap.edit, raising=True)
    monkeypatch.setattr(ch, '_safe_answer', lambda *a, **k: None, raising=False)

    q = types.SimpleNamespace()
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={'sn_long_parts': ['a', 'b']})

    state = await ch.submit_flows_cancel(upd, ctx)
    assert 'sn_long_parts' not in ctx.user_data
    assert cap.calls
    # In snippet path it should route to snippets_menu
    text, markup, _ = cap.calls[-1]
    # back button points to community_hub from that submenu
    btn = markup.inline_keyboard[-1][0]
    assert btn.callback_data == 'community_hub'
    assert state == ch.ConversationHandler.END
