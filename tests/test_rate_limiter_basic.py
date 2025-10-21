import asyncio
import pytest

from rate_limiter import RateLimiter
import os


@pytest.mark.asyncio
async def test_rate_limiter_allows_up_to_limit_then_blocks():
    limiter = RateLimiter(max_per_minute=3)
    user_id = 123

    assert await limiter.check_rate_limit(user_id) is True
    assert await limiter.check_rate_limit(user_id) is True
    assert await limiter.check_rate_limit(user_id) is True
    # רביעית צריכה להיחסם
    assert await limiter.check_rate_limit(user_id) is False


@pytest.mark.asyncio
async def test_rate_limiter_window_cleanup_allows_after_old_entries_removed():
    limiter = RateLimiter(max_per_minute=2)
    user_id = 77

    # מלא את החלון
    assert await limiter.check_rate_limit(user_id) is True
    assert await limiter.check_rate_limit(user_id) is True
    assert await limiter.check_rate_limit(user_id) is False

    # הפוך את כל הרשומות לישנות מ-60 שניות כדי להתנקה בבדיקה הבאה
    from datetime import datetime, timedelta, timezone
    too_old = datetime.now(timezone.utc) - timedelta(seconds=120)
    limiter._requests[user_id] = [too_old, too_old]

    # עכשיו צריך לאפשר מחדש
    assert await limiter.check_rate_limit(user_id) is True


@pytest.mark.asyncio
async def test_rate_limiter_cleanup_all_expired_limit_1():
    limiter = RateLimiter(max_per_minute=1)
    user_id = 88
    # מלא
    assert await limiter.check_rate_limit(user_id) is True
    assert await limiter.check_rate_limit(user_id) is False
    # הפוך את הרשומה היחידה לישנה
    from datetime import datetime, timedelta, timezone
    too_old = datetime.now(timezone.utc) - timedelta(seconds=120)
    limiter._requests[user_id] = [too_old]
    # צריך להתנקה לחלוטין ולאפשר
    assert await limiter.check_rate_limit(user_id) is True


def test_limits_packages_present():
    # Ensure optional advanced limiting deps are installed per issue #910
    try:
        import flask_limiter  # type: ignore
        import limits  # type: ignore
    except Exception as e:
        raise AssertionError(f"Rate limiting deps missing: {e}")


@pytest.mark.asyncio
async def test_rate_limiter_usage_ratio_soft_warning_path():
    rl = RateLimiter(max_per_minute=5)
    uid = 42
    # 4/5 hits → ratio ≈ 0.8
    for _ in range(4):
        assert await rl.check_rate_limit(uid) is True
    ratio = await rl.get_current_usage_ratio(uid)
    assert 0.79 <= ratio <= 0.81
    # 5th allowed, 6th blocked
    assert await rl.check_rate_limit(uid) is True
    assert await rl.check_rate_limit(uid) is False


@pytest.mark.asyncio
async def test_rate_limiter_usage_ratio_soft_warning_path():
    rl = RateLimiter(max_per_minute=5)
    uid = 42
    # 4/5 hits → ratio ≈ 0.8
    for _ in range(4):
        assert await rl.check_rate_limit(uid) is True
    ratio = await rl.get_current_usage_ratio(uid)
    assert 0.79 <= ratio <= 0.81
    # 5th allowed, 6th blocked
    assert await rl.check_rate_limit(uid) is True
    assert await rl.check_rate_limit(uid) is False
