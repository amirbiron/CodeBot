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

    import main as mod

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
    maint_msg_handler = maintenance_handlers[0]

    update = types.SimpleNamespace(callback_query=None, message=_FakeMessage(), effective_user=types.SimpleNamespace(id=1))
    context = types.SimpleNamespace()

    # בזמן warmup אמורה להישלח הודעת תחזוקה
    await maint_msg_handler.callback(update, context)
    assert update.message.replies, 'expected maintenance reply during warmup'
    assert update.message.replies[-1] == mod.config.MAINTENANCE_MESSAGE


@pytest.mark.asyncio
async def test_maintenance_message_not_sent_after_ttl_elapsed_by_time(monkeypatch):
    # הגדרת זמן מדומה כדי לשלוט על TTL
    import main as mod

    base_time = 1_000.0
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')
    monkeypatch.setenv('MAINTENANCE_MODE', 'true')
    monkeypatch.setenv('MAINTENANCE_AUTO_WARMUP_SECS', '10')

    # זמן בסיס בעת יצירה
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

    import main as mod

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
    maint_msg_handler = maintenance_handlers[0]

    # ודא שהוגדר חלון פעיל
    assert getattr(bot, '_maintenance_active_until_ts', 0) > 0

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

    import main as mod

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
    assert len(maintenance_handlers) >= 2, 'expected both maintenance handlers'
    maint_cbq_handler = maintenance_handlers[1]

    update = types.SimpleNamespace(callback_query=_FakeCallbackQuery(), message=None, effective_user=types.SimpleNamespace(id=4))
    context = types.SimpleNamespace()
    await maint_cbq_handler.callback(update, context)
    assert update.callback_query.edits, 'expected edit_message_text during warmup'
    assert update.callback_query.edits[-1][0] == mod.config.MAINTENANCE_MESSAGE

