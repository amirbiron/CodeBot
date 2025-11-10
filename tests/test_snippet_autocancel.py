import types
import pytest
import conversation_handlers as ch


@pytest.mark.asyncio
async def test_autocancel_snippet_on_other_button(monkeypatch):
    # Make the catch-all light: if nothing matches, just end
    # Neutralize heavy handlers possibly called by the catch-all
    # We'll choose a data that doesn't match any branch to avoid side effects
    q = types.SimpleNamespace(data='noop')
    upd = types.SimpleNamespace(callback_query=q, update_id=123)
    ctx = types.SimpleNamespace(user_data={'sn_item': {'title': 't'}})

    # Call
    state = await ch.handle_callback_query(upd, ctx)
    # Should end and clear sn_item (autocancel)
    assert state == ch.ConversationHandler.END
    assert 'sn_item' not in ctx.user_data
