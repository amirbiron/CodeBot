import types
import pytest


class _FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text):
        self.replies.append(text)


class _FakeCallbackQuery:
    def __init__(self):
        self.edits = []

    async def edit_message_text(self, text, reply_markup=None, parse_mode=None):
        self.edits.append((text, reply_markup, parse_mode))


@pytest.mark.asyncio
async def test_maintenance_message_sent_during_warmup_for_message(monkeypatch):
    # ENV הכרחיים
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    monkeypatch.setenv('MAINTENANCE_MODE', 'true')
    monkeypatch.setenv('MAINTENANCE_AUTO_WARMUP_SECS', '10')

    import importlib
    import config as cfg
    importlib.reload(cfg)
    import main as mod
    # ודא שהמודול נטען אחרי ריענון הקונפיג
    importlib.reload(mod)

    class _JobQ:
        def __init__(self):
            self.last = None

        def run_once(self, cb, when=None, name=None):
            self.last = (cb, when, name)
            return None

    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}
            self.job_queue = _JobQ()

        def add_handler(self, handler, group=None):
            self.handlers.append((handler, group))

        def add_error_handler(self, handler, group=None):
            pass

        def remove_handler(self, handler, group=None):
            pass

    class _Builder:
        def token(self, *a, **k):
            return self

        def defaults(self, *a, **k):
            return self

        def persistence(self, *a, **k):
            return self

        def post_init(self, *a, **k):
            return self

        def build(self):
            return _MiniApp()

    class _AppNS:
        def builder(self):
            return _Builder()

    monkeypatch.setattr(mod, 'Application', _AppNS())

    bot = mod.CodeKeeperBot()

    # מצא את maintenance handlers (group -100)
    maintenance_handlers = [h for h, g in bot.application.handlers if g == -100]
    assert maintenance_handlers, 'expected maintenance handlers to be registered'
    # בחר ספציפית את ה-MessageHandler של תחזוקה לפי שם הפונקציה
    maint_msg_handler = None
    for h in maintenance_handlers:
        cb = getattr(h, 'callback', None)
        if getattr(cb, '__name__', '') == 'maintenance_reply':
            maint_msg_handler = h
            break
    assert maint_msg_handler is not None, 'maintenance handler not found'

    update = types.SimpleNamespace(callback_query=None, message=_FakeMessage(), effective_user=types.SimpleNamespace(id=1))
    context = types.SimpleNamespace()

    # בזמן warmup אמורה להישלח הודעת תחזוקה
    await maint_msg_handler.callback(update, context)
    assert update.message.replies, 'expected maintenance reply during warmup'
    assert update.message.replies[-1] == mod.config.MAINTENANCE_MESSAGE


@pytest.mark.asyncio
async def test_maintenance_message_not_sent_after_ttl_elapsed_by_time(monkeypatch):
    # הגדרת זמן מדומה כדי לשלוט על TTL
    import importlib
    import config as cfg
    importlib.reload(cfg)
    import main as mod

    base_time = 1_000.0
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    monkeypatch.setenv('MAINTENANCE_MODE', 'true')
    monkeypatch.setenv('MAINTENANCE_AUTO_WARMUP_SECS', '10')

    # טען מחדש מודול ולאחר מכן תקבע זמן בסיס
    importlib.reload(mod)
    monkeypatch.setattr(mod.time, 'time', lambda: base_time)

    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}

        def add_handler(self, handler, group=None):
            self.handlers.append((handler, group))

        def add_error_handler(self, handler, group=None):
            pass

        def remove_handler(self, handler, group=None):
            pass

    class _Builder:
        def token(self, *a, **k):
            return self

        def defaults(self, *a, **k):
            return self

        def persistence(self, *a, **k):
            return self

        def post_init(self, *a, **k):
            return self

        def build(self):
            return _MiniApp()

    class _AppNS:
        def builder(self):
            return _Builder()

    monkeypatch.setattr(mod, 'Application', _AppNS())

    # בנה את הבוט עם הזמן הבסיסי
    bot = mod.CodeKeeperBot()

    # לאחר היצירה, קפוץ מעבר ל-TTL
    monkeypatch.setattr(mod.time, 'time', lambda: base_time + 20)

    maint_msg_handler = [h for h, g in bot.application.handlers if g == -100][0]

    update = types.SimpleNamespace(callback_query=None, message=_FakeMessage(), effective_user=types.SimpleNamespace(id=2))
    context = types.SimpleNamespace()

    # אחרי פקיעת TTL לא אמורה להישלח הודעה
    await maint_msg_handler.callback(update, context)
    assert update.message.replies == []


@pytest.mark.asyncio
async def test_maintenance_clear_job_disables_message_immediately(monkeypatch):
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    monkeypatch.setenv('MAINTENANCE_MODE', 'true')
    monkeypatch.setenv('MAINTENANCE_AUTO_WARMUP_SECS', '10')

    import importlib
    import config as cfg
    importlib.reload(cfg)
    import main as mod
    importlib.reload(mod)

    class _JobQ:
        def __init__(self):
            self.last = None

        def run_once(self, cb, when=None, name=None):
            self.last = (cb, when, name)
            return None

    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}
            self.job_queue = _JobQ()

        def add_handler(self, handler, group=None):
            self.handlers.append((handler, group))

        def add_error_handler(self, handler, group=None):
            pass

        def remove_handler(self, handler, group=None):
            # הסרה לוגית — לא נדרשת לבדיקה, אך מסופקת למקרה שהקוד יקרא לה
            try:
                self.handlers.remove((handler, -100))
            except Exception:
                pass

    class _Builder:
        def token(self, *a, **k):
            return self

        def defaults(self, *a, **k):
            return self

        def persistence(self, *a, **k):
            return self

        def post_init(self, *a, **k):
            return self

        def build(self):
            return _MiniApp()

    class _AppNS:
        def builder(self):
            return _Builder()

    monkeypatch.setattr(mod, 'Application', _AppNS())

    bot = mod.CodeKeeperBot()

    # קבל את ה-handler ואת ה-job שתוזמן
    maintenance_handlers = [h for h, g in bot.application.handlers if g == -100]
    assert maintenance_handlers, 'expected maintenance handlers to be registered'
    # בחר handler של תחזוקה לפי שם הפונקציה
    maint_msg_handler = None
    for h in maintenance_handlers:
        if getattr(getattr(h, 'callback', None), '__name__', '') == 'maintenance_reply':
            maint_msg_handler = h
            break
    assert maint_msg_handler is not None, 'maintenance handler not found'

    # ודא שהוגדר חלון פעיל (יתכן שה-clear job כבר רץ — נוודא לפני ההפעלה)
    assert getattr(bot, '_maintenance_active_until_ts', 0) >= 0

    # הפעל מיידית את ה-callback של ה-job כדי לדמות סיום warmup
    cb, when, name = bot.application.job_queue.last
    assert name == 'maintenance_clear_handlers'
    await cb(types.SimpleNamespace())  # context מדומה

    # ה-TTL נוטרל
    assert getattr(bot, '_maintenance_active_until_ts', 0) == 0

    # כעת לא אמורה להישלח הודעה
    update = types.SimpleNamespace(callback_query=None, message=_FakeMessage(), effective_user=types.SimpleNamespace(id=3))
    context = types.SimpleNamespace()
    await maint_msg_handler.callback(update, context)
    assert update.message.replies == []


@pytest.mark.asyncio
async def test_maintenance_message_sent_during_warmup_for_callback_query(monkeypatch):
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    monkeypatch.setenv('MAINTENANCE_MODE', 'true')

    import importlib
    import config as cfg
    importlib.reload(cfg)
    import main as mod
    importlib.reload(mod)

    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}

        def add_handler(self, handler, group=None):
            self.handlers.append((handler, group))

        def add_error_handler(self, handler, group=None):
            pass

        def remove_handler(self, handler, group=None):
            pass

    class _Builder:
        def token(self, *a, **k):
            return self

        def defaults(self, *a, **k):
            return self

        def persistence(self, *a, **k):
            return self

        def post_init(self, *a, **k):
            return self

        def build(self):
            return _MiniApp()

    class _AppNS:
        def builder(self):
            return _Builder()

    monkeypatch.setattr(mod, 'Application', _AppNS())

    bot = mod.CodeKeeperBot()

    maintenance_handlers = [h for h, g in bot.application.handlers if g == -100]
    # מצא את ה-CallbackQueryHandler של תחזוקה
    maint_cbq_handler = None
    for h in maintenance_handlers:
        if h.__class__.__name__ == 'CallbackQueryHandler' and getattr(getattr(h, 'callback', None), '__name__', '') == 'maintenance_reply':
            maint_cbq_handler = h
            break
    assert maint_cbq_handler is not None, 'expected maintenance CallbackQueryHandler'

    update = types.SimpleNamespace(callback_query=_FakeCallbackQuery(), message=None, effective_user=types.SimpleNamespace(id=4))
    context = types.SimpleNamespace()
    await maint_cbq_handler.callback(update, context)
    assert update.callback_query.edits, 'expected edit_message_text during warmup'
    assert update.callback_query.edits[-1][0] == mod.config.MAINTENANCE_MESSAGE

