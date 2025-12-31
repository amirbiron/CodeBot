from __future__ import annotations

try:
    from prometheus_client import Counter, Histogram, Gauge
except Exception:  # pragma: no cover
    Counter = Histogram = Gauge = None  # type: ignore

# מטריקות
SLOW_QUERIES_TOTAL = (
    Counter(
        "mongodb_slow_queries_total",
        "Total number of slow queries",
        ["collection", "operation"],
    )
    if Counter
    else None
)

QUERY_DURATION = (
    Histogram(
        "mongodb_query_duration_seconds",
        "Query duration in seconds",
        ["collection", "operation"],
        buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
    )
    if Histogram
    else None
)

COLLSCAN_DETECTED = (
    Counter(
        "mongodb_collscan_detected_total",
        "Number of COLLSCAN operations detected",
        ["collection"],
    )
    if Counter
    else None
)

ACTIVE_PROFILER_BUFFER_SIZE = (
    Gauge(
        "query_profiler_buffer_size",
        "Current number of queries in profiler buffer",
    )
    if Gauge
    else None
)

