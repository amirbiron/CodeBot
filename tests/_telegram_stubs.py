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

# Optional minimal type often referenced in tests as a spec
class Update:  # pragma: no cover - shape only
    pass

telegram.InlineKeyboardButton = InlineKeyboardButton
telegram.InlineKeyboardMarkup = InlineKeyboardMarkup
telegram.InputFile = InputFile
telegram.ReplyKeyboardMarkup = ReplyKeyboardMarkup
telegram.ReplyKeyboardRemove = ReplyKeyboardRemove
telegram.Update = Update
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

class Application:  # placeholder to satisfy imports; tests monkeypatch runtime behavior
    pass

class ApplicationHandlerStop(Exception):
    pass

# Minimal filters namespace used by code; values aren't exercised in tests
filters = types.SimpleNamespace(
    TEXT=object(),
    COMMAND=object(),
)

te.CallbackQueryHandler = CallbackQueryHandler
te.CommandHandler = CommandHandler
te.MessageHandler = MessageHandler
te.InlineQueryHandler = InlineQueryHandler
te.PicklePersistence = PicklePersistence
te.ContextTypes = ContextTypes
te.Application = Application
te.ApplicationHandlerStop = ApplicationHandlerStop
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

terr.BadRequest = BadRequest
terr.RetryAfter = RetryAfter
sys.modules['telegram.error'] = terr
