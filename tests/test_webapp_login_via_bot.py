import os
import sys
import types
import asyncio


def _install_telegram_stubs():
    """Install minimal telegram stubs so importing conversation_handlers won't fail."""
    # telegram base module
    tg = types.ModuleType('telegram')

    class _ReplyKeyboardMarkup:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    class _ReplyKeyboardRemove:
        pass

    class _InlineKeyboardButton:
        def __init__(self, text, url=None, callback_data=None):
            self.text = text
            self.url = url
            self.callback_data = callback_data

    class _InlineKeyboardMarkup:
        def __init__(self, rows):
            self.rows = rows

    tg.ReplyKeyboardMarkup = _ReplyKeyboardMarkup
    tg.ReplyKeyboardRemove = _ReplyKeyboardRemove
    tg.InlineKeyboardButton = _InlineKeyboardButton
    tg.InlineKeyboardMarkup = _InlineKeyboardMarkup
    tg.Update = object
    sys.modules['telegram'] = tg

    # telegram.constants
    consts = types.ModuleType('telegram.constants')
    class _PM:
        HTML = 'HTML'
    consts.ParseMode = _PM
    sys.modules['telegram.constants'] = consts

    # telegram.ext
    ext = types.ModuleType('telegram.ext')
    class _ContextTypes:
        DEFAULT_TYPE = object
    class _ConversationHandler:
        END = -1
    class _CommandHandler:
        pass
    class _MessageHandler:
        pass
    class _CallbackQueryHandler:
        pass
    class _filters:
        TEXT = 1
        COMMAND = 2
    ext.ContextTypes = _ContextTypes
    ext.ConversationHandler = _ConversationHandler
    ext.CommandHandler = _CommandHandler
    ext.MessageHandler = _MessageHandler
    ext.CallbackQueryHandler = _CallbackQueryHandler
    ext.filters = _filters
    sys.modules['telegram.ext'] = ext


def _prepare_env():
    os.environ.setdefault('BOT_TOKEN', 'test-token')
    os.environ.setdefault('MONGODB_URL', 'mongodb://localhost:27017')
    os.environ.setdefault('DISABLE_DB', 'true')
    os.environ.setdefault('WEBAPP_URL', 'https://example.com')


class _Msg:
    def __init__(self):
        self.calls = []
    async def reply_text(self, text, **kwargs):
        self.calls.append((text, kwargs))
        return None


class _Update:
    def __init__(self, user_id: int = 123, username: str = 'user', first_name: str = 'User'):
        self.message = _Msg()
        self.effective_user = types.SimpleNamespace(id=user_id, username=username, first_name=first_name)


class _Context:
    def __init__(self, args=None):
        self.args = args or []
        self.user_data = {}


def test_start_command_webapp_login_sends_personal_link(monkeypatch):
    _install_telegram_stubs()
    _prepare_env()

    # Import after stubs and env are ready
    import conversation_handlers as ch

    # Avoid external writes
    monkeypatch.setattr(ch, 'reporter', types.SimpleNamespace(report_activity=lambda uid: None), raising=True)
    monkeypatch.setattr(ch.user_stats, 'log_user', lambda *a, **k: None, raising=True)

    # Make database token collection capture insertions
    import database as dbmod
    insert_calls = []

    class _TokColl:
        def insert_one(self, doc):
            insert_calls.append(doc)
            return types.SimpleNamespace(inserted_id='x')

    # Ensure no-op DB exists and expose webapp_tokens
    if getattr(dbmod.db, 'db', None) is None:
        dbmod.db.db = types.SimpleNamespace()
    dbmod.db.db.webapp_tokens = _TokColl()

    update = _Update(user_id=777, username='alice', first_name='Alice')
    context = _Context(args=['webapp_login'])

    # Run
    result = asyncio.get_event_loop().run_until_complete(ch.start_command(update, context))

    # Assertions
    assert result == ch.ConversationHandler.END
    assert update.message.calls, 'Expected a reply with login link'
    text, kwargs = update.message.calls[0]
    assert 'קישור התחברות אישי' in text
    # Validate reply markup and URL
    rm = kwargs.get('reply_markup')
    assert rm and getattr(rm, 'rows', None), 'Expected inline keyboard rows'
    btn = rm.rows[0][0]
    assert '/auth/token?token=' in (btn.url or '')
    assert f'user_id={update.effective_user.id}' in btn.url
    # Token doc inserted
    assert insert_calls and insert_calls[0]['user_id'] == 777 and len(insert_calls[0]['token']) == 32


def test_start_command_webapp_login_handles_insert_exception(monkeypatch):
    _install_telegram_stubs()
    _prepare_env()

    import conversation_handlers as ch
    monkeypatch.setattr(ch, 'reporter', types.SimpleNamespace(report_activity=lambda uid: None), raising=True)
    monkeypatch.setattr(ch.user_stats, 'log_user', lambda *a, **k: None, raising=True)

    import database as dbmod

    class _TokCollFail:
        def insert_one(self, doc):
            raise RuntimeError('boom')

    if getattr(dbmod.db, 'db', None) is None:
        dbmod.db.db = types.SimpleNamespace()
    dbmod.db.db.webapp_tokens = _TokCollFail()

    update = _Update(user_id=42, username='bob', first_name='Bob')
    context = _Context(args=['webapp_login'])

    # Should not raise; still sends message
    result = asyncio.get_event_loop().run_until_complete(ch.start_command(update, context))

    assert result == ch.ConversationHandler.END
    assert update.message.calls, 'Expected a reply even if DB insert failed'
    text, kwargs = update.message.calls[0]
    assert 'קישור התחברות אישי' in text
    rm = kwargs.get('reply_markup')
    assert rm and getattr(rm, 'rows', None)

