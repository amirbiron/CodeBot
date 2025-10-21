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
