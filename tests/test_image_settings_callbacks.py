import pytest
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_image_settings_callbacks_and_persist(monkeypatch):
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    # Capture calls to safe_edit_message_reply_markup
    calls = {"kb": []}
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

    # Minimal Query stub that supports answer + edit_message_text/caption
    class _Query:
        def __init__(self, data):
            self.data = data
            self.message = SimpleNamespace()  # not used in these paths
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

    class _Ctx:
        def __init__(self):
            self.user_data = {}
            self.application = SimpleNamespace(bot_data={})

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
