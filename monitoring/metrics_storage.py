"""
Lightweight DB-backed metrics storage with safe, best-effort batching.

Design goals:
- Fail-open: never break app flow if DB unavailable or pymongo missing
- No import-time DB connections; initialize lazily on first flush
- Use environment variables only (avoid importing config to prevent cycles)
- Memory-safety in misconfiguration: drop/cap buffer when storage unavailable

Environment variables:
- METRICS_DB_ENABLED: "true/1/yes" to enable DB writes (default: false)
- MONGODB_URL: Mongo connection string (required when enabled)
- DATABASE_NAME: Database name (default: code_keeper_bot)
- METRICS_COLLECTION: Collection name (default: service_metrics)
- METRICS_BATCH_SIZE: Batch size threshold (default: 50)
- METRICS_FLUSH_INTERVAL_SEC: Time-based flush threshold (default: 5 seconds)
- METRICS_MAX_BUFFER: Max queued items in memory (default: 5000)
"""
from __future__ import annotations

import math
import os
import time
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

# Optional structured event emission (do not hard-depend)
try:  # pragma: no cover
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields: Any) -> None:  # type: ignore
        return None


def _is_true(val: Optional[str]) -> bool:
    return str(val or "").lower() in {"1", "true", "yes", "on"}


def _enabled() -> bool:
    if _is_true(os.getenv("DISABLE_DB")):
        return False
    return _is_true(os.getenv("METRICS_DB_ENABLED"))


# Lazily-initialized PyMongo client/collection
_client = None  # type: ignore
_collection = None  # type: ignore
_init_failed = False
_buf: deque[Dict[str, Any]] = deque()
_lock = Lock()
_last_flush_ts: float = time.time()


def _build_time_match(start_dt: Optional[datetime], end_dt: Optional[datetime]) -> Dict[str, Any]:
    match: Dict[str, Any] = {"type": "request"}
    if start_dt or end_dt:
        window: Dict[str, Any] = {}
        if start_dt:
            window["$gte"] = start_dt
        if end_dt:
            window["$lte"] = end_dt
        if window:
            match["ts"] = window
    return match


def _max_buffer_size() -> int:
    try:
        return max(1, int(os.getenv("METRICS_MAX_BUFFER", "5000") or "5000"))
    except Exception:
        return 5000


def _get_collection():  # pragma: no cover - exercised indirectly
    global _client, _collection, _init_failed
    if _collection is not None or _init_failed:
        return _collection

    if not _enabled():
        _init_failed = True  # mark to skip further attempts
        return None

    try:
        try:
            from pymongo import MongoClient  # type: ignore
        except Exception:
            _init_failed = True
            emit_event("metrics_db_pymongo_missing", severity="warn")
            return None

        mongo_url = os.getenv("MONGODB_URL")
        if not mongo_url:
            _init_failed = True
            emit_event("metrics_db_missing_url", severity="warn")
            return None

        db_name = os.getenv("DATABASE_NAME") or "code_keeper_bot"
        coll_name = os.getenv("METRICS_COLLECTION") or "service_metrics"

        _client = MongoClient(
            mongo_url,
            maxPoolSize=20,
            minPoolSize=0,
            serverSelectionTimeoutMS=2000,
            socketTimeoutMS=5000,
            connectTimeoutMS=2000,
            retryWrites=True,
            retryReads=True,
        )
        db = _client[db_name]
        _collection = db[coll_name]
        try:
            _client.admin.command("ping")
        except Exception:
            # Connection might still succeed later; do not fail-hard
            pass
        emit_event("metrics_db_initialized", severity="info", collection=coll_name)
        return _collection
    except Exception as e:
        _init_failed = True
        emit_event("metrics_db_init_error", severity="warn", error=str(e))
        return None


def _flush_locked(now_ts: float) -> None:
    coll = _get_collection()
    if coll is None:
        # If initialization failed permanently, clear buffer to prevent leaks
        if _init_failed:
            try:
                _buf.clear()
            except Exception:
                pass
        return
    if not _buf:
        return
    # Pop a batch while holding the lock; on failure, push back
    batch_size = int(os.getenv("METRICS_BATCH_SIZE", "50") or "50")
    items = []
    try:
        while _buf and len(items) < max(1, batch_size):
            items.append(_buf.popleft())
        if not items:
            return
        try:
            coll.insert_many(items, ordered=False)  # type: ignore[attr-defined]
            global _last_flush_ts
            _last_flush_ts = now_ts
        except Exception as e:  # Re-queue on failure
            for it in reversed(items):
                _buf.appendleft(it)
            emit_event("metrics_db_batch_insert_error", severity="warn", error=str(e), count=len(items))
    except Exception:
        # On any unexpected error, re-queue items to preserve data
        for it in reversed(items):
            _buf.appendleft(it)


def flush(force: bool = False) -> None:
    if not _enabled():
        return
    now_ts = time.time()
    with _lock:
        # Time-based threshold
        interval = int(os.getenv("METRICS_FLUSH_INTERVAL_SEC", "5") or "5")
        if force or (now_ts - _last_flush_ts) >= max(1, interval):
            _flush_locked(now_ts)


def enqueue_request_metric(
    status_code: int,
    duration_seconds: float,
    *,
    request_id: str | None = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Queue a single request metric for best-effort DB persistence.

    No-ops entirely when METRICS_DB_ENABLED is not true.
    """
    if not _enabled():
        return
    # If initialization was deemed impossible (pymongo missing / bad URL),
    # drop new items immediately to uphold fail-open semantics.
    if _init_failed:
        return
    try:
        doc: Dict[str, Any] = {
            "ts": datetime.now(timezone.utc),
            "type": "request",
            "status_code": int(status_code),
            "duration_seconds": float(duration_seconds),
        }
        if request_id:
            doc["request_id"] = str(request_id)
        if extra:
            for k, v in (extra or {}).items():
                if k in doc:
                    continue
                doc[k] = v

        with _lock:
            # Re-check under lock to avoid races
            if _init_failed:
                return
            _buf.append(doc)
            # Cap buffer to prevent unbounded growth under persistent failures
            try:
                max_buf = _max_buffer_size()
                while len(_buf) > max_buf:
                    _buf.popleft()
            except Exception:
                pass
            # Size-based flush threshold
            batch_size = int(os.getenv("METRICS_BATCH_SIZE", "50") or "50")
            if len(_buf) >= max(1, batch_size):
                _flush_locked(time.time())
        # Also attempt time-based flush outside lock (cheap check)
        flush(force=False)
    except Exception:
        # Fail-open: never raise
        return


def aggregate_request_timeseries(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    granularity_seconds: int,
) -> List[Dict[str, Any]]:
    """Aggregate request metrics into fixed time buckets."""
    coll = _get_collection()
    if coll is None:
        return []
    try:
        bucket_seconds = max(1, int(granularity_seconds or 1))
    except Exception:
        bucket_seconds = 60
    bucket_ms = bucket_seconds * 1000

    match = _build_time_match(start_dt, end_dt)
    pipeline = [
        {"$match": match},
        {
            "$project": {
                "bucket": {
                    "$toDate": {
                        "$subtract": [
                            {"$toLong": "$ts"},
                            {"$mod": [{"$toLong": "$ts"}, bucket_ms]},
                        ]
                    }
                },
                "duration_seconds": "$duration_seconds",
                "status_code": "$status_code",
            }
        },
        {
            "$group": {
                "_id": "$bucket",
                "count": {"$sum": 1},
                "avg_duration": {"$avg": "$duration_seconds"},
                "max_duration": {"$max": "$duration_seconds"},
                "error_count": {
                    "$sum": {
                        "$cond": [
                            {"$gte": ["$status_code", 500]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {"$sort": {"_id": 1}},
    ]
    try:
        rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for row in rows:
        bucket = row.get("_id")
        ts_iso = None
        if isinstance(bucket, datetime):
            ts_iso = bucket.astimezone(timezone.utc).isoformat()
        out.append(
            {
                "timestamp": ts_iso,
                "count": int(row.get("count", 0)),
                "avg_duration": float(row.get("avg_duration", 0.0) or 0.0),
                "max_duration": float(row.get("max_duration", 0.0) or 0.0),
                "error_count": int(row.get("error_count", 0)),
            }
        )
    return out


def aggregate_top_endpoints(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Return the slowest HTTP endpoints within the given time window."""
    coll = _get_collection()
    if coll is None:
        return []
    try:
        max_items = max(1, min(50, int(limit)))
    except Exception:
        max_items = 5

    match = _build_time_match(start_dt, end_dt)
    pipeline = [
        {"$match": match},
        {
            "$project": {
                "path": {
                    "$ifNull": [
                        "$path",
                        {"$ifNull": ["$handler", "unknown"]},
                    ]
                },
                "method": {"$ifNull": ["$method", "UNKNOWN"]},
                "duration_seconds": "$duration_seconds",
            }
        },
        {
            "$group": {
                "_id": {"path": "$path", "method": "$method"},
                "count": {"$sum": 1},
                "avg_duration": {"$avg": "$duration_seconds"},
                "max_duration": {"$max": "$duration_seconds"},
            }
        },
        {"$sort": {"max_duration": -1}},
        {"$limit": max_items},
    ]
    try:
        rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for row in rows:
        ident = row.get("_id") or {}
        path = ident.get("path") or "unknown"
        method = ident.get("method") or "UNKNOWN"
        out.append(
            {
                "endpoint": str(path),
                "method": str(method),
                "count": int(row.get("count", 0)),
                "avg_duration": float(row.get("avg_duration", 0.0) or 0.0),
                "max_duration": float(row.get("max_duration", 0.0) or 0.0),
            }
        )
    return out


def average_request_duration(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
) -> Optional[float]:
    """Return the average request duration for a given window."""
    coll = _get_collection()
    if coll is None:
        return None
    match = _build_time_match(start_dt, end_dt)
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": None,
                "avg_duration": {"$avg": "$duration_seconds"},
            }
        },
    ]
    try:
        rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]
    except Exception:
        return None
    if not rows:
        return None
    value = rows[0].get("avg_duration")
    try:
        return float(value)
    except Exception:
        return None


def aggregate_error_ratio(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
) -> Dict[str, int]:
    """Return total/error counts for the window."""
    coll = _get_collection()
    if coll is None:
        return {"total": 0, "errors": 0}
    match = _build_time_match(start_dt, end_dt)
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": None,
                "total": {"$sum": 1},
                "errors": {
                    "$sum": {
                        "$cond": [
                            {"$gte": ["$status_code", 500]},
                            1,
                            0,
                        ]
                    }
                },
            }
        },
    ]
    try:
        rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]
    except Exception:
        return {"total": 0, "errors": 0}
    if not rows:
        return {"total": 0, "errors": 0}
    doc = rows[0]
    return {"total": int(doc.get("total", 0)), "errors": int(doc.get("errors", 0))}


def find_by_request_id(
    request_id: str,
    *,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Find metrics records by request_id.

    Used by triage service to provide fallback when Sentry is unavailable.
    Returns empty list on any failure (fail-open).
    """
    if not request_id:
        return []
    coll = _get_collection()
    if coll is None:
        return []
    try:
        import re
        rid = str(request_id).strip()
        if not rid:
            return []
        max_items = max(1, min(100, int(limit)))
        # Regex safety: escape special characters to prevent injection (see alert_tags_storage.py)
        rid_escaped = re.escape(rid)
        # Search by exact match or partial match (prefix)
        query: Dict[str, Any] = {
            "$or": [
                {"request_id": rid},
                {"request_id": {"$regex": f"^{rid_escaped}"}},
            ]
        }
        cursor = (
            coll.find(query)  # type: ignore[attr-defined]
            .sort("ts", -1)
            .limit(max_items)
        )
        results: List[Dict[str, Any]] = []
        for doc in cursor:
            try:
                ts = doc.get("ts")
                ts_iso = ""
                if isinstance(ts, datetime):
                    ts_iso = ts.astimezone(timezone.utc).isoformat()
                results.append({
                    "timestamp": ts_iso,
                    "request_id": str(doc.get("request_id") or ""),
                    "status_code": int(doc.get("status_code", 0) or 0),
                    "duration_seconds": float(doc.get("duration_seconds", 0.0) or 0.0),
                    "path": str(doc.get("path") or doc.get("handler") or ""),
                    "method": str(doc.get("method") or ""),
                })
            except Exception:
                continue
        return results
    except Exception:
        return []


def aggregate_latency_percentiles(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    percentiles: Tuple[int, ...] = (50, 95, 99),
    sample_limit: int = 5000,
) -> Dict[str, float]:
    """Return latency percentiles (seconds) for the given window.

    Best-effort:
    - Try Mongo $percentile aggregation when available.
    - Otherwise, sample up to sample_limit records and compute percentiles in Python.
    """
    coll = _get_collection()
    if coll is None:
        return {}

    try:
        pcts = tuple(int(p) for p in (percentiles or (50, 95, 99)))
    except Exception:
        pcts = (50, 95, 99)
    pcts = tuple(p for p in pcts if 0 < int(p) < 100)
    if not pcts:
        pcts = (50, 95, 99)

    match = _build_time_match(start_dt, end_dt)

    # Attempt Mongo-native percentile aggregation (MongoDB 5.2+)
    try:
        p_array = [float(p) / 100.0 for p in pcts]
        pipeline = [
            {"$match": match},
            {
                "$group": {
                    "_id": None,
                    "p": {
                        "$percentile": {
                            "input": "$duration_seconds",
                            "p": p_array,
                            "method": "approximate",
                        }
                    },
                }
            },
        ]
        rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]
        if rows:
            arr = rows[0].get("p")
            if isinstance(arr, list) and len(arr) == len(pcts):
                out: Dict[str, float] = {}
                for idx, p in enumerate(pcts):
                    try:
                        out[f"p{p}"] = float(arr[idx])
                    except Exception:
                        continue
                if out:
                    return out
    except Exception:
        # fallback below
        pass

    # Fallback: sample durations and compute percentiles in Python (nearest-rank).
    try:
        max_items = max(1, min(50_000, int(sample_limit)))
    except Exception:
        max_items = 5000
    try:
        cursor = (
            coll.find(match, {"duration_seconds": 1, "_id": 0})  # type: ignore[attr-defined]
            .sort("ts", -1)
            .limit(max_items)
        )
        values: list[float] = []
        for doc in cursor:
            try:
                values.append(float(doc.get("duration_seconds", 0.0) or 0.0))
            except Exception:
                continue
        if not values:
            return {}
        values.sort()

        def _nearest_rank(p: int) -> float:
            if not values:
                return 0.0
            # nearest-rank: ceil(p/100 * N) - 1
            n = len(values)
            k = int(math.ceil((float(p) / 100.0) * float(n))) - 1
            k = max(0, min(n - 1, k))
            return float(values[k])

        out: Dict[str, float] = {}
        for p in pcts:
            try:
                out[f"p{p}"] = _nearest_rank(int(p))
            except Exception:
                continue
        return out
    except Exception:
        return {}
