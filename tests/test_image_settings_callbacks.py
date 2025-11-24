import pytest
from types import SimpleNamespace
from telegram.ext import ApplicationHandlerStop


@pytest.mark.asyncio
async def test_image_settings_callbacks_and_persist(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    # Capture calls to safe_edit_message_reply_markup
    calls = {"kb": [], "note_prompt": [], "note_saved": [], "bot_edits": []}
    async def _safe_edit_reply_markup(query, reply_markup=None):
        calls["kb"].append(reply_markup)
    monkeypatch.setattr(mod.TelegramUtils, 'safe_edit_message_reply_markup', _safe_edit_reply_markup, raising=True)

    # Stub DB persist
    saved = {}
    class _DBStub:
        def save_image_prefs(self, user_id, prefs):
            saved['payload'] = (user_id, dict(prefs))
            return True
    monkeypatch.setattr(mod, 'db', _DBStub(), raising=True)

    class _App:
        def add_handler(self, *a, **k):
            pass

    class _Msg:
        def __init__(self):
            self.chat_id = 777
            self.message_id = 555

        async def reply_text(self, *a, **k):
            calls["note_prompt"].append((a, k))

    # Minimal Query stub that supports answer + edit_message_text/caption
    class _Query:
        def __init__(self, data):
            self.data = data
            self.message = _Msg()
        async def answer(self, *a, **k):
            return None
        async def edit_message_text(self, *a, **k):
            return None
        async def edit_message_caption(self, *a, **k):
            return None

    class _Upd:
        def __init__(self, data):
            self.effective_user = SimpleNamespace(id=123)
            self.callback_query = _Query(data)

    class _Bot:
        async def edit_message_reply_markup(self, *a, **k):
            calls["bot_edits"].append((a, k))

    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.application = SimpleNamespace(bot_data={})
            self.bot = _Bot()

    h = H(_App())
    ctx = _Ctx()

    # 1) Open settings for a short filename (no tokenization needed)
    await h.handle_callback_query(_Upd('edit_image_settings_demo.py'), ctx)

    # 2) Set theme
    await h.handle_callback_query(_Upd('img_set_theme:gruvbox:demo.py'), ctx)
    assert ctx.user_data.get('img_settings', {}).get('demo.py', {}).get('theme') == 'gruvbox'

    # 3) Set width
    await h.handle_callback_query(_Upd('img_set_width:1400:demo.py'), ctx)
    assert ctx.user_data.get('img_settings', {}).get('demo.py', {}).get('width') == 1400

    # 4) Set font
    await h.handle_callback_query(_Upd('img_set_font:jetbrains:demo.py'), ctx)
    assert ctx.user_data.get('img_settings', {}).get('demo.py', {}).get('font') == 'jetbrains'

    # 5) Save & revert to base keyboard
    await h.handle_callback_query(_Upd('img_settings_done:demo.py'), ctx)
    assert saved.get('payload') and saved['payload'][0] == 123
    assert saved['payload'][1].get('theme') == 'gruvbox'
    assert saved['payload'][1].get('width') == 1400
    assert saved['payload'][1].get('font') == 'jetbrains'

    # Ensure keyboard was updated at least once during flow
    assert calls['kb'], 'expected safe_edit_message_reply_markup to be called'

    # 6) Prompt for note entry
    await h.handle_callback_query(_Upd('img_note_prompt:demo.py'), ctx)
    state = ctx.user_data.get('waiting_for_image_note')
    assert state and state['file_name'] == 'demo.py'
    assert state['chat_id'] == 777
    assert state['message_id'] == 555
    assert calls['note_prompt'], 'expected prompt reply_text to be sent'
    assert 123 in h._image_note_waiters

    # 7) Simulate user text input for note
    class _NoteMsg:
        def __init__(self, text):
            self.text = text

        async def reply_text(self, *a, **k):
            calls['note_saved'].append((a, k))

    note_update = SimpleNamespace(
        message=_NoteMsg("פתק חדש"),
        effective_user=SimpleNamespace(id=123),
    )
    # ודא שהדגל עדיין קיים לפני הקלט
    ctx.user_data['waiting_for_image_note'] = state
    with pytest.raises(ApplicationHandlerStop):
        await h._handle_image_note_input(note_update, ctx)
    assert ctx.user_data.get('img_settings', {}).get('demo.py', {}).get('note') == "פתק חדש"
    assert calls['note_saved'], 'expected confirmation message after saving note'
    assert calls['bot_edits'], 'expected edit_message_reply_markup to refresh keyboard'
    assert 123 not in h._image_note_waiters

    # 8) Clear the note via button
    await h.handle_callback_query(_Upd('img_note_clear:demo.py'), ctx)
    assert not ctx.user_data.get('img_settings', {}).get('demo.py', {}).get('note')

    # 9) Missing message should restore waiting state and stop propagation
    ctx.user_data['waiting_for_image_note'] = {'file_name': 'demo.py'}
    no_msg_update = SimpleNamespace(effective_user=SimpleNamespace(id=123))
    with pytest.raises(ApplicationHandlerStop):
        await h._handle_image_note_input(no_msg_update, ctx)
    assert ctx.user_data.get('waiting_for_image_note', {}).get('file_name') == 'demo.py'
    assert 123 in h._image_note_waiters
