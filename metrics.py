"""
Prometheus metrics primitives and helpers.
"""
from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, Optional, List, Tuple
import os
import threading
import time as _time
from collections import deque
from urllib.parse import urlparse

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

# Logger for structured warnings around anomalies
logger = logging.getLogger(__name__)

# --- OpenTelemetry metrics (best-effort, fail-open) ---
_OTEL_HTTP_LOCK = threading.Lock()
_OTEL_HTTP_INIT_DONE: bool = False
_OTEL_HTTP_REQUESTS_COUNTER = None
_OTEL_HTTP_DURATION_HIST = None
_OTEL_HTTP_QUEUE_DELAY_HIST = None


def _otel_init_http_metrics():
    """Best-effort init of OpenTelemetry HTTP instruments (idempotent)."""
    global _OTEL_HTTP_INIT_DONE, _OTEL_HTTP_REQUESTS_COUNTER, _OTEL_HTTP_DURATION_HIST, _OTEL_HTTP_QUEUE_DELAY_HIST
    if _OTEL_HTTP_INIT_DONE:
        return
    with _OTEL_HTTP_LOCK:
        if _OTEL_HTTP_INIT_DONE:
            return
        try:
            from opentelemetry import metrics as _otel_metrics  # type: ignore
        except Exception:
            _OTEL_HTTP_INIT_DONE = True
            return
        try:
            meter = _otel_metrics.get_meter("codebot.metrics")
        except Exception:
            _OTEL_HTTP_INIT_DONE = True
            return
        try:
            _OTEL_HTTP_REQUESTS_COUNTER = meter.create_counter(
                "codebot.http.server.requests",
                description="Total incoming request outcomes (best-effort)",
                unit="1",
            )
        except Exception:
            _OTEL_HTTP_REQUESTS_COUNTER = None
        try:
            _OTEL_HTTP_DURATION_HIST = meter.create_histogram(
                "codebot.http.server.duration",
                description="Incoming request duration in seconds (best-effort)",
                unit="s",
            )
        except Exception:
            _OTEL_HTTP_DURATION_HIST = None
        try:
            _OTEL_HTTP_QUEUE_DELAY_HIST = meter.create_histogram(
                "codebot.http.server.queue_delay",
                description="Incoming request queue delay in seconds (best-effort)",
                unit="s",
            )
        except Exception:
            _OTEL_HTTP_QUEUE_DELAY_HIST = None
        _OTEL_HTTP_INIT_DONE = True


def _otel_record_http_outcome(
    *,
    status_code: int,
    duration_seconds: float,
    endpoint: str,
    method: str,
    source: str | None = None,
    status_bucket: str | None = None,
    queue_delay_ms: int | None = None,
) -> None:
    """Record a single request outcome to OpenTelemetry metrics (never raises)."""
    try:
        _otel_init_http_metrics()
        attrs: dict[str, object] = {
            "http.method": (method or "").upper() or "GET",
            "http.route": str(endpoint or "unknown")[:160],
            "http.status_code": int(status_code),
        }
        if source:
            attrs["codebot.source"] = str(source)[:64]
        if status_bucket:
            attrs["codebot.status_bucket"] = str(status_bucket)[:16]
        if _OTEL_HTTP_REQUESTS_COUNTER is not None:
            try:
                _OTEL_HTTP_REQUESTS_COUNTER.add(1, attrs)  # type: ignore[attr-defined]
            except Exception:
                pass
        if _OTEL_HTTP_DURATION_HIST is not None:
            try:
                _OTEL_HTTP_DURATION_HIST.record(max(0.0, float(duration_seconds)), attrs)  # type: ignore[attr-defined]
            except Exception:
                pass
        if queue_delay_ms is not None and _OTEL_HTTP_QUEUE_DELAY_HIST is not None:
            try:
                _OTEL_HTTP_QUEUE_DELAY_HIST.record(max(0.0, float(queue_delay_ms)) / 1000.0, attrs)  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        return

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

# Health check gauges exposed via /metrics
health_mongo_status = (
    Gauge("health_mongo_status", "1 when MongoDB is connected, else 0") if Gauge else None
)
health_ping_ms = (
    Gauge("health_ping_ms", "MongoDB ping latency reported by /healthz (milliseconds)")
    if Gauge
    else None
)
health_indexes_total = (
    Gauge("health_indexes_total", "Healthy index count reported by /healthz") if Gauge else None
)
health_latency_ewma = (
    Gauge("health_latency_ewma", "Application EWMA latency in milliseconds reported by /healthz")
    if Gauge
    else None
)

# Startup metrics (milliseconds) to track cold-start regressions
startup_stage_duration_ms = (
    Gauge(
        "startup_stage_duration_ms",
        "Duration of individual startup stages in milliseconds",
        ["stage"],
    )
    if Gauge
    else None
)
startup_total_duration_ms = (
    Gauge("startup_total_duration_ms", "Total application startup duration in milliseconds")
    if Gauge
    else None
)

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
codebot_active_requests_total = Gauge("codebot_active_requests_total", "Number of in-flight HTTP requests") if Gauge else None

# Internal helper: total requests for uptime calculation (not externally required but useful)
codebot_requests_total = Counter("codebot_requests_total", "Total HTTP requests processed") if Counter else None
codebot_external_error_rate_percent = (
    Gauge(
        "codebot_external_error_rate_percent",
        "Rolling 5m error rate percent for traffic attributed to external services",
    )
    if Gauge
    else None
)

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

# Queue delay (time from ingress to app handling) as measured from X-Request-Start/X-Queue-Start.
http_request_queue_duration_seconds = (
    Histogram(
        "http_request_queue_duration_seconds",
        "HTTP request queue delay in seconds",
        ["method", "endpoint"],
    )
    if Histogram
    else None
)

# --- Stage 4: outbound dependency resilience metrics ---
outbound_request_duration_seconds = (
    Histogram(
        "request_duration_seconds",
        "Outbound request duration in seconds",
        ["service", "endpoint", "status"],
    )
    if Histogram
    else None
)

outbound_retries_total = (
    Counter(
        "retries_total",
        "Total outbound request retries",
        ["service", "endpoint"],
    )
    if Counter
    else None
)

circuit_state_metric = (
    Gauge(
        "circuit_state",
        "Circuit breaker state (0=closed,1=half_open,2=open)",
        ["service", "endpoint"],
    )
    if Gauge
    else None
)

circuit_success_rate_metric = (
    Gauge(
        "circuit_success_rate",
        "Recent success rate for outbound requests (0-1)",
        ["service", "endpoint"],
    )
    if Gauge
    else None
)

# --- Stage 6: unified handler/command/db metrics ---
codebot_handler_requests_total = (
    Counter(
        "codebot_handler_requests_total",
        "Total web handler invocations",
        ["handler", "status", "cache_hit"],
    )
    if Counter
    else None
)

codebot_handler_latency_seconds = (
    Histogram(
        "codebot_handler_latency_seconds",
        "Web handler latency in seconds",
        ["handler", "status", "cache_hit"],
    )
    if Histogram
    else None
)

codebot_command_requests_total = (
    Counter(
        "codebot_command_requests_total",
        "Total Telegram command executions",
        ["command", "status", "cache_hit"],
    )
    if Counter
    else None
)

codebot_command_latency_seconds = (
    Histogram(
        "codebot_command_latency_seconds",
        "Telegram command latency in seconds",
        ["command", "status", "cache_hit"],
    )
    if Histogram
    else None
)

codebot_db_requests_total = (
    Counter(
        "codebot_db_requests_total",
        "Total database operations",
        ["operation", "status"],
    )
    if Counter
    else None
)

codebot_db_latency_seconds = (
    Histogram(
        "codebot_db_latency_seconds",
        "Database operation latency in seconds",
        ["operation", "status"],
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
_ACTIVE_REQUESTS: int = 0
_ACTIVE_REQUESTS_LOCK = threading.Lock()
_EWMA_ALPHA: float = float(os.getenv("METRICS_EWMA_ALPHA", "0.2"))
_EWMA_RT: float | None = None
_HTTP_SAMPLE_BUFFER = int(os.getenv("HTTP_SAMPLE_BUFFER", "2000"))
_HTTP_REQUEST_SAMPLES: deque[Tuple[float, str, str, float, int]] = deque(maxlen=max(100, _HTTP_SAMPLE_BUFFER))
_HTTP_SAMPLES_LOCK = threading.Lock()
_HTTP_SAMPLE_RETENTION_SECONDS: int = int(os.getenv("HTTP_SAMPLE_RETENTION_SECONDS", "600"))
_ERROR_HISTORY_SECONDS: int = max(60, int(os.getenv("ERROR_HISTORY_SECONDS", "600")))
_ERROR_HISTORY_MAX_SAMPLES: int = int(os.getenv("ERROR_HISTORY_MAX_SAMPLES", "2000"))
_ERR_TIMESTAMPS: deque[float] = deque(maxlen=max(200, _ERROR_HISTORY_MAX_SAMPLES))
_ERR_TIMESTAMPS_LOCK = threading.Lock()
_ANOMALY_COOLDOWN_SEC: int = int(os.getenv("ALERT_COOLDOWN_SECONDS", "300"))
_ANOMALY_LAST_TS: float = 0.0
_ERRS_PER_MIN_THRESHOLD: int = int(os.getenv("ALERT_ERRORS_PER_MINUTE", "20"))
_AVG_RT_THRESHOLD: float = float(os.getenv("ALERT_AVG_RESPONSE_TIME", "3.0"))
_DEPLOY_AVG_RT_THRESHOLD: float = float(os.getenv("ALERT_AVG_RESPONSE_TIME_DEPLOY", "10.0"))
_DEPLOY_GRACE_PERIOD_SECONDS: int = int(os.getenv("DEPLOY_GRACE_PERIOD_SECONDS", "120"))
_LAST_DEPLOYMENT_TS: float | None = None

# Endpoints to exclude from EWMA + slow-endpoint sampling (but still record Prometheus metrics).
# IMPORTANT: do not import `config.py` here (it has required settings and can break docs/tests).
_ANOMALY_IGNORE_ENDPOINTS_ENV: str = "ANOMALY_IGNORE_ENDPOINTS"
_ANOMALY_IGNORE_ENDPOINTS_RAW: str | None = None
_ANOMALY_IGNORE_ENDPOINTS_SET: set[str] = set()
_ANOMALY_IGNORE_ENDPOINTS_LOCK = threading.Lock()


def _normalize_anomaly_ignore_token(value: Any) -> str:
    """Normalize a configured ignore token (path or endpoint name)."""
    try:
        s = str(value or "").strip()
    except Exception:
        return ""
    if not s:
        return ""
    # Allow full URL values by extracting the path part
    if "://" in s:
        try:
            parsed = urlparse(s)
            if parsed and parsed.path:
                s = parsed.path
        except Exception:
            pass
    # Drop query/hash to match request.path semantics
    try:
        s = s.split("?", 1)[0].split("#", 1)[0].strip()
    except Exception:
        pass
    if not s:
        return ""
    # Normalize trailing slash for paths (keep "/" as-is)
    if s.startswith("/") and len(s) > 1:
        s = s.rstrip("/")
    return s


def _parse_anomaly_ignore_endpoints(raw: str | None) -> set[str]:
    try:
        text = str(raw or "").strip()
    except Exception:
        text = ""
    if not text:
        return set()

    tokens: list[Any]
    if text.startswith("["):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                tokens = list(parsed)
            else:
                tokens = [parsed]
        except Exception:
            tokens = [p.strip() for p in text.split(",")]
    else:
        tokens = [p.strip() for p in text.split(",")]

    out: set[str] = set()
    for token in tokens:
        normalized = _normalize_anomaly_ignore_token(token)
        if normalized:
            out.add(normalized)
    return out


def _get_anomaly_ignore_endpoints() -> set[str]:
    """Return the current ignore set, reloading if env changed (thread-safe)."""
    global _ANOMALY_IGNORE_ENDPOINTS_RAW, _ANOMALY_IGNORE_ENDPOINTS_SET
    raw = os.getenv(_ANOMALY_IGNORE_ENDPOINTS_ENV, "") or ""
    if _ANOMALY_IGNORE_ENDPOINTS_RAW is not None and raw == _ANOMALY_IGNORE_ENDPOINTS_RAW:
        return _ANOMALY_IGNORE_ENDPOINTS_SET

    with _ANOMALY_IGNORE_ENDPOINTS_LOCK:
        raw2 = os.getenv(_ANOMALY_IGNORE_ENDPOINTS_ENV, "") or ""
        if _ANOMALY_IGNORE_ENDPOINTS_RAW is not None and raw2 == _ANOMALY_IGNORE_ENDPOINTS_RAW:
            return _ANOMALY_IGNORE_ENDPOINTS_SET
        _ANOMALY_IGNORE_ENDPOINTS_RAW = raw2
        _ANOMALY_IGNORE_ENDPOINTS_SET = _parse_anomaly_ignore_endpoints(raw2)
        return _ANOMALY_IGNORE_ENDPOINTS_SET


def _is_anomaly_ignored(*, path: str | None = None, endpoint: str | None = None) -> bool:
    """True if the request should be ignored for EWMA/slow-endpoint sampling."""
    ignore_set = _get_anomaly_ignore_endpoints()
    if not ignore_set:
        return False
    for candidate in (path, endpoint):
        normalized = _normalize_anomaly_ignore_token(candidate)
        if normalized and normalized in ignore_set:
            return True
    return False


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


def _update_active_requests_gauge(value: int) -> None:
    try:
        if codebot_active_requests_total is not None:
            codebot_active_requests_total.set(max(0.0, float(value)))
    except Exception:
        pass


def note_request_started() -> None:
    """Increment the in-flight requests gauge (best-effort)."""
    global _ACTIVE_REQUESTS
    try:
        with _ACTIVE_REQUESTS_LOCK:
            _ACTIVE_REQUESTS += 1
            current = _ACTIVE_REQUESTS
        _update_active_requests_gauge(current)
    except Exception:
        return


def note_request_finished() -> None:
    """Decrement the in-flight requests gauge (never negative)."""
    global _ACTIVE_REQUESTS
    try:
        with _ACTIVE_REQUESTS_LOCK:
            _ACTIVE_REQUESTS = max(0, _ACTIVE_REQUESTS - 1)
            current = _ACTIVE_REQUESTS
        _update_active_requests_gauge(current)
    except Exception:
        return


def get_active_requests_count() -> int:
    """Return the current in-flight request count (best-effort)."""
    try:
        with _ACTIVE_REQUESTS_LOCK:
            return max(0, int(_ACTIVE_REQUESTS))
    except Exception:
        return 0


def get_current_memory_usage() -> float:
    """Return current process RSS in MB (best-effort)."""
    try:
        import psutil  # type: ignore

        process = psutil.Process()
        return float(process.memory_info().rss) / 1024.0 / 1024.0
    except Exception:
        return 0.0


def _record_error_timestamp(ts: float | None = None) -> None:
    """Record an error timestamp with retention and max sample cap."""
    try:
        value = float(ts if ts is not None else _time.time())
    except Exception:
        value = _time.time()
    cutoff = value - float(_ERROR_HISTORY_SECONDS)
    try:
        with _ERR_TIMESTAMPS_LOCK:
            _ERR_TIMESTAMPS.append(value)
            while _ERR_TIMESTAMPS and _ERR_TIMESTAMPS[0] < cutoff:
                _ERR_TIMESTAMPS.popleft()
    except Exception:
        return


def get_recent_errors_count(minutes: int = 5) -> int:
    """Return the number of 5xx errors recorded in the last X minutes."""
    if minutes is None:
        minutes = 5
    try:
        window = max(0, int(minutes)) * 60
        if window <= 0:
            return 0
        cutoff = _time.time() - float(window)
    except Exception:
        return 0
    try:
        with _ERR_TIMESTAMPS_LOCK:
            return sum(1 for ts in _ERR_TIMESTAMPS if ts >= cutoff)
    except Exception:
        return 0


def _note_http_request_sample(
    method: str,
    endpoint: str,
    status_code: int,
    duration_seconds: float,
    *,
    ts: float | None = None,
) -> None:
    """Store a lightweight sample for slow-endpoint summaries (best-effort)."""
    try:
        timestamp = float(ts if ts is not None else _time.time())
        sample = (
            timestamp,
            (method or "").upper() or "GET",
            endpoint or "unknown",
            max(0.0, float(duration_seconds)),
            int(status_code),
        )
    except Exception:
        return
    cutoff = timestamp - float(max(60, _HTTP_SAMPLE_RETENTION_SECONDS))
    try:
        with _HTTP_SAMPLES_LOCK:
            _HTTP_REQUEST_SAMPLES.append(sample)
            while _HTTP_REQUEST_SAMPLES and _HTTP_REQUEST_SAMPLES[0][0] < cutoff:
                _HTTP_REQUEST_SAMPLES.popleft()
    except Exception:
        return


def _recent_http_samples(window_seconds: Optional[int] = None) -> List[Tuple[float, str, str, float, int]]:
    try:
        with _HTTP_SAMPLES_LOCK:
            samples = list(_HTTP_REQUEST_SAMPLES)
    except Exception:
        return []
    if not samples:
        return []
    try:
        window = int(window_seconds) if window_seconds is not None else _HTTP_SAMPLE_RETENTION_SECONDS
        cutoff = _time.time() - float(max(1, window))
    except Exception:
        cutoff = _time.time() - float(_HTTP_SAMPLE_RETENTION_SECONDS)
    return [sample for sample in samples if sample[0] >= cutoff]


def get_top_slow_endpoints(limit: int = 5, window_seconds: Optional[int] = None) -> List[Dict[str, Any]]:
    """Return the slowest endpoints observed recently (best-effort)."""
    try:
        max_items = max(0, int(limit))
    except Exception:
        max_items = 5
    if max_items <= 0:
        return []

    samples = _recent_http_samples(window_seconds)
    stats: Dict[Tuple[str, str], Dict[str, float]] = {}
    for _ts, method, endpoint, duration, _status in samples:
        key = (method or "GET", endpoint or "unknown")
        data = stats.setdefault(key, {"count": 0.0, "sum": 0.0, "max": 0.0})
        data["count"] += 1.0
        data["sum"] += float(duration)
        data["max"] = max(data["max"], float(duration))

    results: List[Dict[str, Any]] = []
    for (method, endpoint), data in stats.items():
        count = max(1.0, data["count"])
        avg = data["sum"] / count
        results.append(
            {
                "method": method,
                "endpoint": endpoint,
                "count": int(count),
                "avg_duration": float(avg),
                "max_duration": float(data["max"]),
            }
        )

    results.sort(key=lambda item: item.get("max_duration", 0.0), reverse=True)
    return results[:max_items]


def get_slowest_endpoint() -> str:
    """Return a formatted string describing the slowest endpoint recently seen."""
    top = get_top_slow_endpoints(limit=1)
    if not top:
        return "unknown"
    entry = top[0]
    try:
        method = str(entry.get("method", "GET"))
        endpoint = str(entry.get("endpoint", "unknown"))
        max_dur = float(entry.get("max_duration", 0.0))
        return f"{method} {endpoint} ({max_dur:.3f}s)"
    except Exception:
        return "unknown"


def _emit_deployment_alert(summary: str, *, name: str) -> None:
    try:
        from internal_alerts import emit_internal_alert  # type: ignore

        emit_internal_alert(name=name, severity="info", summary=str(summary))
    except Exception:
        try:
            emit_event(name, severity="info", summary=str(summary))
        except Exception:
            pass


def note_deployment_started(summary: str = "Service starting up") -> None:
    """Mark the start of a deployment and emit an informational alert."""
    global _LAST_DEPLOYMENT_TS
    try:
        _LAST_DEPLOYMENT_TS = _time.time()
    except Exception:
        _LAST_DEPLOYMENT_TS = None
    _emit_deployment_alert(summary, name="deployment_event")


def note_deployment_shutdown(summary: str = "Service shutting down") -> None:
    """Emit a shutdown deployment event (does not reset latency grace period)."""
    _emit_deployment_alert(summary, name="deployment_event")


def _current_latency_threshold(now_ts: float) -> float:
    """Return the dynamic latency threshold depending on deploy grace period."""
    try:
        if (
            _DEPLOY_GRACE_PERIOD_SECONDS > 0
            and _LAST_DEPLOYMENT_TS is not None
            and (now_ts - float(_LAST_DEPLOYMENT_TS)) < float(_DEPLOY_GRACE_PERIOD_SECONDS)
            and _DEPLOY_AVG_RT_THRESHOLD > 0
        ):
            return float(_DEPLOY_AVG_RT_THRESHOLD)
    except Exception:
        pass
    return float(_AVG_RT_THRESHOLD)


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


def get_avg_response_time_seconds() -> float:
    """Return the smoothed average HTTP response time (seconds)."""
    try:
        return max(0.0, float(_EWMA_RT or 0.0))
    except Exception:
        return 0.0


def _status_label_from_code(status_code: int | None, override: str | None = None) -> str:
    try:
        if override:
            return _normalize_metric_label(str(override), "unknown_status")
    except Exception:
        pass
    try:
        if status_code is None:
            return "unknown"
        bucket = int(status_code) // 100
        if bucket == 0:
            return _normalize_metric_label(str(status_code), "unknown")
        return f"{bucket}xx"
    except Exception:
        return "unknown"


def _cache_hit_label(cache_hit: bool | str | None) -> str:
    try:
        if isinstance(cache_hit, str):
            value = cache_hit.strip().lower()
            if value in {"hit", "miss", "warm", "cold", "partial", "unknown"}:
                return value
            if value in {"true", "yes", "1"}:
                return "hit"
            if value in {"false", "no", "0"}:
                return "miss"
            return "unknown"
        if cache_hit is True:
            return "hit"
        if cache_hit is False:
            return "miss"
    except Exception:
        return "unknown"
    return "unknown"


def _attach_source(name: str | None, source: str | None, *, default: str) -> str:
    base = _normalize_metric_label(name, default)
    try:
        src = (source or "").strip()
        if not src:
            return base
        prefixed = f"{src}:{base}"
        return _normalize_metric_label(prefixed, default)
    except Exception:
        return base


def _load_external_service_keywords() -> set[str]:
    defaults = {
        "uptime",
        "uptimerobot",
        "uptime_robot",
        "betteruptime",
        "statuscake",
        "pingdom",
        "external_monitor",
        "github api",
        "github_api",
    }
    extra = os.getenv("ALERT_EXTERNAL_SERVICES", "")
    extra_tokens = {token.strip().lower() for token in str(extra or "").split(",") if token.strip()}
    return {token for token in defaults.union(extra_tokens) if token}


_EXTERNAL_SERVICE_KEYWORDS = _load_external_service_keywords()


def _matches_external_service_keyword(value: Optional[str]) -> bool:
    try:
        text = str(value or "").strip().lower()
    except Exception:
        text = ""
    if not text:
        return False
    for keyword in _EXTERNAL_SERVICE_KEYWORDS:
        if keyword in text:
            return True
    return False


def _classify_request_source(
    raw_source: Optional[str],
    handler: Optional[str],
    command: Optional[str],
    path: Optional[str],
) -> tuple[str, Optional[str]]:
    try:
        source_text = str(raw_source or "").strip()
    except Exception:
        source_text = ""
    component: Optional[str] = None
    origin: Optional[str] = None
    lowered = source_text.lower()
    if lowered in {"internal", "external"}:
        origin = lowered
    elif ":" in source_text:
        prefix, suffix = source_text.split(":", 1)
        prefix_clean = prefix.strip().lower()
        if prefix_clean in {"internal", "external"}:
            origin = prefix_clean
            component = suffix.strip() or None
        else:
            component = source_text or None
    elif source_text:
        component = source_text

    if origin is None:
        for candidate in (component, handler, command, path):
            if _matches_external_service_keyword(candidate):
                origin = "external"
                if not component and candidate:
                    candidate_text = str(candidate).strip()
                    component = candidate_text or component
                break

    if origin not in {"internal", "external"}:
        origin = "internal"
    return origin, (component or None)


def record_request_outcome(
    status_code: int,
    duration_seconds: float,
    *,
    source: str | None = None,
    handler: str | None = None,
    command: str | None = None,
    cache_hit: bool | str | None = None,
    status_label: str | None = None,
    method: str | None = None,
    path: str | None = None,
) -> None:
    """Record a single HTTP request outcome across services.

    - Increments total requests
    - Increments failed requests (status >= 500)
    - Updates EWMA average response time gauge
    - Performs lightweight anomaly detection and emits internal alerts when thresholds are exceeded
    """
    try:
        status_int = int(status_code)
    except Exception:
        status_int = 0
    cache_label = _cache_hit_label(cache_hit)
    status_bucket = _status_label_from_code(status_int, status_label)
    source_origin = "internal"
    component_label: Optional[str] = None
    source_raw_text = ""

    try:
        if codebot_requests_total is not None:
            codebot_requests_total.inc()
        if status_int >= 500:
            if codebot_failed_requests_total is not None:
                codebot_failed_requests_total.inc()
            _record_error_timestamp()
        # Allow excluding specific paths (e.g., observability heavy endpoints) from EWMA.
        # Still record core request counters + error timestamps for history.
        if not _is_anomaly_ignored(path=path):
            _update_ewma(float(duration_seconds))
        _maybe_trigger_anomaly()
        # OpenTelemetry: record request outcome via counters/histograms (best-effort).
        # NOTE: We intentionally do NOT persist per-request metrics to MongoDB anymore
        # (legacy metrics_storage caused DB overload and was disabled in production).
        ctx_dict: Dict[str, Any] = {}
        rid: Optional[str] = None
        queue_delay_ms: Optional[int] = None
        command_label = ""
        handler_text = ""
        method_text = ""
        path_text = ""
        try:
            ctx_raw = _get_structlog_ctx() or {}
            ctx_dict = ctx_raw if isinstance(ctx_raw, dict) else {}
            req_id = ctx_dict.get("request_id")
            rid = str(req_id) if req_id else None
            # Queue delay (milliseconds) is bound by the webserver middleware (X-Queue-Start/X-Request-Start).
            # Keep it best-effort and numeric-only to avoid polluting downstream storage.
            for key in ("queue_delay", "queue_delay_ms", "queue_time_ms", "queue_ms"):
                try:
                    raw_q = ctx_dict.get(key)
                except Exception:
                    raw_q = None
                if raw_q in (None, ""):
                    continue
                try:
                    queue_delay_ms = int(float(raw_q))
                except Exception:
                    queue_delay_ms = None
                if queue_delay_ms is not None:
                    queue_delay_ms = max(0, queue_delay_ms)
                    break
            extra_fields: Dict[str, Any] = {}
            if source is not None:
                try:
                    source_raw_text = str(source).strip()
                except Exception:
                    source_raw_text = ""
            if handler:
                try:
                    handler_text = str(handler).strip()
                except Exception:
                    handler_text = ""
            if command:
                try:
                    command_label = str(command).strip()
                except Exception:
                    command_label = ""
            if not command_label and ctx_dict:
                ctx_command = ctx_dict.get("command")
                if ctx_command:
                    try:
                        command_label = str(ctx_command).strip()
                    except Exception:
                        command_label = ""
            if command_label:
                pass
            if method:
                try:
                    method_text = str(method).upper()
                except Exception:
                    method_text = ""
            if path:
                try:
                    path_text = str(path).strip()
                except Exception:
                    path_text = ""
            source_origin, component_label = _classify_request_source(
                source_raw_text or None,
                handler_text or None,
                command_label or None,
                path_text or None,
            )
        except Exception:
            pass

        try:
            endpoint_label = (handler_text or command_label or path_text or "unknown")[:160]
            method_label = (method_text or "GET")[:16]
            _otel_record_http_outcome(
                status_code=int(status_code),
                duration_seconds=float(duration_seconds),
                endpoint=endpoint_label,
                method=method_label,
                source=source_origin or None,
                status_bucket=status_bucket,
                queue_delay_ms=queue_delay_ms,
            )
        except Exception:
            pass
        note_context = {
            "source": source_origin or None,
            "component": component_label or None,
            "handler": handler_text or None,
            "path": path_text or None,
            "method": method_text or None,
            "command": command_label or None,
            "request_id": rid,
            "user_id": (
                str(ctx_dict.get("user_id") or "").strip()
                if ctx_dict and ctx_dict.get("user_id")
                else None
            ),
        }
        if queue_delay_ms is not None:
            note_context["queue_delay_ms"] = int(queue_delay_ms)
        note_context = {k: v for k, v in note_context.items() if v}
        # Feed adaptive thresholds module (best-effort)
        try:
            from alert_manager import note_request, check_and_emit_alerts  # type: ignore
            note_request(
                int(status_code),
                float(duration_seconds),
                context=note_context or None,
                source=source_origin,
            )
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

    try:
        obs_duration = max(0.0, float(duration_seconds))
    except Exception:
        obs_duration = 0.0

    try:
        if handler:
            handler_name = _attach_source(handler, source, default="unknown_handler")
            if codebot_handler_requests_total is not None:
                try:
                    codebot_handler_requests_total.labels(
                        handler=handler_name,
                        status=status_bucket,
                        cache_hit=cache_label,
                    ).inc()
                except Exception:
                    pass
            if codebot_handler_latency_seconds is not None:
                try:
                    codebot_handler_latency_seconds.labels(
                        handler=handler_name,
                        status=status_bucket,
                        cache_hit=cache_label,
                    ).observe(obs_duration)
                except Exception:
                    pass
        if command:
            command_name = _attach_source(command, source, default="unknown_command")
            if codebot_command_requests_total is not None:
                try:
                    codebot_command_requests_total.labels(
                        command=command_name,
                        status=status_bucket,
                        cache_hit=cache_label,
                    ).inc()
                except Exception:
                    pass
            if codebot_command_latency_seconds is not None:
                try:
                    codebot_command_latency_seconds.labels(
                        command=command_name,
                        status=status_bucket,
                        cache_hit=cache_label,
                    ).observe(obs_duration)
                except Exception:
                    pass
    except Exception:
        pass


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


def _normalize_metric_label(value: str | None, default: str) -> str:
    try:
        v = (value or "").strip()
        if not v:
            return default
        return v.replace(" ", "_")[:120]
    except Exception:
        return default


def update_health_gauges(
    *,
    mongo_connected: bool | None = None,
    ping_ms: float | None = None,
    indexes_total: float | None = None,
    latency_ewma_ms: float | None = None,
) -> None:
    """Best-effort bridge from /healthz payload into Prometheus gauges."""
    try:
        if health_mongo_status is not None and mongo_connected is not None:
            health_mongo_status.set(1.0 if mongo_connected else 0.0)
        if health_ping_ms is not None and ping_ms is not None:
            health_ping_ms.set(max(0.0, float(ping_ms)))
        if health_indexes_total is not None and indexes_total is not None:
            health_indexes_total.set(max(0.0, float(indexes_total)))
        if health_latency_ewma is not None and latency_ewma_ms is not None:
            health_latency_ewma.set(max(0.0, float(latency_ewma_ms)))
    except Exception:
        return


def record_startup_stage_metric(stage: str, duration_ms: float | None) -> None:
    """Expose per-stage startup duration (milliseconds) via Prometheus."""
    if duration_ms is None:
        return
    try:
        if startup_stage_duration_ms is None:
            return
        stage_label = _normalize_metric_label(stage, "unknown_stage")
        startup_stage_duration_ms.labels(stage=stage_label).set(max(0.0, float(duration_ms)))
    except Exception:
        return


def record_startup_total_metric(duration_ms: float | None) -> None:
    """Expose total startup duration (milliseconds) via Prometheus."""
    if duration_ms is None:
        return
    try:
        if startup_total_duration_ms is None:
            return
        startup_total_duration_ms.set(max(0.0, float(duration_ms)))
    except Exception:
        return


def record_http_request(
    method: str,
    endpoint: str | None,
    status_code: int,
    duration_seconds: float,
    *,
    path: str | None = None,
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
        # Keep Prometheus metrics for history, but optionally exclude from slow-endpoint sampling.
        if not _is_anomaly_ignored(path=path, endpoint=endpoint):
            _note_http_request_sample(m, ep, int(status), float(duration_seconds))
    except Exception:
        return


def record_request_queue_delay(
    method: str,
    endpoint: str | None,
    delay_seconds: float,
) -> None:
    """Record request queue delay (best-effort, never raises)."""
    try:
        if http_request_queue_duration_seconds is None:
            return
        ep = _normalize_endpoint(endpoint)
        m = (method or "").upper() or "GET"
        delay = max(0.0, float(delay_seconds))
        http_request_queue_duration_seconds.labels(m, ep).observe(delay)
    except Exception:
        return


def record_outbound_request_duration(
    service: str | None,
    endpoint: str | None,
    status: str | None,
    duration_seconds: float,
) -> None:
    try:
        if outbound_request_duration_seconds is None:
            return
        svc = _normalize_metric_label(service, "unknown_service")
        ep = _normalize_metric_label(endpoint, "unknown_endpoint")
        st = _normalize_metric_label(status, "unknown_status")
        outbound_request_duration_seconds.labels(svc, ep, st).observe(max(0.0, float(duration_seconds)))
    except Exception:
        return


def increment_outbound_retry(service: str | None, endpoint: str | None) -> None:
    try:
        if outbound_retries_total is None:
            return
        svc = _normalize_metric_label(service, "unknown_service")
        ep = _normalize_metric_label(endpoint, "unknown_endpoint")
        outbound_retries_total.labels(svc, ep).inc()
    except Exception:
        return


def set_circuit_state(service: str | None, endpoint: str | None, state_value: float) -> None:
    try:
        if circuit_state_metric is None:
            return
        svc = _normalize_metric_label(service, "unknown_service")
        ep = _normalize_metric_label(endpoint, "unknown_endpoint")
        circuit_state_metric.labels(svc, ep).set(float(state_value))
    except Exception:
        return


def set_circuit_success_rate(service: str | None, endpoint: str | None, value: float) -> None:
    try:
        if circuit_success_rate_metric is None:
            return
        svc = _normalize_metric_label(service, "unknown_service")
        ep = _normalize_metric_label(endpoint, "unknown_endpoint")
        circuit_success_rate_metric.labels(svc, ep).set(max(0.0, min(1.0, float(value))))
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


def record_db_operation(operation: str, duration_seconds: float, *, status: str | None = "ok") -> None:
    """Record latency + count for database hot path operations."""
    try:
        op_label = _normalize_metric_label(operation, "unknown_operation")
        status_label = _normalize_metric_label(status, "ok")
        duration = max(0.0, float(duration_seconds))
    except Exception:
        return
    try:
        if codebot_db_requests_total is not None:
            try:
                codebot_db_requests_total.labels(operation=op_label, status=status_label).inc()
            except Exception:
                pass
        if codebot_db_latency_seconds is not None:
            try:
                codebot_db_latency_seconds.labels(operation=op_label, status=status_label).observe(duration)
            except Exception:
                pass
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
        try:
            with _ERR_TIMESTAMPS_LOCK:
                err_rate = sum(1 for ts in _ERR_TIMESTAMPS if ts >= window_start)
        except Exception:
            err_rate = 0

        # Average response time
        avg_rt = float(_EWMA_RT or 0.0)
        latency_threshold = _current_latency_threshold(now)

        breach_msgs: list[str] = []
        if err_rate >= _ERRS_PER_MIN_THRESHOLD and _ERRS_PER_MIN_THRESHOLD > 0:
            breach_msgs.append(f"errors/min >= {err_rate} (threshold {_ERRS_PER_MIN_THRESHOLD})")
        if avg_rt >= latency_threshold and latency_threshold > 0:
            breach_msgs.append(f"avg_rt={avg_rt:.3f}s (threshold {latency_threshold:.3f}s)")

        if not breach_msgs:
            return

        _ANOMALY_LAST_TS = now
        summary = "; ".join(breach_msgs)
        slow_endpoints = get_top_slow_endpoints(limit=5)
        top_endpoint = get_slowest_endpoint()
        active_requests = get_active_requests_count()
        recent_errors_5m = get_recent_errors_count(minutes=5)
        memory_mb = get_current_memory_usage()
        if avg_rt >= latency_threshold and latency_threshold > 0:
            try:
                logger.warning(
                    "High response time detected",
                    extra={
                        "avg_response_time": round(avg_rt, 4),
                        "threshold": round(latency_threshold, 4),
                        "active_requests": active_requests,
                        "recent_errors_5m": recent_errors_5m,
                        "slow_endpoints": slow_endpoints,
                        "memory_mb": round(memory_mb, 2),
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                )
            except Exception:
                pass

        alert_labels = {
            "top_slow_endpoint": top_endpoint,
            "active_requests": str(active_requests),
            "recent_errors_5m": str(recent_errors_5m),
            "avg_memory_usage_mb": f"{memory_mb:.2f}",
        }
        try:
            from internal_alerts import emit_internal_alert  # type: ignore
            emit_internal_alert(
                name="anomaly_detected",
                severity="anomaly",
                summary=summary,
                labels=alert_labels,
                slow_endpoints=slow_endpoints,
            )
        except Exception:
            # As a fallback, emit a structured event only
            try:
                emit_event(
                    "anomaly_detected",
                    severity="anomaly",
                    summary=summary,
                    labels=alert_labels,
                    slow_endpoints=slow_endpoints,
                )
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


def set_external_error_rate_percent(value: Optional[float]) -> None:
    """Update the external error rate gauge (best-effort)."""
    try:
        if codebot_external_error_rate_percent is None or value is None:
            return
        codebot_external_error_rate_percent.set(max(0.0, float(value)))
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
