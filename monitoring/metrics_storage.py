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

import os
import time
from collections import deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, Optional

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
