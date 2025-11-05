from __future__ import annotations

import os
import threading
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

import requests
from requests.adapters import HTTPAdapter

try:
    from observability import emit_event as _emit_event  # type: ignore
except Exception:  # pragma: no cover
    def _emit_event(_event: str, **_fields):  # type: ignore
        return None

try:
    # Retry is optional depending on urllib3 version bundled with requests
    from urllib3.util import Retry  # type: ignore
except Exception:  # pragma: no cover
    Retry = None  # type: ignore


_local = threading.local()
try:
    from observability_instrumentation import start_span, set_current_span_attributes
except Exception:  # pragma: no cover
    class _NoSpan:
        def __enter__(self):  # pragma: no cover
            return None

        def __exit__(self, *_exc):  # pragma: no cover
            return False

    def start_span(*_a, **_k):  # type: ignore
        return _NoSpan()

    def set_current_span_attributes(*_a, **_k):  # type: ignore
        return None


def _extract_retry_count(resp: requests.Response) -> Optional[int]:
    try:
        raw = getattr(resp, "raw", None)
        retries_obj = getattr(raw, "retries", None)
        if retries_obj is None:
            return None
        history = getattr(retries_obj, "history", None)
        if history is None:
            return None
        return int(len(history))
    except Exception:
        return None


def _to_int(env_name: str, default: int) -> int:
    try:
        val = os.getenv(env_name)
        if val is None or val == "":
            return int(default)
        return int(val)
    except Exception:
        return int(default)


def _to_float(env_name: str, default: float) -> float:
    try:
        val = os.getenv(env_name)
        if val is None or val == "":
            return float(default)
        return float(val)
    except Exception:
        return float(default)


class CircuitOpenError(requests.RequestException):
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
    retryable_types = (
        requests.ConnectionError,
        requests.Timeout,
        requests.exceptions.ChunkedEncodingError,
        requests.exceptions.ContentDecodingError,
        requests.exceptions.ProxyError,
        requests.exceptions.SSLError,
    )
    return isinstance(exc, retryable_types)


def _sleep_with_backoff(attempt: int, policy: RetryPolicy) -> None:
    delay = compute_backoff_delay(attempt, policy)
    if delay <= 0:
        return
    try:
        time.sleep(delay)
    except Exception:
        return


def _create_session() -> requests.Session:
    pool_conns = _to_int("REQUESTS_POOL_CONNECTIONS", 20)
    pool_max = _to_int("REQUESTS_POOL_MAXSIZE", 100)
    retries = _to_int("REQUESTS_RETRIES", 2)
    backoff = _to_float("REQUESTS_RETRY_BACKOFF", 0.2)

    sess = requests.Session()
    adapter_kwargs = {"pool_connections": pool_conns, "pool_maxsize": pool_max}

    if Retry is not None:
        status_forcelist = (500, 502, 503, 504)
        allowed = frozenset(["GET", "POST", "PUT", "PATCH", "DELETE"])  # HEAD rarely used here
        try:
            retry = Retry(
                total=retries,
                connect=retries,
                read=0,  # do not retry read timeouts to avoid long hangs
                status=retries,
                backoff_factor=backoff,
                status_forcelist=status_forcelist,
                allowed_methods=allowed,
                raise_on_status=False,
            )
        except TypeError:
            # Older urllib3 uses method_whitelist
            retry = Retry(
                total=retries,
                connect=retries,
                read=0,  # do not retry read timeouts to avoid long hangs
                status=retries,
                backoff_factor=backoff,
                status_forcelist=status_forcelist,
                method_whitelist=allowed,  # type: ignore[arg-type]
                raise_on_status=False,
            )
        adapter_kwargs["max_retries"] = retry

    adapter = HTTPAdapter(**adapter_kwargs)
    sess.mount("https://", adapter)
    sess.mount("http://", adapter)
    return sess


def get_session() -> requests.Session:
    sess: Optional[requests.Session] = getattr(_local, "session", None)
    if sess is None:
        sess = _create_session()
        _local.session = sess
    return sess


def request(method: str, url: str, **kwargs):
    timeout = kwargs.pop("timeout", _to_float("REQUESTS_TIMEOUT", 8.0))
    slow_ms = _to_float("HTTP_SLOW_MS", 0.0)
    logger = logging.getLogger(__name__)

    service_hint = kwargs.pop("service", None)
    endpoint_hint = kwargs.pop("endpoint", None)
    retry_policy_override = kwargs.pop("retry_policy", None)
    circuit_policy_override = kwargs.pop("circuit_policy", None)
    max_attempts_override = kwargs.pop("max_attempts", None)
    backoff_base_override = kwargs.pop("backoff_base", None)
    backoff_cap_override = kwargs.pop("backoff_cap", None)
    jitter_override = kwargs.pop("jitter", None)

    policy = retry_policy_override or DEFAULT_RETRY_POLICY
    if (
        max_attempts_override is not None
        or backoff_base_override is not None
        or backoff_cap_override is not None
        or jitter_override is not None
    ):
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

        policy = RetryPolicy(
            max_attempts=_maybe_int(max_attempts_override, policy.max_attempts),
            backoff_base=_maybe_float(backoff_base_override, policy.backoff_base),
            backoff_cap=_maybe_float(backoff_cap_override, policy.backoff_cap),
            jitter=_maybe_float(jitter_override, policy.jitter),
        )

    circuit_policy: CircuitBreakerPolicy = circuit_policy_override or DEFAULT_CIRCUIT_POLICY

    service_label, endpoint_label, display_service, display_endpoint = resolve_labels(
        url, service_hint, endpoint_hint
    )
    breaker = get_circuit_breaker(
        service_label,
        endpoint_label,
        display_service=display_service,
        display_endpoint=display_endpoint,
        policy=circuit_policy,
    )

    if not breaker.allow_request():
        breaker.record_skip()
        note_request_duration(service_label, endpoint_label, "circuit_open", 0.0)
        try:
            _emit_event(
                "circuit_open_block",
                severity="warning",
                service=display_service,
                endpoint=display_endpoint,
            )
        except Exception:
            pass
        raise CircuitOpenError(display_service, display_endpoint)

    headers = kwargs.get("headers")
    merged_headers = _merge_observability_headers(headers)
    if merged_headers is not None:
        kwargs["headers"] = merged_headers

    span_attrs = {
        "http.method": str(method).upper(),
        "http.url": str(url),
        "timeout": float(timeout),
        "service": service_label,
        "endpoint": endpoint_label,
    }
    span_cm = start_span("http.client", span_attrs)
    span = span_cm.__enter__()
    if span is not None:
        try:
            set_current_span_attributes(
                {
                    "component": "http.sync",
                    "service": service_label,
                    "endpoint": endpoint_label,
                }
            )
        except Exception:
            pass

    error: Exception | None = None
    result: requests.Response | None = None
    retries_performed = 0
    observed_retry_history = 0
    last_status_code: Optional[int] = None
    last_duration_ms: Optional[float] = None
    last_status_label: Optional[str] = None
    last_error_signature: Optional[str] = None

    def _total_retries() -> int:
        return max(0, retries_performed + observed_retry_history)

    max_attempts = max(1, policy.max_attempts)

    try:
        for attempt in range(1, max_attempts + 1):
            t0 = time.perf_counter()
            try:
                resp = get_session().request(method=method, url=url, timeout=timeout, **kwargs)
                duration_seconds = time.perf_counter() - t0
                duration_ms = duration_seconds * 1000.0
                status_code = int(getattr(resp, "status_code", 0) or 0)
                last_status_code = status_code
                last_duration_ms = duration_ms

                history_len = _extract_retry_count(resp)
                if history_len is not None:
                    try:
                        observed_retry_history = max(observed_retry_history, int(history_len))
                    except Exception:
                        observed_retry_history = max(observed_retry_history, 0)

                if slow_ms and slow_ms > 0 and duration_ms > slow_ms:
                    try:
                        logger.warning(
                            "slow_http",
                            extra={
                                "method": str(method).upper(),
                                "url": str(url),
                                "status": status_code,
                                "ms": round(duration_ms, 1),
                            },
                        )
                    except Exception:
                        pass

                if _should_retry_status(status_code):
                    breaker.record_failure()
                    note_request_duration(service_label, endpoint_label, "http_error", duration_seconds)
                    last_status_label = "http_error"
                    if attempt >= max_attempts:
                        last_error_signature = "HTTPStatus"
                        try:
                            _emit_event(
                                "external_request_failure",
                                severity="error",
                                service=display_service,
                                endpoint=display_endpoint,
                                error_signature="HTTPStatus",
                                retries=_total_retries(),
                            )
                        except Exception:
                            pass
                        result = resp
                        break
                    try:
                        resp.close()
                    except Exception:
                        pass
                    retries_performed += 1
                    note_retry(service_label, endpoint_label)
                    _sleep_with_backoff(attempt, policy)
                    continue

                breaker.record_success()
                note_request_duration(service_label, endpoint_label, "success", duration_seconds)
                retries_performed = max(retries_performed, attempt - 1)
                last_status_label = "success"
                result = resp
                break

            except Exception as exc:
                duration_seconds = time.perf_counter() - t0
                duration_ms = duration_seconds * 1000.0
                last_duration_ms = duration_ms
                error = exc
                last_error_signature = type(exc).__name__
                last_status_label = "exception"
                note_request_duration(service_label, endpoint_label, "exception", duration_seconds)
                breaker.record_failure()
                if not _is_retryable_exception(exc) or attempt >= max_attempts:
                    break
                retries_performed += 1
                note_retry(service_label, endpoint_label)
                _sleep_with_backoff(attempt, policy)
                error = None
                continue

        return_value = result
        if return_value is not None:
            if span is not None:
                try:
                    if last_duration_ms is not None:
                        span.set_attribute("duration_ms", float(last_duration_ms))  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    if last_status_code is not None:
                        span.set_attribute("http.status_code", int(last_status_code))  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    retry_count_value = _total_retries()
                    span.set_attribute("retry_count", int(max(0, retry_count_value)))  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    span.set_attribute("status", "ok" if last_status_label == "success" else "error")  # type: ignore[attr-defined]
                except Exception:
                    pass
            return return_value

        if error is not None:
            if span is not None:
                try:
                    if last_duration_ms is not None:
                        span.set_attribute("duration_ms", float(last_duration_ms))  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    span.set_attribute("status", "error")  # type: ignore[attr-defined]
                    if last_error_signature:
                        span.set_attribute("error_signature", last_error_signature)  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    retry_count_value = _total_retries()
                    span.set_attribute("retry_count", int(max(0, retry_count_value)))  # type: ignore[attr-defined]
                except Exception:
                    pass
            try:
                _emit_event(
                    "external_request_failure",
                    severity="error",
                    service=display_service,
                    endpoint=display_endpoint,
                    error_signature=last_error_signature or type(error).__name__,
                    retries=_total_retries(),
                )
            except Exception:
                pass
            raise error

        if span is not None:
            try:
                if last_duration_ms is not None:
                    span.set_attribute("duration_ms", float(last_duration_ms))  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                span.set_attribute("status", "error")  # type: ignore[attr-defined]
                span.set_attribute(
                    "error_signature", last_error_signature or "RetriesExhausted"
                )  # type: ignore[attr-defined]
            except Exception:
                pass
            try:
                retry_count_value = _total_retries()
                span.set_attribute("retry_count", int(max(0, retry_count_value)))  # type: ignore[attr-defined]
            except Exception:
                pass
        error = requests.RequestException(
            f"HTTP request failed after {max_attempts} attempts"
        )
        try:
            _emit_event(
                "external_request_failure",
                severity="error",
                service=display_service,
                endpoint=display_endpoint,
                error_signature=last_error_signature or "RetriesExhausted",
                retries=_total_retries(),
            )
        except Exception:
            pass
        raise error

    finally:
        if error is None:
            span_cm.__exit__(None, None, None)
        else:
            span_cm.__exit__(type(error), error, getattr(error, "__traceback__", None))


def _merge_observability_headers(headers: Any) -> Mapping[str, str] | None:
    base: dict[str, str] = {}
    if headers is None:
        base = {}
    elif isinstance(headers, Mapping):
        for key, value in headers.items():
            if key is None or value is None:
                continue
            try:
                base[str(key)] = str(value)
            except Exception:
                continue
    else:
        try:
            for key, value in dict(headers).items():  # type: ignore[arg-type]
                if key is None or value is None:
                    continue
                base[str(key)] = str(value)
        except Exception:
            base = {}

    try:
        from observability import prepare_outgoing_headers  # type: ignore

        merged = prepare_outgoing_headers(base or None)
    except Exception:
        merged = None

    if merged:
        return merged
    if headers is None:
        # לא נוספו כותרות – נחזיר None כדי לשמור על ברירת המחדל של requests
        return None
    return base or None
