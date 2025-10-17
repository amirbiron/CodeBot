import types
import pytest


class _Msg:
    def __init__(self):
        self.texts = []
        self.docs = []
    async def edit_text(self, text, **kwargs):
        self.texts.append(text)
        return self
    async def reply_document(self, document, filename=None, caption=None):
        # Capture content for assertions
        self.docs.append((document, filename, caption))
        return self


class _Query:
    def __init__(self):
        self.message = _Msg()
        self.data = ""
        self.from_user = types.SimpleNamespace(id=5)
    async def edit_message_text(self, text, **kwargs):
        self.message.texts.append(text)
        return self.message
    async def answer(self, *args, **kwargs):
        return None


class _Update:
    def __init__(self):
        self.callback_query = _Query()
        self.effective_user = types.SimpleNamespace(id=5)


class _Context:
    def __init__(self):
        self.user_data = {}
        self.bot_data = {}


def _install_stubs(monkeypatch):
    import sys, types as _t
    # telegram base stubs
    if 'telegram' not in sys.modules:
        tg = _t.ModuleType('telegram')
        class InlineKeyboardButton:
            def __init__(self, text, callback_data=None):
                self.text = text
                self.callback_data = callback_data
        class InlineKeyboardMarkup:
            def __init__(self, inline_keyboard):
                self.inline_keyboard = inline_keyboard
        class InputFile:
            def __init__(self, obj, filename=None):
                self.obj = obj
                self.filename = filename
        tg.InlineKeyboardButton = InlineKeyboardButton
        tg.InlineKeyboardMarkup = InlineKeyboardMarkup
        tg.InputFile = InputFile
        sys.modules['telegram'] = tg
    if 'telegram.constants' not in sys.modules:
        consts = _t.ModuleType('telegram.constants')
        consts.ParseMode = types.SimpleNamespace(MARKDOWN='MARKDOWN', HTML='HTML')
        sys.modules['telegram.constants'] = consts


@pytest.mark.asyncio
async def test_confirm_delete_calls_db_and_edits_message(monkeypatch):
    _install_stubs(monkeypatch)

    # env for config
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')

    # stub db.delete_file
    called = {"args": None}
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def delete_file(self, uid, name):
            called["args"] = (uid, name)
            return True
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    import sys
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    # Build handler and run callback
    h = H(types.SimpleNamespace(add_handler=lambda *a, **k: None))
    upd = _Update(); ctx = _Context()

    upd.callback_query.data = "confirm_delete_test.py"
    await h.handle_callback_query(upd, ctx)

    # db called with correct args and message edited to success
    assert called["args"] == (5, "test.py")
    assert any("נמחק בהצלחה" in t for t in upd.callback_query.message.texts)


@pytest.mark.asyncio
async def test_fav_toggle_id_updates_label_and_message(monkeypatch):
    _install_stubs(monkeypatch)
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')

    # stub db
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def __init__(self):
            self.docs = {"42": {"file_name": "a.py", "programming_language": "python", "description": ""}}
            self.fav = False
        def get_file_by_id(self, fid):
            return self.docs.get(fid)
        def toggle_favorite(self, uid, name):
            self.fav = not self.fav
            return self.fav
        def get_latest_version(self, uid, name):
            return {"programming_language": "python", "description": ""}
        def is_favorite(self, uid, name):
            return self.fav
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    # stub telegram classes for building updated keyboard
    import telegram as tg

    import sys
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    h = H(types.SimpleNamespace(add_handler=lambda *a, **k: None))
    upd = _Update(); ctx = _Context()

    upd.callback_query.data = "fav_toggle_id:42"
    await h.handle_callback_query(upd, ctx)

    # Should answer with star/heart and edit message to include details
    assert upd.callback_query.message.texts, "expected edited message content"


@pytest.mark.asyncio
async def test_fav_toggle_token_fallback_uses_context_mapping(monkeypatch):
    _install_stubs(monkeypatch)
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')

    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def __init__(self):
            self.fav = False
        def toggle_favorite(self, uid, name):
            self.fav = not self.fav
            return self.fav
        def get_latest_version(self, uid, name):
            return {"programming_language": "python", "description": ""}
        def is_favorite(self, uid, name):
            return self.fav
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    import sys
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    h = H(types.SimpleNamespace(add_handler=lambda *a, **k: None))
    upd = _Update(); ctx = _Context()

    # prepare mapping
    ctx.user_data['fav_tokens'] = {"tok": "a.py"}
    upd.callback_query.data = "fav_toggle_tok:tok"

    await h.handle_callback_query(upd, ctx)

    # Should have edited text and no alert error
    assert upd.callback_query.message.texts, "expected edited message content"
