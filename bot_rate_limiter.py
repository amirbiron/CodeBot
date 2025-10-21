from __future__ import annotations

"""
Advanced Telegram bot rate limiting using limits + Redis, with shadow mode and admin bypass.
"""
import os
import logging
from functools import wraps
from typing import Awaitable, Callable, Any

from limits import RateLimitItemPerMinute, RateLimitItemPerHour, RateLimitItemPerDay
from limits.storage import RedisStorage
from limits.strategies import MovingWindowRateLimiter

logger = logging.getLogger(__name__)

# Redis storage (fail-open to in-memory if URL missing)
_REDIS_URL = os.getenv("REDIS_URL")
_storage = RedisStorage(_REDIS_URL) if _REDIS_URL else None
_limiter = MovingWindowRateLimiter(_storage) if _storage is not None else None

# Define limits
LIMITS = {
    "default": RateLimitItemPerMinute(20),
    "sensitive": RateLimitItemPerMinute(5),
    "heavy": RateLimitItemPerHour(10),
    "signup": RateLimitItemPerDay(3),
}

class RateLimitExceeded(Exception):
    pass

def _admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_USER_IDS", "")
    ids: set[int] = set()
    for part in raw.split(','):
        part = part.strip()
        if part.isdigit():
            ids.add(int(part))
    return ids

def _get_user_key(user_id: int, scope: str) -> str:
    return f"tg:{scope}:{int(user_id)}"

def check_rate_limit(user_id: int, scope: str, limit_name: str = "default") -> bool:
    if _limiter is None:
        return True
    shadow_mode = os.getenv("RATE_LIMIT_SHADOW_MODE", "false").lower() in {"1", "true", "yes"}
    key = _get_user_key(user_id, scope)
    ok = _limiter.hit(LIMITS[limit_name], key)
    # metrics/logging (best-effort)
    try:
        from metrics import rate_limit_hits, rate_limit_blocked  # type: ignore
        if rate_limit_hits is not None:
            rate_limit_hits.labels(source="telegram", scope=scope, limit=limit_name, result=("allowed" if ok else "blocked")).inc()
        if not ok and rate_limit_blocked is not None:
            rate_limit_blocked.labels(source="telegram", scope=scope, limit=limit_name).inc()
    except Exception:
        pass
    if shadow_mode and not ok:
        logger.info("Rate limit would block (shadow mode)", extra={"user_id": user_id, "scope": scope, "limit": limit_name})
        return True
    return ok

def rate_limit(scope: str, limit_name: str = "default", bypass_admins: bool = True):
    def decorator(func: Callable[..., Awaitable[Any]]):
        @wraps(func)
        async def wrapper(update, context, *args, **kwargs):
            try:
                user = getattr(update, 'effective_user', None)
                user_id = int(getattr(user, 'id', 0) or 0)
            except Exception:
                user_id = 0
            if user_id:
                if bypass_admins and user_id in _admin_ids():
                    return await func(update, context, *args, **kwargs)
                if not check_rate_limit(user_id, scope, limit_name):
                    try:
                        msg = getattr(update, 'message', None)
                        if msg is not None:
                            await msg.reply_text(
                                "⏰ אתה שולח יותר מדי בקשות.\n"
                                "אנא נסה שוב בעוד כמה דקות.\n\n"
                                "אם אתה חושב שזו טעות, צור קשר עם התמיכה."
                            )
                    except Exception:
                        pass
                    raise RateLimitExceeded(f"User {user_id} exceeded {limit_name} limit")
            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator
