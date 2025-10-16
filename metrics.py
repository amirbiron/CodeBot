"""
Prometheus metrics primitives and helpers.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Optional

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
errors_total = Counter("errors_total", "Total error count", ["code"]) if Counter else None
operation_latency_seconds = Histogram(
    "operation_latency_seconds",
    "Operation latency in seconds",
    ["operation", "repo"],
) if Histogram else None
telegram_updates_total = Counter(
    "telegram_updates_total",
    "Total Telegram updates processed",
    ["type", "status"],
) if Counter else None
active_indexes = Gauge("active_indexes", "Active DB indexes") if Gauge else None

# Optional business events counter for high-level analytics
business_events_total = Counter(
    "business_events_total",
    "Count of business-domain events",
    ["metric"],
) if Counter else None


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
