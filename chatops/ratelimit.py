"""
Rate-limit utilities for sensitive ChatOps commands.

- Cooldown (seconds) per user+command, defaults to 5 seconds
- Configured via ENV SENSITIVE_COMMAND_COOLDOWN_SEC
- Decorator: limit_sensitive(command_name)
"""
from __future__ import annotations

import os
import time
import asyncio
import functools
from typing import Dict, Tuple, Awaitable, Callable, Any


class SensitiveCommandRateLimiter:
    def __init__(self, cooldown_sec: int = 5) -> None:
        self._cooldown_sec = max(1, int(cooldown_sec or 5))
        self._last_call_ts: Dict[Tuple[int, str], float] = {}
        self._lock = asyncio.Lock()

    @property
    def cooldown_sec(self) -> int:
        return self._cooldown_sec

    @cooldown_sec.setter
    def cooldown_sec(self, value: int) -> None:
        try:
            self._cooldown_sec = max(1, int(value or 5))
        except Exception:
            self._cooldown_sec = 5

    async def should_allow(self, user_id: int, command_name: str) -> Tuple[bool, int]:
        now = time.monotonic()
        key = (int(user_id or 0), str(command_name or ""))
        async with self._lock:
            last = self._last_call_ts.get(key, 0.0)
            remaining = self._cooldown_sec - int(now - last)
            if last and remaining > 0:
                return False, remaining
            self._last_call_ts[key] = now
            return True, 0


def _get_default_cooldown() -> int:
    try:
        return max(1, int(os.getenv("SENSITIVE_COMMAND_COOLDOWN_SEC", "5")))
    except Exception:
        return 5


sensitive_limiter = SensitiveCommandRateLimiter(_get_default_cooldown())


def limit_sensitive(command_name: str) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """Decorator to throttle sensitive command handlers per user."""
    def _decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @functools.wraps(func)
        async def _wrapper(update, context, *args, **kwargs):  # type: ignore[override]
            try:
                user_id = int(getattr(getattr(update, 'effective_user', None), 'id', 0) or 0)
            except Exception:
                user_id = 0
            if user_id:
                try:
                    allowed, remaining = await sensitive_limiter.should_allow(user_id, command_name)
                except Exception:
                    allowed, remaining = True, 0
                if not allowed:
                    try:
                        msg = getattr(update, 'message', None)
                        if msg is not None:
                            await msg.reply_text(f"⏳ אנא נסה שוב בעוד {remaining} שניות")
                    except Exception:
                        pass
                    return
            return await func(update, context, *args, **kwargs)
        return _wrapper
    return _decorator
