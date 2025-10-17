"""
Permissions utilities for ChatOps commands.

- Admin allowlist via ENV ADMIN_USER_IDS (comma-separated integers)
- Optional chat allowlist via ENV ALLOWED_CHAT_IDS (comma-separated integers)
- Decorators for admin-only and chat-allowlisted commands
"""
from __future__ import annotations

import os
import functools
from typing import Callable, Iterable, Set, Optional, Awaitable, Any


def _parse_int_set(raw: str) -> Set[int]:
    values: Set[int] = set()
    for part in (raw or "").split(','):
        s = part.strip()
        if not s:
            continue
        try:
            values.add(int(s))
        except Exception:
            continue
    return values


def get_admin_user_ids() -> Set[int]:
    return _parse_int_set(os.getenv("ADMIN_USER_IDS", ""))


def is_admin(user_id: int) -> bool:
    try:
        return int(user_id) in get_admin_user_ids()
    except Exception:
        return False


def get_allowed_chat_ids() -> Set[int]:
    return _parse_int_set(os.getenv("ALLOWED_CHAT_IDS", ""))


def is_chat_allowed(chat_id: Optional[int]) -> bool:
    try:
        allowlist = get_allowed_chat_ids()
        if not allowlist:
            return True  # no restriction configured
        if chat_id is None:
            return True  # best-effort: do not block when chat id is unavailable
        return int(chat_id) in allowlist
    except Exception:
        return True


def admin_required(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    @functools.wraps(func)
    async def wrapper(update, context, *args, **kwargs):  # type: ignore[override]
        try:
            user_id = int(getattr(getattr(update, 'effective_user', None), 'id', 0) or 0)
        except Exception:
            user_id = 0
        if not is_admin(user_id):
            # best-effort reply
            try:
                msg = getattr(update, 'message', None)
                if msg is not None:
                    await msg.reply_text("❌ פקודה זמינה למנהלים בלבד")
            except Exception:
                pass
            return
        return await func(update, context, *args, **kwargs)
    return wrapper


def chat_allowlist_required(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    @functools.wraps(func)
    async def wrapper(update, context, *args, **kwargs):  # type: ignore[override]
        try:
            chat = getattr(update, 'effective_chat', None)
            chat_id = int(getattr(chat, 'id', 0) or 0)
        except Exception:
            chat_id = None
        if not is_chat_allowed(chat_id):
            try:
                msg = getattr(update, 'message', None)
                if msg is not None:
                    await msg.reply_text("⛔ פקודה זו זמינה רק בצ'אטים מורשים")
            except Exception:
                pass
            return
        return await func(update, context, *args, **kwargs)
    return wrapper
