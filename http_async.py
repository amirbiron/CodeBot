from __future__ import annotations
import os
import asyncio
from typing import Optional, Any

try:
    import aiohttp  # type: ignore
except Exception:  # pragma: no cover
    aiohttp = None  # type: ignore

_session: Optional["aiohttp.ClientSession"] = None  # type: ignore[name-defined]


def _int_env(name: str, default: int) -> int:
    try:
        env_val = os.getenv(name)
        if env_val not in (None, ""):
            return int(env_val)
    except Exception:
        pass
    # Fallback to config if available
    try:
        from config import config  # type: ignore
        return int(getattr(config, name, default))
    except Exception:
        return default


def _build_session_kwargs() -> dict[str, Any]:
    kwargs: dict[str, Any] = {}
    if aiohttp is None:  # pragma: no cover
        return kwargs
    total = _int_env("AIOHTTP_TIMEOUT_TOTAL", 10)
    limit = _int_env("AIOHTTP_POOL_LIMIT", 50)
    limit_per_host = _int_env("AIOHTTP_LIMIT_PER_HOST", 0)
    try:
        timeout = aiohttp.ClientTimeout(total=total)  # type: ignore[attr-defined]
        kwargs["timeout"] = timeout
    except Exception:
        pass
    try:
        connector = aiohttp.TCPConnector(
            limit=limit,
            limit_per_host=(None if limit_per_host <= 0 else limit_per_host),
            use_dns_cache=True,
            ttl_dns_cache=300,
            enable_cleanup_closed=True,
            force_close=False,
        )
        kwargs["connector"] = connector
    except Exception:
        pass
    return kwargs


def get_session() -> "aiohttp.ClientSession":  # type: ignore[name-defined]
    global _session
    if aiohttp is None:  # pragma: no cover
        raise RuntimeError("aiohttp is not available in this environment")
    # אם יש סשן קיים אבל הוא שייך ללולאה אחרת/סגורה – נבנה סשן חדש
    try:
        current_loop = asyncio.get_event_loop()
    except Exception:
        current_loop = None  # type: ignore[assignment]
    if _session is not None and not getattr(_session, "closed", False):
        # נסה לחלץ את הלולאה המקורית של הסשן/קונקטור (מאפיין פנימי אך יציב יחסית)
        session_loop = getattr(_session, "_loop", None)
        if session_loop is None:
            connector = getattr(_session, "_connector", None)
            session_loop = getattr(connector, "_loop", None)
        try:
            loop_is_closed = bool(getattr(session_loop, "is_closed", lambda: False)()) if session_loop else False
        except Exception:
            loop_is_closed = False
        if session_loop is not None and (loop_is_closed or (current_loop is not None and session_loop is not current_loop)):
            # נסה לסגור את הסשן הישן בלולאה שלו (best-effort), ואז ניצור חדש
            try:
                is_running = bool(getattr(session_loop, "is_running", lambda: False)())
            except Exception:
                is_running = False
            try:
                if is_running:
                    session_loop.create_task(_session.close())  # type: ignore[call-arg]
                else:
                    session_loop.run_until_complete(_session.close())  # type: ignore[call-arg]
            except Exception:
                # אל תמנע בנייה מחדש גם אם הסגירה נכשלה
                pass
            finally:
                _session = None
    if _session is None or getattr(_session, "closed", False):
        kwargs = _build_session_kwargs()
        _session = aiohttp.ClientSession(**kwargs)
    return _session


async def close_session() -> None:
    global _session
    try:
        if _session is not None and not getattr(_session, "closed", False):
            await _session.close()
    finally:
        _session = None
