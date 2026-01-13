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
- METRICS_ROLLUP_SECONDS: Rollup bucket size in seconds for DB writes (default: 60)
"""
from __future__ import annotations

import math
import os
import sys
import time
from collections import deque
from datetime import datetime, timezone
from threading import Event, Lock, Thread
from typing import Any, Dict, List, Optional, Tuple

# Optional structured event emission (do not hard-depend)
try:  # pragma: no cover
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields: Any) -> None:  # type: ignore
        return None


def _is_true(val: Optional[str]) -> bool:
    return str(val or "").lower() in {"1", "true", "yes", "on"}


def _write_enabled() -> bool:
    """Check if WRITING metrics to DB is enabled.

    שומרי בטיחות:
    - ברירת המחדל היא OFF (כדי לא להעמיס על MongoDB בלי כוונה)
    - אפשר לעצור כתיבה באופן מיידי עם DISABLE_METRICS_WRITES=true
    """
    if _is_true(os.getenv("DISABLE_DB")):
        return False
    if _is_true(os.getenv("DISABLE_METRICS_WRITES")):
        return False
    return _is_true(os.getenv("METRICS_DB_ENABLED"))


def _read_enabled() -> bool:
    """Check if READING metrics from DB is enabled.

    קריאה מה-DB נשארת פעילה תמיד (אלא אם מושבתת מפורשות),
    כדי שדשבורד ה-Observability יציג נתונים היסטוריים גם כשהכתיבה מושבתת.
    """
    if _is_true(os.getenv("DISABLE_DB")):
        return False
    if _is_true(os.getenv("DISABLE_METRICS_READS")):
        return False
    # אם METRICS_DB_ENABLED=true או שיש URL תקין - אפשר לקרוא
    if _is_true(os.getenv("METRICS_DB_ENABLED")):
        return True
    # Fallback: אפשר קריאה אם יש MongoDB URL מוגדר (גם בלי METRICS_DB_ENABLED)
    return bool(os.getenv("MONGODB_URL"))


def _enabled() -> bool:
    """Legacy function - now delegates to _write_enabled for backwards compatibility."""
    return _write_enabled()


# Lazily-initialized PyMongo client/collection
_client = None  # type: ignore
_collection = None  # type: ignore
_init_failed = False  # True when initialization permanently failed (e.g., pymongo missing)
_write_disabled = False  # True when writes are intentionally disabled (not a failure)
_buf: deque[Dict[str, Any]] = deque()
_agg: Dict[Tuple[int, str, str], Dict[str, Any]] = {}
_lock = Lock()
_last_flush_ts: float = time.time()

# Background flush worker (to avoid blocking request path)
_worker_started = False
_worker_event = Event()
_start_lock = Lock()


def _is_pytest() -> bool:
    return bool(os.getenv("PYTEST_CURRENT_TEST")) or ("pytest" in sys.modules)


def _start_worker_if_needed() -> None:
    global _worker_started
    if _worker_started or _is_pytest():
        return
    # Double-checked locking to avoid spawning multiple workers under concurrency
    with _start_lock:
        if _worker_started or _is_pytest():
            return
        try:
            t = Thread(target=_worker_loop, name="metrics-db-writer", daemon=True)
            t.start()
            _worker_started = True
        except Exception:
            # Fail-open: never block app due to background thread
            return


def _worker_loop() -> None:  # pragma: no cover
    """Flush queued metrics in background so UI requests aren't blocked by DB inserts."""
    while True:
        try:
            interval = int(os.getenv("METRICS_FLUSH_INTERVAL_SEC", "5") or "5")
        except Exception:
            interval = 5
        try:
            # Wake on signal or periodically
            _worker_event.wait(timeout=max(1, interval))
            _worker_event.clear()
        except Exception:
            pass
        try:
            flush(force=False)
        except Exception:
            pass


def _build_time_match(start_dt: Optional[datetime], end_dt: Optional[datetime]) -> Dict[str, Any]:
    # Support both legacy per-request docs and rollup docs.
    match: Dict[str, Any] = {"type": {"$in": ["request", "request_agg"]}}
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


def _rollup_seconds() -> int:
    """Return rollup bucket size in seconds for DB writes."""
    try:
        value = int(os.getenv("METRICS_ROLLUP_SECONDS", "60") or "60")
    except Exception:
        value = 60
    return max(1, min(3600, value))


def _bucket_start_dt(now: datetime, bucket_seconds: int) -> datetime:
    """Floor a datetime to bucket_seconds (UTC)."""
    try:
        ts = int(now.timestamp())
    except Exception:
        ts = int(time.time())
    b = int(bucket_seconds) if bucket_seconds else 60
    b = max(1, b)
    bucket_ts = ts - (ts % b)
    return datetime.fromtimestamp(bucket_ts, tz=timezone.utc)


def _safe_label(value: Any, *, default: str, limit: int = 160) -> str:
    """Normalize a potentially noisy label into a bounded string."""
    try:
        text = str(value or "").strip()
    except Exception:
        text = ""
    if not text:
        return default
    # Keep labels low-cardinality-ish (no newlines, bounded length)
    text = text.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    if len(text) > limit:
        text = text[:limit]
    return text


def _drain_agg_to_buf_unlocked() -> None:
    """Move rollup entries from _agg into _buf. Caller must hold _lock."""
    if not _agg:
        return
    try:
        for doc in _agg.values():
            _buf.append(doc)
    finally:
        _agg.clear()


def _get_collection(*, for_read: bool = True):  # pragma: no cover - exercised indirectly
    """Get the MongoDB collection for metrics storage.

    Args:
        for_read: If True, allows connection even when writes are disabled.
                  This enables the Observability dashboard to show historical data.
    """
    global _client, _collection, _init_failed, _write_disabled

    # If already initialized successfully, return the collection
    if _collection is not None:
        return _collection

    # If initialization permanently failed (e.g., pymongo missing), don't retry
    if _init_failed:
        return None

    # If writes are disabled and this is a write request, return None
    # but allow read requests to proceed with initialization
    if _write_disabled and not for_read:
        return None

    # Check if we should connect based on read/write mode
    enabled = _read_enabled() if for_read else _write_enabled()
    if not enabled:
        # Mark write_disabled (not init_failed) so reads can still work
        if not for_read:
            _write_disabled = True
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


def _flush_once(now_ts: float) -> bool:
    coll = _get_collection(for_read=False)  # Writing metrics requires write access
    if coll is None:
        # If initialization failed permanently, clear buffer to prevent leaks
        if _init_failed:
            with _lock:
                try:
                    _agg.clear()
                    _buf.clear()
                except Exception:
                    pass
        return False

    # Convert current rollups into buffer before popping a batch
    try:
        with _lock:
            _drain_agg_to_buf_unlocked()
            # Cap buffer to prevent unbounded growth under persistent failures
            try:
                max_buf = _max_buffer_size()
                while len(_buf) > max_buf:
                    _buf.popleft()
            except Exception:
                pass
    except Exception:
        # best-effort; continue
        pass

    # Pop a batch under lock, but perform IO without holding the lock
    try:
        batch_size = int(os.getenv("METRICS_BATCH_SIZE", "50") or "50")
    except Exception:
        batch_size = 50
    items: List[Dict[str, Any]] = []
    try:
        with _lock:
            while _buf and len(items) < max(1, batch_size):
                items.append(_buf.popleft())
    except Exception:
        # Never lose already-popped items
        try:
            with _lock:
                for it in reversed(items):
                    _buf.appendleft(it)
        except Exception:
            pass
        return False

    if not items:
        return False

    try:
        coll.insert_many(items, ordered=False)  # type: ignore[attr-defined]
        global _last_flush_ts
        with _lock:
            _last_flush_ts = now_ts
        return True
    except Exception as e:  # Re-queue on failure
        with _lock:
            for it in reversed(items):
                _buf.appendleft(it)
        emit_event("metrics_db_batch_insert_error", severity="warn", error=str(e), count=len(items))
        return False


def flush(force: bool = False) -> None:
    # Emergency kill-switch: disable DB writes explicitly when needed.
    # Default is OFF (i.e., writes are allowed when METRICS_DB_ENABLED=true).
    if _is_true(os.getenv("DISABLE_METRICS_WRITES")):
        return
    if not _enabled():
        return
    now_ts = time.time()
    try:
        interval = int(os.getenv("METRICS_FLUSH_INTERVAL_SEC", "5") or "5")
    except Exception:
        interval = 5
    # Time-based threshold
    if not force and (now_ts - _last_flush_ts) < max(1, interval):
        return
    # Flush multiple batches best-effort (useful for force=True and for draining the queue)
    for _ in range(100):
        if not _flush_once(time.time()):
            break


def enqueue_request_metric(
    status_code: int,
    duration_seconds: float,
    *,
    request_id: str | None = None,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Queue a single request metric for best-effort DB persistence.

    Notes:
    - Writes are opt-in via METRICS_DB_ENABLED=true
    - In production we do NOT write "one document per request".
      Instead, we aggregate (roll up) into per-bucket documents to keep Mongo load low.
    """
    # Emergency kill-switch: disable DB writes explicitly when needed.
    # Default is OFF (i.e., writes are allowed when METRICS_DB_ENABLED=true).
    if _is_true(os.getenv("DISABLE_METRICS_WRITES")):
        return
    if not _enabled():
        return
    # If initialization was deemed impossible (pymongo missing / bad URL),
    # drop new items immediately to uphold fail-open semantics.
    if _init_failed:
        return
    try:
        now = datetime.now(timezone.utc)
        rollup_sec = _rollup_seconds()
        bucket_dt = _bucket_start_dt(now, rollup_sec)
        bucket_ts = int(bucket_dt.timestamp())

        # Best-effort enrich with low-cardinality context (method/path/handler)
        method = "UNKNOWN"
        path = "unknown"
        handler = ""
        if isinstance(extra, dict):
            method = _safe_label(extra.get("method"), default="UNKNOWN", limit=16).upper()
            handler = _safe_label(extra.get("handler"), default="", limit=160)
            path = _safe_label(extra.get("path") or handler, default="unknown", limit=160)
        else:
            method = "UNKNOWN"
            path = "unknown"

        dur = max(0.0, float(duration_seconds))
        is_err = 1 if int(status_code) >= 500 else 0

        with _lock:
            # Re-check under lock to avoid races
            if _init_failed:
                return

            key = (bucket_ts, method, path)
            doc = _agg.get(key)
            if doc is None:
                doc = {
                    "ts": bucket_dt,
                    "type": "request_agg",
                    "bucket_seconds": int(rollup_sec),
                    "method": method,
                    "path": path,
                    # Keep handler if provided (may be useful for debugging)
                    "handler": handler or None,
                    "count": 0,
                    "sum_duration": 0.0,
                    "max_duration": 0.0,
                    "error_count": 0,
                }
                _agg[key] = doc

            # Update rollup counters
            try:
                doc["count"] = int(doc.get("count", 0) or 0) + 1
            except Exception:
                doc["count"] = 1
            try:
                doc["sum_duration"] = float(doc.get("sum_duration", 0.0) or 0.0) + dur
            except Exception:
                doc["sum_duration"] = dur
            try:
                prev_max = float(doc.get("max_duration", 0.0) or 0.0)
            except Exception:
                prev_max = 0.0
            doc["max_duration"] = max(prev_max, dur)
            try:
                doc["error_count"] = int(doc.get("error_count", 0) or 0) + int(is_err)
            except Exception:
                doc["error_count"] = int(is_err)

            # Cap total queued DB docs (rollups + pending inserts)
            try:
                max_buf = _max_buffer_size()
                # If _agg grows too much (e.g. huge cardinality), start dropping oldest
                while len(_agg) + len(_buf) > max_buf:
                    # Drain one rollup into buffer, then drop from buffer head
                    _drain_agg_to_buf_unlocked()
                    if _buf:
                        _buf.popleft()
                    else:
                        break
            except Exception:
                pass
        # Never flush on the request path. Wake background worker instead.
        _start_worker_if_needed()
        try:
            _worker_event.set()
        except Exception:
            pass
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
                # Support both legacy per-request docs and rollup docs
                "count": {
                    "$cond": [
                        {"$eq": ["$type", "request_agg"]},
                        {"$ifNull": ["$count", 0]},
                        1,
                    ]
                },
                "sum_duration": {
                    "$cond": [
                        {"$eq": ["$type", "request_agg"]},
                        {"$ifNull": ["$sum_duration", 0.0]},
                        {"$ifNull": ["$duration_seconds", 0.0]},
                    ]
                },
                "max_duration": {
                    "$cond": [
                        {"$eq": ["$type", "request_agg"]},
                        {"$ifNull": ["$max_duration", 0.0]},
                        {"$ifNull": ["$duration_seconds", 0.0]},
                    ]
                },
                "error_count": {
                    "$cond": [
                        {"$eq": ["$type", "request_agg"]},
                        {"$ifNull": ["$error_count", 0]},
                        {
                            "$cond": [
                                {"$gte": ["$status_code", 500]},
                                1,
                                0,
                            ]
                        },
                    ]
                },
            }
        },
        {
            "$group": {
                "_id": "$bucket",
                "count": {"$sum": "$count"},
                "sum_duration": {"$sum": "$sum_duration"},
                "max_duration": {"$max": "$max_duration"},
                "error_count": {"$sum": "$error_count"},
            }
        },
        {
            "$project": {
                "count": 1,
                "avg_duration": {
                    "$cond": [
                        {"$gt": ["$count", 0]},
                        {"$divide": ["$sum_duration", "$count"]},
                        0.0,
                    ]
                },
                "max_duration": 1,
                "error_count": 1,
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
                "count": {
                    "$cond": [
                        {"$eq": ["$type", "request_agg"]},
                        {"$ifNull": ["$count", 0]},
                        1,
                    ]
                },
                "sum_duration": {
                    "$cond": [
                        {"$eq": ["$type", "request_agg"]},
                        {"$ifNull": ["$sum_duration", 0.0]},
                        {"$ifNull": ["$duration_seconds", 0.0]},
                    ]
                },
                "max_duration": {
                    "$cond": [
                        {"$eq": ["$type", "request_agg"]},
                        {"$ifNull": ["$max_duration", 0.0]},
                        {"$ifNull": ["$duration_seconds", 0.0]},
                    ]
                },
            }
        },
        {
            "$group": {
                "_id": {"path": "$path", "method": "$method"},
                "count": {"$sum": "$count"},
                "sum_duration": {"$sum": "$sum_duration"},
                "max_duration": {"$max": "$max_duration"},
            }
        },
        {
            "$project": {
                "count": 1,
                "avg_duration": {
                    "$cond": [
                        {"$gt": ["$count", 0]},
                        {"$divide": ["$sum_duration", "$count"]},
                        0.0,
                    ]
                },
                "max_duration": 1,
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
            "$project": {
                "count": {
                    "$cond": [
                        {"$eq": ["$type", "request_agg"]},
                        {"$ifNull": ["$count", 0]},
                        1,
                    ]
                },
                "sum_duration": {
                    "$cond": [
                        {"$eq": ["$type", "request_agg"]},
                        {"$ifNull": ["$sum_duration", 0.0]},
                        {"$ifNull": ["$duration_seconds", 0.0]},
                    ]
                },
            }
        },
        {
            "$group": {
                "_id": None,
                "count": {"$sum": "$count"},
                "sum_duration": {"$sum": "$sum_duration"},
            }
        },
        {
            "$project": {
                "avg_duration": {
                    "$cond": [
                        {"$gt": ["$count", 0]},
                        {"$divide": ["$sum_duration", "$count"]},
                        0.0,
                    ]
                }
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
            "$project": {
                "count": {
                    "$cond": [
                        {"$eq": ["$type", "request_agg"]},
                        {"$ifNull": ["$count", 0]},
                        1,
                    ]
                },
                "error_count": {
                    "$cond": [
                        {"$eq": ["$type", "request_agg"]},
                        {"$ifNull": ["$error_count", 0]},
                        {
                            "$cond": [
                                {"$gte": ["$status_code", 500]},
                                1,
                                0,
                            ]
                        },
                    ]
                },
            }
        },
        {
            "$group": {
                "_id": None,
                "total": {"$sum": "$count"},
                "errors": {"$sum": "$error_count"},
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

    # Percentiles require raw per-request samples (rollups are not sufficient).
    match = {"type": "request"}
    if start_dt or end_dt:
        window: Dict[str, Any] = {}
        if start_dt:
            window["$gte"] = start_dt
        if end_dt:
            window["$lte"] = end_dt
        if window:
            match["ts"] = window

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
