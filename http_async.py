from __future__ import annotations
import os
import asyncio
from typing import Optional, Any, Mapping
import time
import logging

from resilience import (
    DEFAULT_CIRCUIT_POLICY,
    DEFAULT_RETRY_POLICY,
    CircuitBreakerPolicy,
    RetryPolicy,
    compute_backoff_delay,
    get_circuit_breaker,
    note_request_duration,
    note_retry,
    resolve_labels,
)

try:
    import aiohttp  # type: ignore
except Exception:  # pragma: no cover
    aiohttp = None  # type: ignore

try:
    from observability import emit_event as _emit_event  # type: ignore
except Exception:  # pragma: no cover
    def _emit_event(_event: str, **_fields):  # type: ignore
        return None

logger = logging.getLogger(__name__)

_session: Optional["aiohttp.ClientSession"] = None  # type: ignore[name-defined]


class CircuitOpenError(RuntimeError):
    def __init__(self, service: str, endpoint: str):
        super().__init__(f"Circuit open for {service}:{endpoint}")
        self.service = service
        self.endpoint = endpoint


_RETRYABLE_STATUS_EXTRA = {408, 425, 429}


def _should_retry_status(status_code: int) -> bool:
    try:
        code = int(status_code)
    except Exception:
        return False
    if code >= 500:
        return True
    return code in _RETRYABLE_STATUS_EXTRA


def _is_retryable_exception(exc: Exception) -> bool:
    retryable = (asyncio.TimeoutError,)
    if aiohttp is not None:
        retryable = retryable + (aiohttp.ClientError,)  # type: ignore[attr-defined]
    return isinstance(exc, retryable)


async def _async_sleep_with_backoff(attempt: int, policy: RetryPolicy) -> None:
    delay = compute_backoff_delay(attempt, policy)
    if delay <= 0:
        return
    try:
        await asyncio.sleep(delay)
    except Exception:
        return


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


def _float_env(name: str, default: float) -> float:
    try:
        env_val = os.getenv(name)
        if env_val not in (None, ""):
            return float(env_val)
    except Exception:
        pass
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

    original_request = getattr(session, "_request", None)  # type: ignore[attr-defined]
    if original_request is None or not callable(original_request):
        # אין לנו מה לעטוף אם המופע לא תומך ב-request פנימי (במוקים מסוימים)
        return

    async def _request(method: str, url: str, **kwargs):  # type: ignore[override]
        try:
            prepared = _prepare_headers(kwargs.get("headers"))
            if prepared is not None:
                kwargs["headers"] = prepared
        except Exception:
            pass
        return await original_request(method, url, **kwargs)

    session._request = _request  # type: ignore[assignment]
    setattr(session, "_codebot_ctx_headers", True)


class _ResilientRequestContext:
    def __init__(
        self,
        method: str,
        url: str,
        *,
        session: Optional["aiohttp.ClientSession"],  # type: ignore[name-defined]
        service: Optional[str],
        endpoint: Optional[str],
        retry_policy: Optional[RetryPolicy],
        circuit_policy: Optional[CircuitBreakerPolicy],
        max_attempts_override: Optional[int],
        backoff_base_override: Optional[float],
        backoff_cap_override: Optional[float],
        jitter_override: Optional[float],
        **kwargs,
    ) -> None:
        self.method = str(method).upper()
        self.url = str(url)
        self._session = session
        self._request_kwargs = dict(kwargs)
        self._service_hint = service
        self._endpoint_hint = endpoint
        self._slow_ms = _float_env("HTTP_SLOW_MS", 0.0)

        base_policy = retry_policy or DEFAULT_RETRY_POLICY

        def _maybe_int(value, fallback):
            try:
                return max(1, int(value))
            except Exception:
                return fallback

        def _maybe_float(value, fallback):
            try:
                return float(value)
            except Exception:
                return fallback

        if (
            max_attempts_override is not None
            or backoff_base_override is not None
            or backoff_cap_override is not None
            or jitter_override is not None
        ):
            base_policy = RetryPolicy(
                max_attempts=_maybe_int(max_attempts_override, base_policy.max_attempts),
                backoff_base=_maybe_float(backoff_base_override, base_policy.backoff_base),
                backoff_cap=_maybe_float(backoff_cap_override, base_policy.backoff_cap),
                jitter=_maybe_float(jitter_override, base_policy.jitter),
            )

        self._retry_policy = base_policy
        self._circuit_policy = circuit_policy or DEFAULT_CIRCUIT_POLICY

        (
            self._service_label,
            self._endpoint_label,
            self._display_service,
            self._display_endpoint,
        ) = resolve_labels(self.url, self._service_hint, self._endpoint_hint)

        self._breaker = get_circuit_breaker(
            self._service_label,
            self._endpoint_label,
            display_service=self._display_service,
            display_endpoint=self._display_endpoint,
            policy=self._circuit_policy,
        )

        self._response: Optional["aiohttp.ClientResponse"] = None  # type: ignore[name-defined]
        self._error: Optional[Exception] = None
        self._retries = 0
        self._last_error_signature: Optional[str] = None
        self._last_duration_seconds: float = 0.0

    async def __aenter__(self):
        if aiohttp is None:  # pragma: no cover
            raise RuntimeError("aiohttp is not available in this environment")

        session = self._session or get_session()

        if not self._breaker.allow_request():
            self._breaker.record_skip()
            note_request_duration(self._service_label, self._endpoint_label, "circuit_open", 0.0)
            try:
                _emit_event(
                    "circuit_open_block",
                    severity="warning",
                    service=self._display_service,
                    endpoint=self._display_endpoint,
                )
            except Exception:
                pass
            raise CircuitOpenError(self._display_service, self._display_endpoint)

        max_attempts = max(1, self._retry_policy.max_attempts)

        for attempt in range(1, max_attempts + 1):
            start = time.perf_counter()
            try:
                response = await session.request(self.method, self.url, **self._request_kwargs)
                duration = time.perf_counter() - start
                self._last_duration_seconds = duration
                status_code = int(getattr(response, "status", 0) or 0)

                if self._slow_ms and (duration * 1000.0) > self._slow_ms:
                    try:
                        logger.warning(
                            "slow_http_async",
                            extra={
                                "method": self.method,
                                "url": self.url,
                                "status": status_code,
                                "ms": round(duration * 1000.0, 1),
                            },
                        )
                    except Exception:
                        pass

                if _should_retry_status(status_code):
                    self._breaker.record_failure()
                    note_request_duration(self._service_label, self._endpoint_label, "http_error", duration)
                    if attempt >= max_attempts:
                        self._response = response
                        self._last_error_signature = "HTTPStatus"
                        try:
                            _emit_event(
                                "external_request_failure",
                                severity="error",
                                service=self._display_service,
                                endpoint=self._display_endpoint,
                                error_signature="HTTPStatus",
                                retries=self._retries,
                            )
                        except Exception:
                            pass
                        break
                    try:
                        await response.release()
                    except Exception:
                        pass
                    self._retries += 1
                    note_retry(self._service_label, self._endpoint_label)
                    await _async_sleep_with_backoff(attempt, self._retry_policy)
                    continue

                self._breaker.record_success()
                note_request_duration(self._service_label, self._endpoint_label, "success", duration)
                self._retries = attempt - 1
                self._response = response
                return response

            except Exception as exc:
                duration = time.perf_counter() - start
                self._last_duration_seconds = duration
                self._error = exc
                self._last_error_signature = type(exc).__name__
                note_request_duration(self._service_label, self._endpoint_label, "exception", duration)
                self._breaker.record_failure()
                if not _is_retryable_exception(exc) or attempt >= max_attempts:
                    break
                self._retries += 1
                note_retry(self._service_label, self._endpoint_label)
                await _async_sleep_with_backoff(attempt, self._retry_policy)
                self._error = None
                continue

        if self._response is not None:
            return self._response

        if self._error is not None:
            try:
                _emit_event(
                    "external_request_failure",
                    severity="error",
                    service=self._display_service,
                    endpoint=self._display_endpoint,
                    error_signature=self._last_error_signature or type(self._error).__name__,
                    retries=self._retries,
                )
            except Exception:
                pass
            raise self._error

        try:
            _emit_event(
                "external_request_failure",
                severity="error",
                service=self._display_service,
                endpoint=self._display_endpoint,
                error_signature="CircuitOpen",
                retries=self._retries,
            )
        except Exception:
            pass
        raise CircuitOpenError(self._display_service, self._display_endpoint)

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        if self._response is not None:
            try:
                await self._response.release()
            except Exception:
                pass
        return False

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


def request(method: str, url: str, **kwargs) -> _ResilientRequestContext:
    session = kwargs.pop("session", None)
    retry_policy = kwargs.pop("retry_policy", None)
    circuit_policy = kwargs.pop("circuit_policy", None)
    service = kwargs.pop("service", None)
    endpoint = kwargs.pop("endpoint", None)
    max_attempts_override = kwargs.pop("max_attempts", None)
    backoff_base_override = kwargs.pop("backoff_base", None)
    backoff_cap_override = kwargs.pop("backoff_cap", None)
    jitter_override = kwargs.pop("jitter", None)

    return _ResilientRequestContext(
        method,
        url,
        session=session,
        service=service,
        endpoint=endpoint,
        retry_policy=retry_policy,
        circuit_policy=circuit_policy,
        max_attempts_override=max_attempts_override,
        backoff_base_override=backoff_base_override,
        backoff_cap_override=backoff_cap_override,
        jitter_override=jitter_override,
        **kwargs,
    )


async def close_session() -> None:
    global _session
    try:
        if _session is not None and not getattr(_session, "closed", False):
            await _session.close()
    finally:
        _session = None
