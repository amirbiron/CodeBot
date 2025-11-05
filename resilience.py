"""Shared resilience utilities: retry policy and circuit breaker management."""

from __future__ import annotations

import os
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse
import re

try:  # Structured logging hook (best-effort)
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(_event: str, **_fields):  # type: ignore
        return None

# --- Helper functions to read environment overrides ---
def _env_int(name: str, default: int) -> int:
    try:
        value = os.getenv(name)
        if value not in (None, ""):
            return max(1, int(value))
    except Exception:
        pass
    return default


def _env_float(name: str, default: float) -> float:
    try:
        value = os.getenv(name)
        if value not in (None, ""):
            return max(0.0, float(value))
    except Exception:
        pass
    return default


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    backoff_base: float = 0.25
    backoff_cap: float = 8.0
    jitter: float = 0.5


@dataclass(frozen=True)
class CircuitBreakerPolicy:
    failure_threshold: int = 5
    recovery_seconds: float = 30.0
    half_open_successes: int = 1
    success_window: int = 20


DEFAULT_RETRY_POLICY = RetryPolicy(
    max_attempts=_env_int("HTTP_RESILIENCE_MAX_ATTEMPTS", 3),
    backoff_base=_env_float("HTTP_RESILIENCE_BACKOFF_BASE", 0.25),
    backoff_cap=_env_float("HTTP_RESILIENCE_BACKOFF_MAX", 8.0),
    jitter=_env_float("HTTP_RESILIENCE_JITTER", 0.5),
)

DEFAULT_CIRCUIT_POLICY = CircuitBreakerPolicy(
    failure_threshold=_env_int("CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5),
    recovery_seconds=_env_float("CIRCUIT_BREAKER_RECOVERY_SECONDS", 30.0),
    half_open_successes=_env_int("CIRCUIT_BREAKER_HALF_OPEN_SUCCESS", 1),
    success_window=_env_int("CIRCUIT_BREAKER_SUCCESS_WINDOW", 20),
)


STATE_VALUES = {"closed": 0.0, "half_open": 1.0, "open": 2.0}
_LABEL_CLEAN_RE = re.compile(r"[^a-z0-9._-]+")


def sanitize_label(value: Optional[str], default: str) -> str:
    try:
        raw = (value or "").strip()
        if not raw:
            return default
        lowered = raw.lower().replace(" ", "_")
        cleaned = _LABEL_CLEAN_RE.sub("_", lowered)
        cleaned = cleaned.strip("_-") or default
        return cleaned
    except Exception:
        return default


def resolve_labels(
    url: Optional[str],
    service: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> Tuple[str, str, str, str]:
    """Return sanitized and display labels for service/endpoint."""

    parsed = None
    raw_service = service
    raw_endpoint = endpoint

    if url:
        try:
            parsed = urlparse(url)
        except Exception:
            parsed = None

    if not raw_service:
        host = None
        if parsed is not None:
            host = parsed.hostname
        if host:
            raw_service = host
    if not raw_endpoint:
        path = None
        if parsed is not None:
            path = parsed.path
        path = path or "/"
        segments = [part for part in path.split("/") if part]
        if not segments:
            raw_endpoint = "root"
        else:
            raw_endpoint = "/".join(segments[:2])

    service_label = sanitize_label(raw_service, "external")
    endpoint_label = sanitize_label(raw_endpoint, "generic")

    display_service = raw_service or service_label
    display_endpoint = raw_endpoint or endpoint_label

    return service_label, endpoint_label, display_service, display_endpoint


def compute_backoff_delay(attempt: int, policy: RetryPolicy) -> float:
    attempt_index = max(1, int(attempt))
    exponential = policy.backoff_base * (2 ** (attempt_index - 1))
    capped = min(policy.backoff_cap, exponential)
    jitter = random.random() * policy.jitter if policy.jitter > 0 else 0.0
    delay = max(0.0, capped + jitter)
    return delay


class CircuitBreaker:
    """Thread-safe circuit breaker for outbound dependencies."""

    def __init__(
        self,
        service_label: str,
        endpoint_label: str,
        *,
        policy: CircuitBreakerPolicy,
        display_service: str,
        display_endpoint: str,
    ) -> None:
        self.service = service_label
        self.endpoint = endpoint_label
        self.display_service = display_service
        self.display_endpoint = display_endpoint
        self.policy = policy
        # Use RLock so nested calls (success_rate inside _update_metrics) do not deadlock.
        self._lock = threading.RLock()
        self._state = "closed"
        self._failure_count = 0
        self._success_during_half_open = 0
        self._last_failure_ts = 0.0
        self._recent_results: deque[int] = deque(maxlen=max(1, policy.success_window))
        self._update_metrics()

    def allow_request(self) -> bool:
        with self._lock:
            if self._state == "open":
                if (time.monotonic() - self._last_failure_ts) >= self.policy.recovery_seconds:
                    self._transition("half_open")
                    return True
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._state == "half_open":
                self._success_during_half_open += 1
                if self._success_during_half_open >= self.policy.half_open_successes:
                    self._transition("closed")
            else:
                self._transition("closed")
            self._recent_results.append(1)
            self._update_metrics()

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._recent_results.append(0)
            self._success_during_half_open = 0
            self._last_failure_ts = time.monotonic()
            if self._state == "half_open":
                self._transition("open")
            elif self._failure_count >= self.policy.failure_threshold:
                self._transition("open")
            else:
                self._update_metrics()

    def record_skip(self) -> None:
        """Record that the request was skipped because the circuit is open."""
        with self._lock:
            self._recent_results.append(0)
            self._update_metrics()

    @property
    def state(self) -> str:
        return self._state

    def success_rate(self) -> float:
        with self._lock:
            if not self._recent_results:
                return 1.0 if self._state == "closed" else 0.0
            return sum(self._recent_results) / float(len(self._recent_results))

    def _transition(self, new_state: str) -> None:
        if new_state not in STATE_VALUES:
            new_state = "closed"
        previous = self._state
        self._state = new_state
        if new_state == "closed":
            self._failure_count = 0
            self._success_during_half_open = 0
        if previous != new_state:
            try:
                emit_event(
                    "circuit_state_change",
                    severity="warning" if new_state == "open" else "info",
                    service=self.display_service,
                    endpoint=self.display_endpoint,
                    previous_state=previous,
                    new_state=new_state,
                )
            except Exception:
                pass
        self._update_metrics()

    def _update_metrics(self) -> None:
        funcs = _get_metrics_funcs()
        if not funcs:
            return
        try:
            funcs["set_circuit_state"](self.service, self.endpoint, STATE_VALUES.get(self._state, 0.0))
            funcs["set_circuit_success_rate"](self.service, self.endpoint, self.success_rate())
        except Exception:
            return


_CIRCUITS: Dict[Tuple[str, str], CircuitBreaker] = {}
_CIRCUITS_LOCK = threading.Lock()
_METRICS_FUNCS: Optional[Dict[str, Any]] = None


def _get_metrics_funcs() -> Dict[str, Any]:
    global _METRICS_FUNCS
    if _METRICS_FUNCS:
        return _METRICS_FUNCS
    try:
        from metrics import (
            increment_outbound_retry,
            record_outbound_request_duration,
            set_circuit_state,
            set_circuit_success_rate,
        )
    except Exception:
        return {}
    else:
        _METRICS_FUNCS = {
            "increment_outbound_retry": increment_outbound_retry,
            "record_outbound_request_duration": record_outbound_request_duration,
            "set_circuit_state": set_circuit_state,
            "set_circuit_success_rate": set_circuit_success_rate,
        }
    return _METRICS_FUNCS or {}


def get_circuit_breaker(
    service_label: str,
    endpoint_label: str,
    *,
    display_service: str,
    display_endpoint: str,
    policy: Optional[CircuitBreakerPolicy] = None,
) -> CircuitBreaker:
    key = (service_label, endpoint_label)
    with _CIRCUITS_LOCK:
        breaker = _CIRCUITS.get(key)
        if breaker is None:
            breaker = CircuitBreaker(
                service_label,
                endpoint_label,
                policy=policy or DEFAULT_CIRCUIT_POLICY,
                display_service=display_service,
                display_endpoint=display_endpoint,
            )
            _CIRCUITS[key] = breaker
        return breaker


def note_retry(service: str, endpoint: str) -> None:
    funcs = _get_metrics_funcs()
    if not funcs:
        return
    try:
        funcs["increment_outbound_retry"](service, endpoint)
    except Exception:
        return


def note_request_duration(service: str, endpoint: str, status: str, duration: float) -> None:
    funcs = _get_metrics_funcs()
    if not funcs:
        return
    try:
        funcs["record_outbound_request_duration"](service, endpoint, status, duration)
    except Exception:
        return
