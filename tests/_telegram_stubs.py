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

telegram.InlineKeyboardButton = InlineKeyboardButton
telegram.InlineKeyboardMarkup = InlineKeyboardMarkup
telegram.InputFile = InputFile
telegram.ReplyKeyboardMarkup = ReplyKeyboardMarkup
telegram.ReplyKeyboardRemove = ReplyKeyboardRemove
telegram.Update = Update
telegram.BotCommand = BotCommand
telegram.BotCommandScopeChat = BotCommandScopeChat
sys.modules['telegram'] = telegram

# --- telegram.constants module stub ---
tc = types.ModuleType('telegram.constants')
tc.ParseMode = types.SimpleNamespace(MARKDOWN='MARKDOWN', HTML='HTML')
sys.modules['telegram.constants'] = tc

# --- telegram.ext module stub ---
te = types.ModuleType('telegram.ext')

class CallbackQueryHandler:
    def __init__(self, *a, **k):
        pass

class CommandHandler:
    def __init__(self, *a, **k):
        pass

class MessageHandler:
    def __init__(self, *a, **k):
        pass

class InlineQueryHandler:
    def __init__(self, *a, **k):
        pass

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
    class _All:
        def __and__(self, other):
            return self
        def __invert__(self):
            return self

    class _Regex:
        def __init__(self, pattern):
            self.pattern = pattern

    class _DocumentNS:
        ALL = object()

    TEXT = object()
    COMMAND = object()
    ALL = _All()

    @staticmethod
    def Regex(pattern):
        return _FiltersNS._Regex(pattern)

    Document = _DocumentNS()

filters = _FiltersNS()

te.CallbackQueryHandler = CallbackQueryHandler
te.CommandHandler = CommandHandler
te.MessageHandler = MessageHandler
te.InlineQueryHandler = InlineQueryHandler
te.PicklePersistence = PicklePersistence
te.ContextTypes = ContextTypes
te.Defaults = Defaults
te.Application = Application
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
