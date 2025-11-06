# tests/_telegram_stubs.py
# Stubs for python-telegram-bot to enable fast, isolated tests without the library installed.
import types
import sys

# --- telegram module stub ---
telegram = types.ModuleType('telegram')

class InlineKeyboardButton:
    def __init__(self, text, callback_data=None, url=None):
        self.text = text
        self.callback_data = callback_data
        self.url = url

class InlineKeyboardMarkup:
    def __init__(self, inline_keyboard):
        # Telegram allows list or tuple
        self.inline_keyboard = inline_keyboard

class InputFile:
    def __init__(self, obj, filename=None):
        self.obj = obj
        self.filename = filename

class ReplyKeyboardMarkup:
    def __init__(self, *a, **k):
        pass

class ReplyKeyboardRemove:
    def __init__(self, *a, **k):
        pass

# Optional minimal types often referenced in tests as a spec
class Update:  # pragma: no cover - shape only
    pass

class BotCommand:
    def __init__(self, command: str, description: str):
        self.command = command
        self.description = description

class BotCommandScopeChat:
    def __init__(self, chat_id: int):
        self.chat_id = chat_id

class InlineQueryResultArticle:
    def __init__(self, id: str, title: str, input_message_content=None, reply_markup=None, description=None, **kwargs):
        self.id = id
        self.title = title
        self.input_message_content = input_message_content
        self.reply_markup = reply_markup
        self.description = description
        self.kwargs = kwargs

class InputTextMessageContent:
    def __init__(self, message_text: str, parse_mode=None, **kwargs):
        self.message_text = message_text
        self.parse_mode = parse_mode
        self.kwargs = kwargs

telegram.InlineKeyboardButton = InlineKeyboardButton
telegram.InlineKeyboardMarkup = InlineKeyboardMarkup
telegram.InputFile = InputFile
telegram.ReplyKeyboardMarkup = ReplyKeyboardMarkup
telegram.ReplyKeyboardRemove = ReplyKeyboardRemove
telegram.Update = Update
telegram.BotCommand = BotCommand
telegram.BotCommandScopeChat = BotCommandScopeChat
telegram.InlineQueryResultArticle = InlineQueryResultArticle
telegram.InputTextMessageContent = InputTextMessageContent
sys.modules['telegram'] = telegram

# --- telegram.constants module stub ---
tc = types.ModuleType('telegram.constants')
tc.ParseMode = types.SimpleNamespace(MARKDOWN='MARKDOWN', HTML='HTML')
sys.modules['telegram.constants'] = tc

# --- telegram.ext module stub ---
te = types.ModuleType('telegram.ext')

class CallbackQueryHandler:
    def __init__(self, callback=None, pattern=None, *args, **kwargs):
        # PTB v20+: first arg is the callback
        self.callback = callback or kwargs.get('callback')
        self.pattern = pattern or kwargs.get('pattern')

class CommandHandler:
    def __init__(self, command=None, callback=None, *args, **kwargs):
        # Accept both (command, callback) and (callback) shapes
        if callback is None and callable(command):
            self.callback = command
            self.commands = tuple()
            self.command = None
            return

        self.callback = callback or kwargs.get('callback')
        cmds = command if command is not None else kwargs.get('command')
        if cmds is None:
            commands_tuple = tuple()
        elif isinstance(cmds, str):
            commands_tuple = (cmds,)
        else:
            try:
                commands_tuple = tuple(cmds)
            except TypeError:
                commands_tuple = (cmds,)
        filtered = tuple(c for c in commands_tuple if c)
        self.commands = filtered
        self.command = filtered[0] if filtered else None

class MessageHandler:
    def __init__(self, filters, callback, *args, **kwargs):
        # PTB v20+: (filters, callback)
        self.filters = filters
        self.callback = callback

class InlineQueryHandler:
    def __init__(self, callback=None, *args, **kwargs):
        self.callback = callback or kwargs.get('callback')

class PicklePersistence:
    def __init__(self, *a, **k):
        pass

class ContextTypes:
    DEFAULT_TYPE = object

class Defaults:
    def __init__(self, *a, **k):
        pass

class Application:  # placeholder to satisfy imports; tests monkeypatch runtime behavior
    pass

class TypeHandler:
    def __init__(self, t, callback):
        self.t = t
        self.callback = callback

class ApplicationHandlerStop(Exception):
    pass

class ConversationHandler:
    # Sentinel used across code/tests to signal conversation end
    END = object()

    def __init__(self, *args, **kwargs):
        # Keep minimal shape; real behavior is monkeypatched in tests where needed
        self.args = args
        self.kwargs = kwargs

# Minimal filters namespace used by code; values aren't exercised in tests
class _FiltersNS:
    class _Filter:
        def __init__(self, kind: str, value=None):
            self.kind = kind
            self.value = value
        def __and__(self, other):
            return _FiltersNS._Filter('AND', (self, other))
        def __or__(self, other):
            return _FiltersNS._Filter('OR', (self, other))
        def __invert__(self):
            return _FiltersNS._Filter('NOT', self)

    class _DocumentNS:
        ALL = None  # initialized after _Filter is defined

    # Common filters
    TEXT = _Filter('TEXT')
    COMMAND = _Filter('COMMAND')
    ALL = _Filter('ALL')

    @staticmethod
    def Regex(pattern):
        f = _FiltersNS._Filter('REGEX', pattern)
        f.pattern = pattern
        return f

    Document = _DocumentNS()
    Document.ALL = _Filter('DOCUMENT_ALL')

filters = _FiltersNS()

te.CallbackQueryHandler = CallbackQueryHandler
te.CommandHandler = CommandHandler
te.MessageHandler = MessageHandler
te.InlineQueryHandler = InlineQueryHandler
te.PicklePersistence = PicklePersistence
te.ContextTypes = ContextTypes
te.Defaults = Defaults
te.Application = Application
te.TypeHandler = TypeHandler
te.ApplicationHandlerStop = ApplicationHandlerStop
te.ConversationHandler = ConversationHandler
te.filters = filters
sys.modules['telegram.ext'] = te

# Provide internal submodule for compatibility with imports like
# `from telegram.ext._application import ApplicationHandlerStop`
te_app = types.ModuleType('telegram.ext._application')
te_app.ApplicationHandlerStop = ApplicationHandlerStop
sys.modules['telegram.ext._application'] = te_app

# --- telegram.error module stub ---
terr = types.ModuleType('telegram.error')

class BadRequest(Exception):
    pass

class RetryAfter(Exception):
    def __init__(self, retry_after=0):
        super().__init__('RetryAfter')
        self.retry_after = retry_after

class Forbidden(Exception):
    pass

terr.BadRequest = BadRequest
terr.RetryAfter = RetryAfter
terr.Forbidden = Forbidden
sys.modules['telegram.error'] = terr

# Also expose telegram.error under the root telegram module for
# call sites using `import telegram; telegram.error.BadRequest`
telegram.error = terr
