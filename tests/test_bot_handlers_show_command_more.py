import sys
import types
import pytest


def ensure_telegram_stubs():
    """Install minimal stubs for telegram modules if not installed."""
    if 'telegram' not in sys.modules:
        telegram = types.ModuleType('telegram')
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
        class Update:  # noqa: D401
            pass
        class ReplyKeyboardMarkup:
            def __init__(self, *a, **k):
                pass
        class ReplyKeyboardRemove:
            def __init__(self, *a, **k):
                pass
        telegram.InlineKeyboardButton = InlineKeyboardButton
        telegram.InlineKeyboardMarkup = InlineKeyboardMarkup
        telegram.InputFile = InputFile
        telegram.Update = Update
        telegram.ReplyKeyboardMarkup = ReplyKeyboardMarkup
        telegram.ReplyKeyboardRemove = ReplyKeyboardRemove
        sys.modules['telegram'] = telegram
        # also provide telegram.error submodule used by code
        t_err = types.ModuleType('telegram.error')
        class BadRequest(Exception):
            pass
        class RetryAfter(Exception):
            def __init__(self, retry_after=0):
                super().__init__('RetryAfter')
                self.retry_after = retry_after
        t_err.BadRequest = BadRequest
        t_err.RetryAfter = RetryAfter
        sys.modules['telegram.error'] = t_err
    if 'telegram.constants' not in sys.modules:
        t_consts = types.ModuleType('telegram.constants')
        # Match usage: ParseMode.MARKDOWN and 'HTML' string compare in tests
        t_consts.ParseMode = types.SimpleNamespace(MARKDOWN='MARKDOWN', HTML='HTML')
        sys.modules['telegram.constants'] = t_consts
    if 'telegram.ext' not in sys.modules:
        t_ext = types.ModuleType('telegram.ext')
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
        t_ext.CallbackQueryHandler = CallbackQueryHandler
        t_ext.CommandHandler = CommandHandler
        t_ext.ContextTypes = ContextTypes
        t_ext.ApplicationHandlerStop = ApplicationHandlerStop
        sys.modules['telegram.ext'] = t_ext


def ensure_conversation_handlers_stub():
    """Provide a lightweight stub for conversation_handlers.MAIN_KEYBOARD to avoid heavy imports."""
    if 'conversation_handlers' not in sys.modules:
        ch = types.ModuleType('conversation_handlers')
        ch.MAIN_KEYBOARD = [["A", "B"], ["C", "D"]]
        sys.modules['conversation_handlers'] = ch


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
    async def reply_document(self, *a, **k):
        self.sent.append((a, k))


class _User:
    id = 777


class _Upd:
    effective_user = _User()
    message = _Msg()


class _Ctx:
    def __init__(self):
        self.args = []
        self.user_data = {}
        self.bot = types.SimpleNamespace()


@pytest.mark.asyncio
async def test_show_command_no_args_shows_usage(monkeypatch):
    monkeypatch.setenv('DISABLE_ACTIVITY_REPORTER', '1')
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    ensure_telegram_stubs()
    ensure_conversation_handlers_stub()
    # stub db before import
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_latest_version(self, user_id, file_name):
            return None
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    app = _App()
    h = H(app)

    upd = _Upd()
    msg = upd.message

    ctx = _Ctx()
    ctx.args = []

    await h.show_command(upd, ctx)

    assert msg.sent, "Expected a reply_text call"
    args, kwargs = msg.sent[-1]
    text = args[0] if args else kwargs.get('text', '')
    assert 'אנא ציין' in text


@pytest.mark.asyncio
async def test_show_command_file_not_found(monkeypatch):
    monkeypatch.setenv('DISABLE_ACTIVITY_REPORTER', '1')
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    ensure_telegram_stubs()
    ensure_conversation_handlers_stub()
    # stub db before import
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_latest_version(self, user_id, file_name):
            return None
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)
    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    h = H(_App())
    upd = _Upd(); ctx = _Ctx()
    ctx.args = ['missing.py']

    await h.show_command(upd, ctx)

    args, kwargs = upd.message.sent[-1]
    text = args[0] if args else kwargs.get('text', '')
    assert 'לא נמצא' in text
    assert 'missing.py' in text


@pytest.mark.asyncio
async def test_show_command_renders_html_and_escapes_code_and_buttons_id(monkeypatch):
    monkeypatch.setenv('DISABLE_ACTIVITY_REPORTER', '1')
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    ensure_telegram_stubs()
    ensure_conversation_handlers_stub()
    # stub db and code service before import
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_latest_version(self, uid, name):
            return {
                '_id': '507f1f77bcf86cd799439011',
                'file_name': name,
                'code': "print('<b>x</b>')",
                'programming_language': 'python',
                'updated_at': None,
            }
        def is_favorite(self, uid, name):
            return False
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)
    svc = __import__('services.code_service', fromlist=['code_service'])
    monkeypatch.setattr(svc, 'highlight_code', lambda c, l: c, raising=True)

    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    h = H(_App())
    upd = _Upd(); ctx = _Ctx()
    ctx.args = ['readme.md']

    await h.show_command(upd, ctx)

    args, kwargs = upd.message.sent[-1]
    text = args[0] if args else kwargs.get('text', '')
    pm = kwargs.get('parse_mode')
    assert isinstance(text, str)
    assert pm == 'HTML'
    # basic structure
    assert '<b>File:</b>' in text
    assert '<b>Language:</b>' in text
    assert '<pre><code>' in text and '</code></pre>' in text
    assert '<b>x</b>' not in text  # escaped
    assert '&lt;b&gt;x&lt;/b&gt;' in text
    # buttons
    rm = kwargs.get('reply_markup')
    assert rm is not None
    buttons = getattr(rm, 'inline_keyboard', [])
    # telegram InlineKeyboardMarkup.inline_keyboard יכול להיות list או tuple
    assert buttons and isinstance(buttons, (list, tuple))
    fav_btn = buttons[-1][0]
    assert getattr(fav_btn, 'text', '').startswith('⭐')
    assert getattr(fav_btn, 'callback_data', '').startswith('fav_toggle_id:')


@pytest.mark.asyncio
async def test_show_command_favorite_token_fallback_and_mapping(monkeypatch):
    monkeypatch.setenv('DISABLE_ACTIVITY_REPORTER', '1')
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    ensure_telegram_stubs()
    ensure_conversation_handlers_stub()
    # stub db and code service before import
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_latest_version(self, uid, name):
            return {
                '_id': 'x'*120,  # force token fallback (too long for callback data)
                'file_name': name,
                'code': 'print(1)',
                'programming_language': 'python',
                'updated_at': None,
            }
        def is_favorite(self, uid, name):
            return False
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)
    svc = __import__('services.code_service', fromlist=['code_service'])
    monkeypatch.setattr(svc, 'highlight_code', lambda c, l: c, raising=True)

    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    h = H(_App())
    upd = _Upd(); ctx = _Ctx()
    ctx.args = ['longid.py']

    await h.show_command(upd, ctx)

    args, kwargs = upd.message.sent[-1]
    rm = kwargs.get('reply_markup')
    buttons = getattr(rm, 'inline_keyboard', [])
    fav_btn = buttons[-1][0]
    cb = getattr(fav_btn, 'callback_data', '')
    assert cb.startswith('fav_toggle_tok:')
    tok = cb.split(':', 1)[1]
    # mapping must exist under the same short token
    assert ctx.user_data.get('fav_tokens', {}).get(tok) == 'longid.py'


@pytest.mark.asyncio
async def test_show_command_favorite_label_when_already_favorited(monkeypatch):
    monkeypatch.setenv('DISABLE_ACTIVITY_REPORTER', '1')
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    ensure_telegram_stubs()
    ensure_conversation_handlers_stub()
    # stub db before import
    db_mod = __import__('database', fromlist=['db'])
    class _DB:
        def get_latest_version(self, uid, name):
            return {
                '_id': '507f1f77bcf86cd799439011',
                'file_name': name,
                'code': 'x',
                'programming_language': 'text',
                'updated_at': None,
            }
        def is_favorite(self, uid, name):
            return True
    monkeypatch.setattr(db_mod, 'db', _DB(), raising=True)
    svc = __import__('services.code_service', fromlist=['code_service'])
    monkeypatch.setattr(svc, 'highlight_code', lambda c, l: c, raising=True)

    sys.modules.pop('bot_handlers', None)
    mod = __import__('bot_handlers')
    H = getattr(mod, 'AdvancedBotHandlers')

    h = H(_App())
    upd = _Upd(); ctx = _Ctx()
    ctx.args = ['fav.txt']

    await h.show_command(upd, ctx)

    args, kwargs = upd.message.sent[-1]
    rm = kwargs.get('reply_markup')
    buttons = getattr(rm, 'inline_keyboard', [])
    fav_btn = buttons[-1][0]
    assert getattr(fav_btn, 'text', '').startswith('💔')
