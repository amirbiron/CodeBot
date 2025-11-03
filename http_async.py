from __future__ import annotations
import os
import asyncio
import time
from urllib.parse import urlparse
from typing import Optional, Any, Mapping

try:
    import aiohttp  # type: ignore
except Exception:  # pragma: no cover
    aiohttp = None  # type: ignore

_session: Optional["aiohttp.ClientSession"] = None  # type: ignore[name-defined]

try:
    from observability_instrumentation import traced, set_span_attributes
except Exception:  # pragma: no cover
    def traced(*_a, **_k):
        def _inner(f):
            return f
        return _inner

    def set_span_attributes(*_a, **_k):
        return None


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


def _normalize_headers(headers: Any) -> Mapping[str, str]:
    if headers is None:
        return {}
    if isinstance(headers, Mapping):
        items = headers.items()
    else:
        try:
            items = dict(headers).items()  # type: ignore[arg-type]
        except Exception:
            return {}
    normalized: dict[str, str] = {}
    for key, value in items:
        if key is None or value is None:
            continue
        try:
            skey = str(key)
            svalue = str(value)
        except Exception:
            continue
        normalized[skey] = svalue
    return normalized


def _prepare_headers(headers: Any) -> Any:
    base = _normalize_headers(headers)
    try:
        from observability import prepare_outgoing_headers  # type: ignore

        merged = prepare_outgoing_headers(base or None)
    except Exception:
        merged = None
    if merged is None or merged == {}:
        if headers is None:
            return None
        if base:
            return base
        return headers
    try:
        if aiohttp is not None:
            from aiohttp import CIMultiDict  # type: ignore[attr-defined]

            return CIMultiDict(merged.items())
    except Exception:
        pass
    return merged


def _instrument_session(session: "aiohttp.ClientSession") -> None:  # type: ignore[name-defined]
    if session is None:
        return
    if getattr(session, "_codebot_ctx_headers", False):
        return

    original_request = session._request  # type: ignore[attr-defined]
    tracer = traced("http.request.async", attributes={"component": "http"})

    @tracer  # type: ignore[misc]
    async def _request(method: str, url: str, **kwargs):  # type: ignore[override]
        start = time.perf_counter()
        attrs: dict[str, Any] = {
            "component": "http",
            "http.method": str(method).upper(),
            "http.url": str(url),
        }
        try:
            parsed = urlparse(str(url))
            if parsed.netloc:
                attrs["server.address"] = parsed.netloc
        except Exception:
            pass
        set_span_attributes(attrs)
        try:
            prepared = _prepare_headers(kwargs.get("headers"))
            if prepared is not None:
                kwargs["headers"] = prepared
        except Exception:
            pass
        response = await original_request(method, url, **kwargs)
        try:
            status_code = int(getattr(response, "status", 0) or 0)
        except Exception:
            status_code = 0
        set_span_attributes({
            "http.status_code": status_code,
            "http.duration_ms": (time.perf_counter() - start) * 1000.0,
        })
        return response

    session._request = _request  # type: ignore[assignment]
    setattr(session, "_codebot_ctx_headers", True)


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
    _instrument_session(_session)
    return _session


async def close_session() -> None:
    global _session
    try:
        if _session is not None and not getattr(_session, "closed", False):
            await _session.close()
    finally:
        _session = None
