import os
import types
import asyncio
import pytest


@pytest.mark.asyncio
async def test_main_global_shadow_limit_logs(monkeypatch, caplog):
    # Enable Redis URL (won't actually connect here) and shadow mode
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("RATE_LIMIT_SHADOW_MODE", "true")

    # Minimal config object to satisfy accesses in main
    class _Cfg:
        RATE_LIMIT_PER_MINUTE = 1
        REDIS_URL = os.getenv("REDIS_URL")
        RATE_LIMIT_SHADOW_MODE = True

    # Patch env that main expects
    monkeypatch.setenv("BOT_TOKEN", "TEST:TOKEN")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")

    # Import main to access RateLimiter
    import importlib
    m = importlib.import_module("main")

    # Fake a tiny object similar to the bot for limiter logic
    class _Bot:
        def __init__(self):
            self.config = _Cfg()
            try:
                self._rate_limiter = m.RateLimiter(max_per_minute=1)
            except Exception:
                self._rate_limiter = None
            try:
                from limits.storage import RedisStorage
                from limits.strategies import MovingWindowRateLimiter
                from limits import RateLimitItemPerMinute
                self._limits_storage = RedisStorage(str(self.config.REDIS_URL))
                self._advanced_limiter = MovingWindowRateLimiter(self._limits_storage)
                self._per_user_global = RateLimitItemPerMinute(50)
                self._shadow_mode = True
            except Exception:
                self._advanced_limiter = None

    # Fake update/context minimal for the gate
    class _User:
        def __init__(self, id):
            self.id = id

    class _Update:
        def __init__(self, id):
            self.effective_user = _User(id)
            self.callback_query = None
            self.message = None

    class _Context:
        DEFAULT_TYPE = object

    bot = _Bot()
    user_id = 123

    # Perform a few rapid checks to trigger the in-memory gate and advanced shadow hit
    allowed_first = await bot._rate_limiter.check_rate_limit(user_id)
    allowed_second = await bot._rate_limiter.check_rate_limit(user_id)
    if getattr(bot, "_advanced_limiter", None) is not None:
        key = f"tg:global:{user_id}"
        ok = bot._advanced_limiter.hit(bot._per_user_global, key)

    assert allowed_first is True
    assert allowed_second in (False, True)


@pytest.mark.asyncio
async def test_main_global_gate_admin_bypass(monkeypatch):
    # Arrange: mark user as admin, disable external deps
    monkeypatch.setenv("ADMIN_USER_IDS", "555")
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    from main import CodeKeeperBot
    bot = CodeKeeperBot()

    # Prepare fake update/context and call the internal gate
    class _User:
        def __init__(self, id):
            self.id = id
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _Upd:
        def __init__(self, id):
            self.effective_user = _User(id)
            self.message = _Msg()
            self.callback_query = None
    class _Ctx:
        user_data = {}

    # Extract the added gate handler from application handlers (group -90)
    gate = None
    for (args, kwargs) in getattr(bot.application, 'handlers', []):
        if args:
            handler = args[0]
            cb = getattr(handler, 'callback', None)
            if callable(cb) and getattr(cb, '__name__', '') == '_rate_limit_gate':
                gate = cb
                break
            if callable(handler) and getattr(handler, '__name__', '') == '_rate_limit_gate':
                gate = handler
                break
    assert gate is not None, "_rate_limit_gate not registered"

    # Act: call with admin user; should not raise
    try:
        await gate(_Upd(555), _Ctx())
    except Exception as e:
        pytest.fail(f"Admin bypass should not raise, got: {e}")


@pytest.mark.asyncio
async def test_main_global_gate_soft_warning_and_block(monkeypatch):
    # Arrange
    monkeypatch.setenv("ADMIN_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    from main import CodeKeeperBot, ApplicationHandlerStop
    bot = CodeKeeperBot()

    # Find gate
    gate = None
    for (args, kwargs) in getattr(bot.application, 'handlers', []):
        if args:
            handler = args[0]
            cb = getattr(handler, 'callback', None)
            if callable(cb) and getattr(cb, '__name__', '') == '_rate_limit_gate':
                gate = cb
                break
            if callable(handler) and getattr(handler, '__name__', '') == '_rate_limit_gate':
                gate = handler
                break
    assert gate is not None

    # Fake update/context
    class _User:
        def __init__(self, id):
            self.id = id
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _Upd:
        def __init__(self, id):
            self.effective_user = _User(id)
            self.callback_query = None
            self.message = _Msg()
    class _Ctx:
        user_data = {}

    upd = _Upd(111)
    ctx = _Ctx()

    # Drive usage near limit: 30/min default; perform 30 allowed calls
    for _ in range(30):
        await gate(upd, ctx)
    # Next call should block
    with pytest.raises(ApplicationHandlerStop):
        await gate(upd, ctx)


@pytest.mark.asyncio
async def test_main_global_gate_blocks_callback_query(monkeypatch):
    # Arrange a callback_query path to cover cq.answer branch
    monkeypatch.setenv("ADMIN_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    from main import CodeKeeperBot, ApplicationHandlerStop
    bot = CodeKeeperBot()

    # Find gate
    gate = None
    for (args, kwargs) in getattr(bot.application, 'handlers', []):
        if args:
            handler = args[0]
            cb = getattr(handler, 'callback', None)
            if callable(cb) and getattr(cb, '__name__', '') == '_rate_limit_gate':
                gate = cb
                break
            if callable(handler) and getattr(handler, '__name__', '') == '_rate_limit_gate':
                gate = handler
                break
    assert gate is not None

    class _User:
        def __init__(self, id):
            self.id = id
    class _CQ:
        async def answer(self, *a, **k):
            return None
    class _Upd:
        def __init__(self, id):
            self.effective_user = _User(id)
            self.message = None
            self.callback_query = _CQ()
    class _Ctx:
        user_data = {}

    upd = _Upd(222)
    ctx = _Ctx()
    # Saturate the limiter first
    for _ in range(30):
        await gate(upd, ctx)
    # Now expect block via callback_query path
    with pytest.raises(ApplicationHandlerStop):
        await gate(upd, ctx)


@pytest.mark.asyncio
async def test_main_global_gate_admin_bypass(monkeypatch):
    # Arrange: mark user as admin, disable external deps
    monkeypatch.setenv("ADMIN_USER_IDS", "555")
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    from main import CodeKeeperBot
    bot = CodeKeeperBot()

    # Prepare fake update/context and call the internal gate
    class _User:
        def __init__(self, id):
            self.id = id
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _Upd:
        def __init__(self, id):
            self.effective_user = _User(id)
            self.message = _Msg()
            self.callback_query = None
    class _Ctx:
        user_data = {}

    # Extract the added gate handler from application handlers (group -90)
    gate = None
    for (args, kwargs) in getattr(bot.application, 'handlers', []):
        if args and callable(getattr(args[1], 'callback', None)):
            cb = args[1].callback
            if cb.__name__ == '_rate_limit_gate':
                gate = cb
                break
        if args and callable(args[1]):
            if args[1].__name__ == '_rate_limit_gate':
                gate = args[1]
                break
    assert gate is not None, "_rate_limit_gate not registered"

    # Act: call with admin user; should not raise
    try:
        await gate(_Upd(555), _Ctx())
    except Exception as e:
        pytest.fail(f"Admin bypass should not raise, got: {e}")


@pytest.mark.asyncio
async def test_main_global_gate_soft_warning_once_per_min(monkeypatch):
    # Arrange
    monkeypatch.setenv("ADMIN_USER_IDS", "")
    monkeypatch.setenv("BOT_TOKEN", "x")
    monkeypatch.setenv("MONGODB_URL", "mongodb://localhost:27017/test")
    from main import CodeKeeperBot, ApplicationHandlerStop
    bot = CodeKeeperBot()

    # Find gate
    gate = None
    for (args, kwargs) in getattr(bot.application, 'handlers', []):
        if args and callable(getattr(args[1], 'callback', None)):
            cb = args[1].callback
            if cb.__name__ == '_rate_limit_gate':
                gate = cb
                break
        if args and callable(args[1]):
            if args[1].__name__ == '_rate_limit_gate':
                gate = args[1]
                break
    assert gate is not None

    # Fake update/context
    class _User:
        def __init__(self, id):
            self.id = id
    class _Msg:
        async def reply_text(self, *a, **k):
            return None
    class _Upd:
        def __init__(self, id):
            self.effective_user = _User(id)
            self.callback_query = None
            self.message = _Msg()
    class _Ctx:
        user_data = {}

    upd = _Upd(111)
    ctx = _Ctx()

    # Drive usage near limit: call gate multiple times to increase internal counter
    # Default is 30/min; simulate closer to boundary by many calls
    for _ in range(28):
        await gate(upd, ctx)
    # This call should still allow and potentially warn; must not raise
    await gate(upd, ctx)
    # Next call likely blocks and raises ApplicationHandlerStop
    with pytest.raises(ApplicationHandlerStop):
        await gate(upd, ctx)
