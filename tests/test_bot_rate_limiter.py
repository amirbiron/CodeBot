import os
import pytest


@pytest.mark.asyncio
async def test_bot_rate_limiter_shadow_mode_allows(monkeypatch):
    # Arrange: point to fake Redis (no connection made until hit), enable shadow mode
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("RATE_LIMIT_SHADOW_MODE", "true")

    from bot_rate_limiter import check_rate_limit  # import after env set

    # Act: send more requests than sensitive limit would allow (5/min)
    user_id = 123456
    scope = "unit_test_sensitive"
    results = [check_rate_limit(user_id, scope, "sensitive") for _ in range(7)]

    # Assert: in shadow mode we should never block (all True)
    assert all(results) is True


def test_bot_rate_limiter_admin_bypass(monkeypatch):
    # Arrange: set admin id
    admin_id = 999
    monkeypatch.setenv("ADMIN_USER_IDS", str(admin_id))
    monkeypatch.setenv("REDIS_URL", "")  # disable Redis to avoid network

    from bot_rate_limiter import rate_limit

    calls = {"count": 0}

    @rate_limit(scope="x", limit_name="sensitive", bypass_admins=True)
    async def handler(update, context):
        calls["count"] += 1
        return True

    class _User:
        def __init__(self, id):
            self.id = id

    class _Update:
        def __init__(self, id):
            self.effective_user = _User(id)
            self.message = None

    class _Context:
        bot_data = {}

    # Act: call as admin multiple times; should not be throttled
    import asyncio

    upd = _Update(admin_id)
    ctx = _Context()
    for _ in range(10):
        asyncio.get_event_loop().run_until_complete(handler(upd, ctx))

    # Assert: handler executed each time
    assert calls["count"] == 10
