import types
import pytest
import importlib


@pytest.mark.asyncio
async def test_start_and_help_texts_include_highlights(monkeypatch):
    import main as mod
    import config as cfg
    importlib.reload(cfg)
    importlib.reload(mod)

    # Minimal app stub to capture command handlers
    class _App:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}
        def add_handler(self, handler, group=None):
            self.handlers.append(handler)
        def add_error_handler(self, *a, **k):
            pass

    app = _App()
    # call setup_handlers to register commands
    mod.setup_handlers(app, mod.db)

    # capture callbacks
    start_cb = None
    help_cb = None
    from telegram.ext import CommandHandler
    for h in app.handlers:
        if isinstance(h, CommandHandler):
            if getattr(h, 'command', None) == ['start']:
                start_cb = h.callback
            if getattr(h, 'command', None) == ['help']:
                help_cb = h.callback

    assert start_cb is not None and help_cb is not None

    sent = {}
    class _Msg:
        async def reply_text(self, text, *a, **k):
            sent.setdefault('texts', []).append(text)
    class _User: id = 111; username = 'u'
    class _Upd:
        effective_user = _User()
        effective_message = _Msg()
        message = effective_message
    class _Ctx:
        args = []
        application = types.SimpleNamespace(bot_data={})

    # call /start
    await start_cb(_Upd(), _Ctx())
    assert any('ברוך הבא לבוט' in t for t in sent.get('texts', []))

    # call /help
    await help_cb(_Upd(), _Ctx())
    all_text = '\n'.join(sent.get('texts', []))
    assert '/remind' in all_text
    assert '/image' in all_text
