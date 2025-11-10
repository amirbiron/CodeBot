import types
import pytest

import conversation_handlers as ch


class _Msg:
    def __init__(self):
        self.called = False
    async def reply_text(self, *a, **k):
        self.called = True


class _Query:
    def __init__(self):
        self.message = _Msg()


@pytest.mark.asyncio
async def test_main_menu_callback(monkeypatch):
    # Neutralize TelegramUtils.safe_edit_message_text
    async def _no_edit(*a, **k):
        return None
    monkeypatch.setattr(ch, 'TelegramUtils', types.SimpleNamespace(safe_edit_message_text=_no_edit), raising=False)
    monkeypatch.setattr(ch, '_safe_answer', lambda *a, **k: None, raising=False)

    q = _Query()
    upd = types.SimpleNamespace(callback_query=q, effective_user=types.SimpleNamespace(id=1))
    ctx = types.SimpleNamespace(user_data={})

    state = await ch.main_menu_callback(upd, ctx)
    assert q.message.called is True
    assert state == ch.ConversationHandler.END
