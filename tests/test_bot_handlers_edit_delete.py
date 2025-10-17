import types
import pytest


class _App:
    def __init__(self):
        self.handlers = []
    def add_handler(self, *a, **k):
        self.handlers.append((a, k))


class _Msg:
    def __init__(self):
        self.sent = []
    async def reply_text(self, *a, **k):
        self.sent.append((a, k))


class _User:
    id = 321


class _Upd:
    def __init__(self):
        self.effective_user = _User()
        self.message = _Msg()


class _Ctx:
    def __init__(self):
        self.args = []
        self.user_data = {}


def _install_stubs(monkeypatch):
    import sys, types as _t
    # telegram stubs
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
        class ReplyKeyboardMarkup:
            def __init__(self, *a, **k):
                pass
        tg.InlineKeyboardButton = InlineKeyboardButton
        tg.InlineKeyboardMarkup = InlineKeyboardMarkup
        tg.InputFile = InputFile
        tg.ReplyKeyboardMarkup = ReplyKeyboardMarkup
        sys.modules['telegram'] = tg
    if 'telegram.constants' not in sys.modules:
        consts = _t.ModuleType('telegram.constants')
        consts.ParseMode = types.SimpleNamespace(MARKDOWN='MARKDOWN', HTML='HTML')
        sys.modules['telegram.constants'] = consts
    if 'telegram.ext' not in sys.modules:
        te = _t.ModuleType('telegram.ext')
        class CallbackQueryHandler:
            def __init__(self, *a, **k):
                pass
        class CommandHandler:
            def __init__(self, *a, **k):
                pass
        class ContextTypes:
            DEFAULT_TYPE = object
        class ApplicationHandlerStop(Exception):
            pass
        te.CallbackQueryHandler = CallbackQueryHandler
        te.CommandHandler = CommandHandler
        te.ContextTypes = ContextTypes
        te.ApplicationHandlerStop = ApplicationHandlerStop
        sys.modules['telegram.ext'] = te
    # conversation_handlers stub
    if 'conversation_handlers' not in sys.modules:
        ch = _t.ModuleType('conversation_handlers')
        ch.MAIN_KEYBOARD = [["A", "B"], ["C", "D"]]
        sys.modules['conversation_handlers'] = ch


@pytest.mark.asyncio
async def test_edit_command_prompts_when_no_args_and_when_not_found(monkeypatch):
    _install_stubs(monkeypatch)
    # env for config
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')

    # stub db
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_latest_version(self, uid, fn):
            return None
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    # fresh import
    import sys
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    h = H(_App())
    upd = _Upd(); ctx = _Ctx()

    # no args
    ctx.args = []
    await h.edit_command(upd, ctx)
    args, kwargs = upd.message.sent[-1]
    text = args[0] if args else kwargs.get('text', '')
    assert 'אנא ציין שם קובץ' in text

    # not found
    upd = _Upd(); ctx = _Ctx()
    ctx.args = ['missing.py']
    await h.edit_command(upd, ctx)
    args, kwargs = upd.message.sent[-1]
    text = args[0] if args else kwargs.get('text', '')
    assert 'לא נמצא' in text and 'missing.py' in text


@pytest.mark.asyncio
async def test_edit_command_sets_editing_context_and_shows_current_code(monkeypatch):
    _install_stubs(monkeypatch)
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')

    # stub db returns file
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_latest_version(self, uid, fn):
            return {'_id': '1', 'file_name': fn, 'code': 'print(1)', 'programming_language': 'python'}
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    import sys
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    h = H(_App())
    upd = _Upd(); ctx = _Ctx()
    ctx.args = ['file.py']

    await h.edit_command(upd, ctx)

    # context populated
    assert ctx.user_data.get('editing_file', {}).get('file_name') == 'file.py'
    # response contains code block and language
    args, kwargs = upd.message.sent[-1]
    text = args[0] if args else kwargs.get('text', '')
    assert 'print(1)' in text and 'python' in text


@pytest.mark.asyncio
async def test_delete_command_prompts_and_confirmation_markup(monkeypatch):
    _install_stubs(monkeypatch)
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')

    # stub db
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_latest_version(self, uid, fn):
            # return doc for valid.py only
            if fn == 'valid.py':
                return {'_id': '1', 'file_name': fn}
            return None
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)

    import sys
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    h = H(_App())

    # no args
    upd = _Upd(); ctx = _Ctx(); ctx.args = []
    await h.delete_command(upd, ctx)
    args, kwargs = upd.message.sent[-1]
    text = args[0] if args else kwargs.get('text', '')
    assert 'אנא ציין שם קובץ' in text

    # not found
    upd = _Upd(); ctx = _Ctx(); ctx.args = ['missing.py']
    await h.delete_command(upd, ctx)
    args, kwargs = upd.message.sent[-1]
    text = args[0] if args else kwargs.get('text', '')
    assert 'לא נמצא' in text and 'missing.py' in text

    # confirmation with markup
    upd = _Upd(); ctx = _Ctx(); ctx.args = ['valid.py']
    await h.delete_command(upd, ctx)
    args, kwargs = upd.message.sent[-1]
    text = args[0] if args else kwargs.get('text', '')
    rm = kwargs.get('reply_markup')
    assert 'אישור מחיקה' in text
    # InlineKeyboardMarkup has inline_keyboard attribute
    buttons = getattr(rm, 'inline_keyboard', [])
    assert buttons and buttons[0][0].callback_data.startswith('confirm_delete_')
