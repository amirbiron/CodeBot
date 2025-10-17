"""
Prometheus metrics primitives and helpers.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Optional
import os
import time as _time
from collections import deque

# Structured event emission (no dependency loop back to metrics)
try:
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover - observability not always available in tests
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None

try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
except Exception:  # pragma: no cover - prometheus optional in some envs
    Counter = Histogram = Gauge = None  # type: ignore
    def generate_latest():  # type: ignore
        return b""
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"  # type: ignore

# Core metrics (names chosen to be generic and reusable)
# Process start time used for uptime derivation
_PROCESS_START_TS: float = _time.time()
_LAST_UPTIME_SCRAPE_TS: float = _PROCESS_START_TS
errors_total = Counter("errors_total", "Total error count", ["code"]) if Counter else None
operation_latency_seconds = (
    Histogram(
        "operation_latency_seconds",
        "Operation latency in seconds",
        ["operation", "repo"],
    )
    if Histogram
    else None
)
telegram_updates_total = (
    Counter(
        "telegram_updates_total",
        "Total Telegram updates processed",
        ["type", "status"],
    )
    if Counter
    else None
)
active_indexes = Gauge("active_indexes", "Active DB indexes") if Gauge else None

# Optional business events counter for high-level analytics
business_events_total = (
    Counter(
        "business_events_total",
        "Count of business-domain events",
        ["metric"],
    )
    if Counter
    else None
)

# --- CodeBot Stage 2: Unified service metrics ---
# Visible in both Flask and AIOHTTP services under /metrics
codebot_active_users_total = Gauge("codebot_active_users_total", "Number of active users recently") if Gauge else None
codebot_failed_requests_total = Counter("codebot_failed_requests_total", "Total failed HTTP requests (status >= 500)") if Counter else None
codebot_avg_response_time_seconds = Gauge("codebot_avg_response_time_seconds", "Smoothed average response time (EWMA) in seconds") if Gauge else None

# Internal helper: total requests for uptime calculation (not externally required but useful)
codebot_requests_total = Counter("codebot_requests_total", "Total HTTP requests processed") if Counter else None

# --- Stage 3 (Observability v3): Advanced derived metrics ---
# Monotonic counter approximating total process uptime seconds.
codebot_uptime_seconds_total = Counter("codebot_uptime_seconds_total", "Total process uptime in seconds") if Counter else None
# Total alerts observed, labeled by source and severity for PromQL filtering.
codebot_alerts_total = (
    Counter(
        "codebot_alerts_total",
        "Total alerts processed (internal + webhook)",
        ["source", "severity"],
    )
    if Counter
    else None
)
# Instantaneous HTTP error rate percentage in the current process.
codebot_error_rate_percent = Gauge("codebot_error_rate_percent", "Instantaneous HTTP error rate percentage") if Gauge else None

# In-memory assistance structures (fail-open, best-effort)
_ACTIVE_USERS: set[int] = set()
_EWMA_ALPHA: float = float(os.getenv("METRICS_EWMA_ALPHA", "0.2"))
_EWMA_RT: float | None = None
_ERR_TIMESTAMPS: deque[float] = deque(maxlen=1000)
_ANOMALY_COOLDOWN_SEC: int = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))
_ANOMALY_LAST_TS: float = 0.0
_ERRS_PER_MIN_THRESHOLD: int = int(os.getenv("ALERT_ERRORS_PER_MINUTE", "20"))
_AVG_RT_THRESHOLD: float = float(os.getenv("ALERT_AVG_RESPONSE_TIME", "2.0"))


@contextmanager
def track_performance(operation: str, labels: Optional[Dict[str, str]] = None):
    start = time.time()
    try:
        yield
    finally:
        if operation_latency_seconds is not None:
            try:
                # בחר רק לייבלים שמוגדרים במטריקה ואל תאפשר דריסה של 'operation'
                allowed = set(getattr(operation_latency_seconds, "_labelnames", []) or [])
                target = {"operation": operation}
                if labels:
                    for k, v in labels.items():
                        if k in allowed and k != "operation":
                            target[k] = v
                # ספק ערכי ברירת מחדל לכל לייבל חסר (למשל repo="") כדי לשמור תאימות לאחור
                for name in allowed:
                    if name not in target:
                        if name == "operation":
                            # כבר סופק לעיל
                            continue
                        # ברירת מחדל: מיתר סמנטיקה, מונע ValueError על חוסר בלייבל
                        target[name] = ""
                operation_latency_seconds.labels(**target).observe(time.time() - start)
            except Exception:
                # avoid breaking app on label mistakes
                pass


def metrics_endpoint_bytes() -> bytes:
    try:
        _update_derived_metrics_on_scrape()
    except Exception:
        # Never break metrics endpoint on derivation issues
        pass
    return generate_latest()


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST


# --- Unified helpers for services instrumentation ---
def note_active_user(user_id: int) -> None:
    """Record that a specific user was active recently, and update the gauge.

    This uses a simple in-memory set per-process. It is a best-effort indicator and
    does not attempt cross-process aggregation. Good enough for basic dashboards/tests.
    """
    try:
        _ACTIVE_USERS.add(int(user_id))
        if codebot_active_users_total is not None:
            codebot_active_users_total.set(len(_ACTIVE_USERS))
    except Exception:
        return


def _update_ewma(duration_seconds: float) -> float:
    global _EWMA_RT
    try:
        if _EWMA_RT is None:
            _EWMA_RT = float(duration_seconds)
        else:
            _EWMA_RT = (_EWMA_ALPHA * float(duration_seconds)) + ((1.0 - _EWMA_ALPHA) * _EWMA_RT)
        if codebot_avg_response_time_seconds is not None:
            codebot_avg_response_time_seconds.set(max(0.0, float(_EWMA_RT)))
        return float(_EWMA_RT)
    except Exception:
        return float(duration_seconds)


def record_request_outcome(status_code: int, duration_seconds: float) -> None:
    """Record a single HTTP request outcome across services.

    - Increments total requests
    - Increments failed requests (status >= 500)
    - Updates EWMA average response time gauge
    - Performs lightweight anomaly detection and emits internal alerts when thresholds are exceeded
    """
    try:
        if codebot_requests_total is not None:
            codebot_requests_total.inc()
        if int(status_code) >= 500 and codebot_failed_requests_total is not None:
            codebot_failed_requests_total.inc()
            _ERR_TIMESTAMPS.append(_time.time())
        _update_ewma(float(duration_seconds))
        _update_error_rate_gauge()
        _maybe_trigger_anomaly()
    except Exception:
        # Fail-open: observability must never crash business logic
        return


def _maybe_trigger_anomaly() -> None:
    """Detect basic anomalies: bursts of errors and high average latency.

    Sends a single alert per cooldown window.
    """
    global _ANOMALY_LAST_TS
    now = _time.time()
    try:
        # Cooldown guard
        if (now - _ANOMALY_LAST_TS) < _ANOMALY_COOLDOWN_SEC:
            return

        # Errors per minute window
        window_start = now - 60.0
        while _ERR_TIMESTAMPS and _ERR_TIMESTAMPS[0] < window_start:
            _ERR_TIMESTAMPS.popleft()
        err_rate = len(_ERR_TIMESTAMPS)

        # Average response time
        avg_rt = float(_EWMA_RT or 0.0)

        breach_msgs: list[str] = []
        if err_rate >= _ERRS_PER_MIN_THRESHOLD and _ERRS_PER_MIN_THRESHOLD > 0:
            breach_msgs.append(f"errors/min >= {err_rate} (threshold {_ERRS_PER_MIN_THRESHOLD})")
        if avg_rt >= _AVG_RT_THRESHOLD and _AVG_RT_THRESHOLD > 0:
            breach_msgs.append(f"avg_rt={avg_rt:.3f}s (threshold {_AVG_RT_THRESHOLD:.3f}s)")

        if not breach_msgs:
            return

        _ANOMALY_LAST_TS = now
        summary = "; ".join(breach_msgs)
        try:
            from internal_alerts import emit_internal_alert  # type: ignore
            emit_internal_alert(name="anomaly_detected", severity="anomaly", summary=summary)
        except Exception:
            # As a fallback, emit a structured event only
            try:
                emit_event("anomaly_detected", severity="anomaly", summary=summary)
            except Exception:
                pass
    except Exception:
        return


def get_uptime_percentage() -> float:
    """Compute uptime percentage based on request counters.

    Uptime ≈ 1 - (failed / total). If counters are unavailable or total==0, return 100.0.
    """
    try:
        total = float(codebot_requests_total._value.get()) if codebot_requests_total is not None else 0.0  # type: ignore[attr-defined]
        failed = float(codebot_failed_requests_total._value.get()) if codebot_failed_requests_total is not None else 0.0  # type: ignore[attr-defined]
    except Exception:
        # Access to internal counter value failed; default to 100%
        return 100.0
    if total <= 0.0:
        return 100.0
    ok_ratio = max(0.0, min(1.0, 1.0 - (failed / total)))
    return round(ok_ratio * 100.0, 2)


def get_process_uptime_seconds() -> float:
    """Return the approximate process uptime in seconds.

    This does not require scraping; based on a monotonic clock since import.
    """
    try:
        return max(0.0, float(_time.time() - _PROCESS_START_TS))
    except Exception:
        return 0.0


def _update_error_rate_gauge() -> None:
    """Recompute and set the error rate gauge based on request counters."""
    try:
        if codebot_error_rate_percent is None:
            return
        try:
            total = float(codebot_requests_total._value.get()) if codebot_requests_total is not None else 0.0  # type: ignore[attr-defined]
            failed = float(codebot_failed_requests_total._value.get()) if codebot_failed_requests_total is not None else 0.0  # type: ignore[attr-defined]
        except Exception:
            total = 0.0
            failed = 0.0
        if total <= 0.0:
            rate = 0.0
        else:
            rate = max(0.0, min(100.0, (failed / total) * 100.0))
        codebot_error_rate_percent.set(rate)
    except Exception:
        return


def _update_derived_metrics_on_scrape() -> None:
    """Update counters/gauges that depend on time at scrape."""
    global _LAST_UPTIME_SCRAPE_TS
    now = _time.time()
    delta: float = 0.0
    try:
        if codebot_uptime_seconds_total is not None:
            delta = max(0.0, float(now - _LAST_UPTIME_SCRAPE_TS))
            if delta > 0.0:
                codebot_uptime_seconds_total.inc(delta)
    except Exception:
        # swallow increment errors but still advance timestamp below
        pass
    finally:
        # Always advance the last scrape timestamp to avoid over-counting next time
        # even if the increment failed above.
        _LAST_UPTIME_SCRAPE_TS = now
    _update_error_rate_gauge()


# --- Business metrics helpers (logged via structlog + optional counter) ---
def track_file_saved(user_id: int, language: str, size_bytes: int) -> None:
    """Record a file_saved business event.

    Uses structured log for rich context and a lightweight Prometheus counter for volume.
    """
    try:
        emit_event(
            "business_metric",
            metric="file_saved",
            user_id=int(user_id),
            language=str(language),
            size_bytes=int(size_bytes),
        )
        if business_events_total is not None:
            business_events_total.labels(metric="file_saved").inc()
    except Exception:
        # Never break business flow on metrics/logging issues
        pass


def track_search_performed(user_id: int, query: str, results_count: int) -> None:
    """Record a search event without logging raw query (privacy by default)."""
    try:
        emit_event(
            "business_metric",
            metric="search",
            user_id=int(user_id),
            query_length=len(str(query or "")),
            results_count=int(results_count),
        )
        if business_events_total is not None:
            business_events_total.labels(metric="search").inc()
    except Exception:
        pass


def track_github_sync(user_id: int, files_count: int, success: bool) -> None:
    """Record a github_sync event (aggregate outcome only)."""
    try:
        emit_event(
            "business_metric",
            metric="github_sync",
            user_id=int(user_id),
            files_count=int(files_count),
            success=bool(success),
        )
        if business_events_total is not None:
            business_events_total.labels(metric="github_sync").inc()
    except Exception:
        pass
