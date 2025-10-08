import types
import asyncio
import pytest


class _FakeUser:
    def __init__(self, uid):
        self.id = uid


class _FakeMessage:
    def __init__(self):
        self.replies = []
    async def reply_text(self, text):
        self.replies.append(text)


class _FakeCallbackQuery:
    def __init__(self):
        self.answered = []
    async def answer(self, text=None, show_alert=False, cache_time=None):
        self.answered.append((text, show_alert, cache_time))


@pytest.mark.asyncio
async def test_rate_limit_gate_blocks_message_flow(monkeypatch):
    # הגדר ENV הכרחיים לבנייה
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')

    # עקוף את Application.builder כדי להחזיר אפליקציה מינימלית תואמת
    import main as mod

    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}
        def add_handler(self, handler, group=None):
            # נשמור tuple לדיבוג
            self.handlers.append((handler, group))
        def add_error_handler(self, handler, group=None):
            # no-op לצורך התאמה לממשק
            pass

    class _Builder:
        def __init__(self):
            pass
        def token(self, *a, **k): return self
        def defaults(self, *a, **k): return self
        def persistence(self, *a, **k): return self
        def post_init(self, *a, **k): return self
        def build(self): return _MiniApp()

    class _AppNS:
        def __init__(self):
            self._b = _Builder()
        def builder(self):
            return self._b

    monkeypatch.setattr(mod, 'Application', _AppNS())

    bot = mod.CodeKeeperBot()

    # מצא את פונקציית השער שהוספנו בקבוצה -90
    gate_handler = None
    for handler, group in bot.application.handlers:
        if group == -90:
            gate_handler = handler
            break

    assert gate_handler is not None, 'Rate limit gate handler not registered'

    # החמרת מגבלה: 1 לדקה
    bot._rate_limiter.max_per_minute = 1

    # בנה update מזויף עם הודעה
    update = types.SimpleNamespace(effective_user=_FakeUser(5), message=_FakeMessage(), callback_query=None)
    context = types.SimpleNamespace()

    # קריאה ראשונה צריכה לעבור בשקט (אין חריגה)
    await gate_handler.callback(update, context)
    # קריאה שנייה — צריכה לחסום ולשלוח הודעה קצרה
    await gate_handler.callback(update, context)

    # ודא שנשלחה הודעת חסימה
    assert update.message.replies, 'expected a throttling reply on second call'


@pytest.mark.asyncio
async def test_rate_limit_gate_blocks_callback_query(monkeypatch):
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')

    import main as mod

    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}
        def add_handler(self, handler, group=None):
            self.handlers.append((handler, group))
        def add_error_handler(self, handler, group=None):
            pass

    class _Builder:
        def token(self, *a, **k): return self
        def defaults(self, *a, **k): return self
        def persistence(self, *a, **k): return self
        def post_init(self, *a, **k): return self
        def build(self): return _MiniApp()

    class _AppNS:
        def builder(self):
            return _Builder()

    monkeypatch.setattr(mod, 'Application', _AppNS())

    bot = mod.CodeKeeperBot()

    gates = [h for h, g in bot.application.handlers if g == -90]
    assert len(gates) >= 2, 'expected both message and callback gates registered'
    gate = gates[1]

    bot._rate_limiter.max_per_minute = 1

    update = types.SimpleNamespace(effective_user=_FakeUser(9), message=None, callback_query=_FakeCallbackQuery())
    context = types.SimpleNamespace()

    await gate.callback(update, context)  # first
    await gate.callback(update, context)  # second -> should block

    assert update.callback_query.answered, 'expected an answer() on throttling'


@pytest.mark.asyncio
async def test_rate_limit_gate_with_no_effective_user(monkeypatch):
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')

    import main as mod

    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}
        def add_handler(self, handler, group=None):
            self.handlers.append((handler, group))

    class _Builder:
        def token(self, *a, **k): return self
        def defaults(self, *a, **k): return self
        def persistence(self, *a, **k): return self
        def post_init(self, *a, **k): return self
        def build(self): return _MiniApp()

    class _AppNS:
        def builder(self):
            return _Builder()

    monkeypatch.setattr(mod, 'Application', _AppNS())

    bot = mod.CodeKeeperBot()
    gate = [h for h, g in bot.application.handlers if g == -90][0]

    # אין effective_user ואין callback_query
    update = types.SimpleNamespace(effective_user=None, message=_FakeMessage(), callback_query=None)
    context = types.SimpleNamespace()
    # אסור לקרוס/לשלוח תשובה
    await gate.callback(update, context)
    assert update.message.replies == []


@pytest.mark.asyncio
async def test_rate_limit_gate_when_limiter_raises_allows_pass(monkeypatch):
    monkeypatch.setenv('BOT_TOKEN', 'x')
    monkeypatch.setenv('MONGODB_URL', 'mongodb://localhost:27017/test')

    import main as mod

    class _MiniApp:
        def __init__(self):
            self.handlers = []
            self.bot_data = {}
        def add_handler(self, handler, group=None):
            self.handlers.append((handler, group))
        def add_error_handler(self, handler, group=None):
            pass

    class _Builder:
        def token(self, *a, **k): return self
        def defaults(self, *a, **k): return self
        def persistence(self, *a, **k): return self
        def post_init(self, *a, **k): return self
        def build(self): return _MiniApp()

    class _AppNS:
        def builder(self):
            return _Builder()

    monkeypatch.setattr(mod, 'Application', _AppNS())

    bot = mod.CodeKeeperBot()
    gate = [h for h, g in bot.application.handlers if g == -90][0]

    # הפוך את ה-limiter כך שיזרוק חריגה -> צריך לאפשר מעבר ולא לשלוח תשובה
    async def _boom(_uid):
        raise RuntimeError('boom')
    bot._rate_limiter.check_rate_limit = _boom  # type: ignore

    update = types.SimpleNamespace(effective_user=_FakeUser(11), message=_FakeMessage(), callback_query=None)
    context = types.SimpleNamespace()

    # אסור לקרוס או לענות
    await gate.callback(update, context)
    assert update.message.replies == []
