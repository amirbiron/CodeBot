import types
import pytest
import conversation_handlers as ch


@pytest.mark.asyncio
async def test_autocancel_long_collect_on_other_button(monkeypatch):
    # דמה ל-callback כללי שלא שייך לזרימת סניפטים
    q = types.SimpleNamespace(data='noop')
    upd = types.SimpleNamespace(callback_query=q, update_id=456)
    ctx = types.SimpleNamespace(user_data={'sn_long_parts': ['a', 'b']})

    state = await ch.handle_callback_query(upd, ctx)
    assert state == ch.ConversationHandler.END
    assert 'sn_long_parts' not in ctx.user_data
