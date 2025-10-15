"""
Prometheus metrics primitives and helpers.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Dict, Optional

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
    ["operation"],
) if Histogram else None
telegram_updates_total = Counter(
    "telegram_updates_total",
    "Total Telegram updates processed",
    ["type", "status"],
) if Counter else None
active_indexes = Gauge("active_indexes", "Active DB indexes") if Gauge else None


@contextmanager
def track_performance(operation: str, labels: Optional[Dict[str, str]] = None):
    start = time.time()
    try:
        yield
    finally:
        if operation_latency_seconds is not None:
            try:
                if labels:
                    operation_latency_seconds.labels(operation=operation, **labels).observe(time.time() - start)
                else:
                    operation_latency_seconds.labels(operation=operation).observe(time.time() - start)
            except Exception:
                # avoid breaking app on label mistakes
                pass


def metrics_endpoint_bytes() -> bytes:
    return generate_latest()


def metrics_content_type() -> str:
    return CONTENT_TYPE_LATEST
