import types
import pytest

import conversation_handlers as ch


class _Bot:
    def __init__(self):
        self.sent = []
    async def send_message(self, chat_id=None, text=None, reply_markup=None):
        self.sent.append((chat_id, text, reply_markup))


@pytest.mark.asyncio
async def test_admin_notification_includes_view_snippet_button(monkeypatch):
    # Stub submit_snippet to succeed with id
    import services.snippet_library_service as svc
    monkeypatch.setattr(svc, 'submit_snippet', lambda **k: {'ok': True, 'id': 'abc123'}, raising=True)
    # Admin IDs
    monkeypatch.setattr(ch, '_get_admin_user_ids', lambda: [111], raising=True)

    # Build update/context with a stub bot and an sn_item ready for language step
    bot = _Bot()
    upd = types.SimpleNamespace(effective_user=types.SimpleNamespace(id=999))
    ctx = types.SimpleNamespace(user_data={'sn_item': {'title': 'T', 'description': 'D', 'code': 'print(1)'}}, bot=bot)

    # Provide language and finalize
    upd_msg = types.SimpleNamespace(text='python')
    upd_with_msg = types.SimpleNamespace(message=upd_msg, effective_user=upd.effective_user)

    state = await ch.snippet_collect_language(upd_with_msg, ctx)
    assert state == ch.ConversationHandler.END
    # Verify admin got a message with a button linking to admin view
    assert bot.sent
    _, _, reply_markup = bot.sent[0]
    # Second row contains the view button according to implementation
    texts = [b.text for row in (reply_markup.inline_keyboard or []) for b in row]
    assert any('👁️ הצג סניפט' in t for t in texts)
