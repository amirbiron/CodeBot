import types
import asyncio
import pytest
from telegram.ext._application import ApplicationHandlerStop


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
    # קריאה שנייה — צריכה לחסום ולשלוח הודעה קצרה ולזרוק ApplicationHandlerStop
    with pytest.raises(ApplicationHandlerStop):
        await gate_handler.callback(update, context)

    # ודא שנשלחה הודעת חסימה
    assert update.message.replies, 'expected a throttling reply on second call'
    assert update.message.replies[-1] == "⚠️ יותר מדי בקשות, נסה שוב בעוד מספר שניות"


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
    with pytest.raises(ApplicationHandlerStop):
        await gate.callback(update, context)  # second -> should block

    assert update.callback_query.answered, 'expected an answer() on throttling'
    assert update.callback_query.answered[-1] == ("יותר מדי בקשות, נסה שוב עוד רגע", False, 1)


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


@pytest.mark.asyncio
async def test_rate_limit_gate_soft_warning_message_once_per_min(monkeypatch):
    # Arrange baseline env and minimal Application
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

    # Extract the gate handler (group -90)
    gate_handler = None
    for handler, group in bot.application.handlers:
        if group == -90:
            gate_handler = handler
            break
    assert gate_handler is not None

    # Make it easy to reach 80% threshold
    bot._rate_limiter.max_per_minute = 5

    # Fake update/context with message path and user_data for anti-spam state
    update = types.SimpleNamespace(effective_user=_FakeUser(777), message=_FakeMessage(), callback_query=None)
    context = types.SimpleNamespace(user_data={})

    # Drive to 80% (4/5)
    for _ in range(3):
        await gate_handler.callback(update, context)
    # At this point no soft warning yet
    assert update.message.replies == []

    # The 4th allowed call should trigger soft-warning (>= 0.8)
    await gate_handler.callback(update, context)
    assert len(update.message.replies) == 1
    assert update.message.replies[-1] == "ℹ️ חיווי: אתה מתקרב למגבלת הקצב. אם תמשיך בקצב הזה ייתכן שתחסם זמנית."
    # Anti-spam timestamp should be recorded
    assert isinstance(context.user_data, dict) and context.user_data.get('_soft_warn_ts')

    # Next allowed call (5th) should NOT send another warning within a minute
    await gate_handler.callback(update, context)
    assert len(update.message.replies) == 1

    # The next call should block and send throttling message
    with pytest.raises(ApplicationHandlerStop):
        await gate_handler.callback(update, context)
    assert update.message.replies[-1] == "⚠️ יותר מדי בקשות, נסה שוב בעוד מספר שניות"


@pytest.mark.asyncio
async def test_rate_limit_gate_soft_warning_callback_query_once_per_min(monkeypatch):
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

    gate_handler = None
    for handler, group in bot.application.handlers:
        if group == -90:
            gate_handler = handler
            break
    assert gate_handler is not None

    bot._rate_limiter.max_per_minute = 5

    update = types.SimpleNamespace(effective_user=_FakeUser(888), message=None, callback_query=_FakeCallbackQuery())
    context = types.SimpleNamespace(user_data={})

    # Bring ratio close to 0.8
    for _ in range(3):
        await gate_handler.callback(update, context)
    assert update.callback_query.answered == []

    # 4th allowed call → soft warning via callback_query.answer
    await gate_handler.callback(update, context)
    assert len(update.callback_query.answered) == 1
    assert update.callback_query.answered[-1] == ("Heads-up: אתה מתקרב למגבלת הקצב (80%+)", False, 1)

    # 5th allowed call should not warn again (anti-spam)
    await gate_handler.callback(update, context)
    assert len(update.callback_query.answered) == 1

    # 6th call should block via callback_query path
    with pytest.raises(ApplicationHandlerStop):
        await gate_handler.callback(update, context)
    assert update.callback_query.answered[-1] == ("יותר מדי בקשות, נסה שוב עוד רגע", False, 1)
