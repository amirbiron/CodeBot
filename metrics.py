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

# Optional DB-backed metrics storage (fail-open stubs if unavailable)
try:  # pragma: no cover
    from monitoring.metrics_storage import (
        enqueue_request_metric as _db_enqueue_request_metric,
        flush as _db_metrics_flush,
    )  # type: ignore
except Exception:  # pragma: no cover
    def _db_enqueue_request_metric(status_code: int, duration_seconds: float, *, request_id: str | None = None, extra=None):  # type: ignore
        return None
    def _db_metrics_flush(force: bool = False) -> None:  # type: ignore
        return None

# Best-effort access to current structlog contextvars for correlation
try:  # pragma: no cover
    from structlog.contextvars import get_contextvars as _get_structlog_ctx  # type: ignore
except Exception:  # pragma: no cover
    def _get_structlog_ctx():  # type: ignore
        return {}

try:
    from prometheus_client import Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST
except Exception:  # pragma: no cover - prometheus optional in some envs
    Counter = Histogram = Gauge = None  # type: ignore
    def generate_latest():  # type: ignore
        return b""
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"  # type: ignore

# Core metrics (names chosen to be generic and reusable)
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

# Observability v6: predicted vs actual incidents counters
predicted_incidents_total = (
    Counter(
        "predicted_incidents_total",
        "Count of predictive incidents detected",
        ["metric"],
    )
    if Counter
    else None
)
actual_incidents_total = (
    Counter(
        "actual_incidents_total",
        "Count of actual critical incidents",
        ["metric"],
    )
    if Counter
    else None
)

# Observability v7: Feedback & Prevention
# Gauge for prediction accuracy over a recent window (e.g., 24h)
prediction_accuracy_percent = (
    Gauge(
        "prediction_accuracy_percent",
        "Prediction accuracy percent over recent window",
    )
    if Gauge
    else None
)

# Counter for prevented incidents over time (labeled by metric)
prevented_incidents_total = (
    Counter(
        "prevented_incidents_total",
        "Count of incidents likely prevented by preemptive actions",
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

# Rate limiting metrics (used by both Flask and Telegram bot)
rate_limit_hits = (
    Counter(
        "rate_limit_hits_total",
        "Total rate limit checks",
        ["source", "scope", "limit", "result"],
    )
    if Counter
    else None
)
rate_limit_blocked = (
    Counter(
        "rate_limit_blocked_total",
        "Total blocked requests by rate limiter",
        ["source", "scope", "limit"],
    )
    if Counter
    else None
)

# --- Phase 3: HTTP-level metrics for SLOs ---
# Standard, well-known Prometheus metric names for HTTP instrumentation.
# Labels kept intentionally small to avoid high cardinality: method, endpoint, status
http_requests_total = (
    Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "endpoint", "status"],
    )
    if Counter
    else None
)
http_request_duration_seconds = (
    Histogram(
        "http_request_duration_seconds",
        "HTTP request duration in seconds",
        ["method", "endpoint"],
    )
    if Histogram
    else None
)

# --- Startup / cold-start metrics ---
# Capture process boot monotonic timestamp as early as metrics import occurs.
_BOOT_T0_MONOTONIC: float = _time.perf_counter()

app_startup_seconds = (
    Gauge(
        "app_startup_seconds",
        "Application startup duration (seconds) from process boot to ready",
    )
    if Gauge
    else None
)

first_request_latency_seconds = (
    Gauge(
        "first_request_latency_seconds",
        "Latency (seconds) from process boot to first completed HTTP request",
    )
    if Gauge
    else None
)

startup_completed = (
    Gauge(
        "startup_completed",
        "1 if application finished startup/preload, else 0",
    )
    if Gauge
    else None
)

# Dependency initialization timing (e.g., mongodb, redis, templates)
dependency_init_seconds = (
    Histogram(
        "dependency_init_seconds",
        "Initialization time for external/internal dependencies",
        ["dependency"],
    )
    if Histogram
    else None
)

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
        _maybe_trigger_anomaly()
        # Dual-write: enqueue request metrics to DB (best-effort, batched)
        try:
            ctx = _get_structlog_ctx() or {}
            req_id = ctx.get("request_id") if isinstance(ctx, dict) else None
            rid = str(req_id) if req_id else None
            _db_enqueue_request_metric(int(status_code), float(duration_seconds), request_id=rid)
        except Exception:
            pass
        # Feed adaptive thresholds module (best-effort)
        try:
            from alert_manager import note_request, check_and_emit_alerts  # type: ignore
            note_request(int(status_code), float(duration_seconds))
            # Evaluate breaches occasionally (cheap; internal cooldowns apply)
            check_and_emit_alerts()
        except Exception:
            pass
        # Feed Predictive Health Engine (best-effort, throttled internally)
        try:
            from predictive_engine import note_observation, maybe_recompute_and_preempt  # type: ignore
            # Allow predictive engine to sample current snapshot without explicit values
            note_observation()
            maybe_recompute_and_preempt()
        except Exception:
            pass
    except Exception:
        # Fail-open: observability must never crash business logic
        return


def _normalize_endpoint(value: str | None) -> str:
    """Return a low-cardinality endpoint label.

    Prefer Flask endpoint name (function name), fall back to path prefix buckets.
    """
    try:
        v = (value or "").strip()
        if not v:
            return "unknown"
        # Flask endpoint names do not include parameters and are stable
        return v.replace(" ", "_")[:120]
    except Exception:
        return "unknown"


def record_http_request(
    method: str,
    endpoint: str | None,
    status_code: int,
    duration_seconds: float,
) -> None:
    """Record HTTP request metrics for SLO calculations.

    - Increments ``http_requests_total{method,endpoint,status}``
    - Observes ``http_request_duration_seconds{method,endpoint}``

    This function is best-effort and never raises.
    """
    try:
        ep = _normalize_endpoint(endpoint)
        m = (method or "").upper() or "GET"
        status = str(int(status_code))
        if http_requests_total is not None:
            try:
                http_requests_total.labels(m, ep, status).inc()
            except Exception:
                pass
        if http_request_duration_seconds is not None:
            try:
                http_request_duration_seconds.labels(m, ep).observe(max(0.0, float(duration_seconds)))
            except Exception:
                pass
    except Exception:
        return


# --- Startup helpers ---
def get_boot_monotonic() -> float:
    """Return the process boot monotonic timestamp captured by metrics import."""
    return float(_BOOT_T0_MONOTONIC)


def mark_startup_complete() -> None:
    """Mark startup as complete and set app_startup_seconds/startup_completed gauges.

    Safe no-op if metrics are unavailable.
    """
    try:
        if app_startup_seconds is not None:
            try:
                app_startup_seconds.set(max(0.0, float(_time.perf_counter() - _BOOT_T0_MONOTONIC)))
            except Exception:
                pass
        if startup_completed is not None:
            try:
                startup_completed.set(1.0)
            except Exception:
                pass
    except Exception:
        return


def note_first_request_latency(duration_seconds: float | None = None) -> None:
    """Record the latency from process boot to first completed HTTP request.

    If duration_seconds is None, compute against get_boot_monotonic().
    """
    try:
        value = float(duration_seconds) if duration_seconds is not None else float(_time.perf_counter() - _BOOT_T0_MONOTONIC)
        if first_request_latency_seconds is not None:
            first_request_latency_seconds.set(max(0.0, value))
    except Exception:
        return


def get_process_uptime_seconds() -> float:
    """Return approximate process uptime in seconds using perf_counter baseline.

    This is computed as ``perf_counter() - get_boot_monotonic()`` to yield elapsed
    time since the baseline captured at import. It is best-effort and monotonic.
    """
    try:
        return max(0.0, float(_time.perf_counter() - _BOOT_T0_MONOTONIC))
    except Exception:
        return 0.0


def record_dependency_init(dependency: str, duration_seconds: float) -> None:
    """Observe initialization time for a named dependency (Histogram)."""
    try:
        if dependency_init_seconds is not None:
            dependency_init_seconds.labels(str(dependency)).observe(max(0.0, float(duration_seconds)))
    except Exception:
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


# --- Adaptive thresholds gauges (optional; consumed by alert_manager) ---
try:  # define lazily to keep import-time optional
    adaptive_error_rate_threshold_percent = Gauge(
        "adaptive_error_rate_threshold_percent",
        "Adaptive threshold for error rate percent (mean+3*sigma over 3h)",
    ) if Gauge else None
    adaptive_latency_threshold_seconds = Gauge(
        "adaptive_latency_threshold_seconds",
        "Adaptive threshold for average latency seconds (mean+3*sigma over 3h)",
    ) if Gauge else None
    adaptive_current_error_rate_percent = Gauge(
        "adaptive_current_error_rate_percent",
        "Current error rate percent (rolling 5m)",
    ) if Gauge else None
    adaptive_current_latency_avg_seconds = Gauge(
        "adaptive_current_latency_avg_seconds",
        "Current average latency seconds (rolling 5m)",
    ) if Gauge else None
except Exception:
    adaptive_error_rate_threshold_percent = None  # type: ignore
    adaptive_latency_threshold_seconds = None  # type: ignore
    adaptive_current_error_rate_percent = None  # type: ignore
    adaptive_current_latency_avg_seconds = None  # type: ignore


def set_adaptive_observability_gauges(
    *,
    error_rate_threshold_percent: Optional[float] = None,
    latency_threshold_seconds: Optional[float] = None,
    current_error_rate_percent: Optional[float] = None,
    current_latency_avg_seconds: Optional[float] = None,
) -> None:
    """Update adaptive observability gauges. No-ops if gauges unavailable."""
    try:
        if adaptive_error_rate_threshold_percent is not None and error_rate_threshold_percent is not None:
            adaptive_error_rate_threshold_percent.set(max(0.0, float(error_rate_threshold_percent)))
        if adaptive_latency_threshold_seconds is not None and latency_threshold_seconds is not None:
            adaptive_latency_threshold_seconds.set(max(0.0, float(latency_threshold_seconds)))
        if adaptive_current_error_rate_percent is not None and current_error_rate_percent is not None:
            adaptive_current_error_rate_percent.set(max(0.0, float(current_error_rate_percent)))
        if adaptive_current_latency_avg_seconds is not None and current_latency_avg_seconds is not None:
            adaptive_current_latency_avg_seconds.set(max(0.0, float(current_latency_avg_seconds)))
    except Exception:
        return


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
