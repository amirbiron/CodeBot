"""
MongoDB-backed alerts storage with TTL and simple counters.

Design goals:
- Fail-open: never throw from public APIs
- Lazy init: connect to Mongo only on first use
- Config via env only (avoid importing global config to prevent cycles)
- TTL-based retention (default 30 days) to keep the collection bounded

Environment variables:
- ALERTS_DB_ENABLED: "true/1/yes" to enable writes (fallback to METRICS_DB_ENABLED)
- MONGODB_URL: required when enabled
- DATABASE_NAME: DB name (default: code_keeper_bot)
- ALERTS_COLLECTION: Collection name (default: alerts_log)
- ALERTS_TTL_DAYS: TTL for documents (default: 30)

Public API:
- record_alert(alert_id, name, severity, summary, source) -> None
- count_alerts_since(since_dt) -> tuple[int, int]
- count_alerts_last_hours(hours=24) -> tuple[int, int]
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple
import hashlib
import os


def _is_true(val: Optional[str]) -> bool:
    return str(val or "").lower() in {"1", "true", "yes", "on"}


def _enabled() -> bool:
    if _is_true(os.getenv("DISABLE_DB")):
        return False
    # Prefer explicit ALERTS_DB_ENABLED, otherwise fall back to METRICS_DB_ENABLED
    return _is_true(os.getenv("ALERTS_DB_ENABLED")) or _is_true(os.getenv("METRICS_DB_ENABLED"))


_client = None  # type: ignore
_collection = None  # type: ignore
_init_failed = False


def _get_collection():  # pragma: no cover - exercised indirectly
    global _client, _collection, _init_failed
    if _collection is not None or _init_failed:
        return _collection

    if not _enabled():
        _init_failed = True
        return None

    try:
        try:
            from pymongo import MongoClient  # type: ignore
            from pymongo import ASCENDING  # type: ignore
        except Exception:
            _init_failed = True
            return None

        mongo_url = os.getenv("MONGODB_URL")
        if not mongo_url:
            _init_failed = True
            return None

        db_name = os.getenv("DATABASE_NAME") or "code_keeper_bot"
        coll_name = os.getenv("ALERTS_COLLECTION") or "alerts_log"

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
        # Best-effort ping
        try:
            _client.admin.command("ping")
        except Exception:
            pass

        # Ensure indexes (best-effort). TTL requires a Date field.
        try:
            try:
                ttl_days = int(os.getenv("ALERTS_TTL_DAYS", "30") or "30")
            except Exception:
                ttl_days = 30
            # TTL cannot be updated in-place; ignore errors if it already exists differently.
            if ttl_days > 0:
                _collection.create_index([("ts_dt", ASCENDING)], expireAfterSeconds=ttl_days * 24 * 3600)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            _collection.create_index([("_key", ASCENDING)], unique=True, sparse=True)  # type: ignore[attr-defined]
        except Exception:
            pass

        return _collection
    except Exception:
        _init_failed = True
        return None


def _build_key(alert_id: Optional[str], name: str, severity: str, summary: str, ts_dt: datetime) -> str:
    if alert_id:
        return f"id:{alert_id}"
    # Fallback: stable hash by minute bucket
    minute_bucket = ts_dt.replace(second=0, microsecond=0).isoformat()
    raw = "|".join([name.strip(), severity.strip().lower(), summary.strip(), minute_bucket])
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return f"h:{digest}"


def record_alert(
    *,
    alert_id: Optional[str],
    name: str,
    severity: str,
    summary: str = "",
    source: str = "",
) -> None:
    """Insert (or upsert via unique key) a single alert record.

    - When alert_id is provided, use it for de-duplication via a unique key.
    - Otherwise use a stable hash based on name/severity/summary/minute.
    """
    if not _enabled() or _init_failed:
        return
    try:
        coll = _get_collection()
        if coll is None:
            return
        now = datetime.now(timezone.utc)
        key = _build_key(alert_id, name or "", severity or "", summary or "", now)
        doc = {
            "ts_dt": now,
            "name": str(name or "alert"),
            "severity": str(severity or "info"),
            "summary": str(summary or ""),
            "source": str(source or ""),
            "_key": key,
        }
        if alert_id:
            doc["alert_id"] = str(alert_id)
        try:
            # Upsert by key (idempotent). Using update_one for better semantics with unique key.
            coll.update_one({"_key": key}, {"$setOnInsert": doc}, upsert=True)  # type: ignore[attr-defined]
        except Exception:
            # Fall back to insert (ignore dup errors silently)
            try:
                coll.insert_one(doc)  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        return


def count_alerts_since(since_dt: datetime) -> tuple[int, int]:
    """Return (total, critical) counts since the given datetime (UTC recommended)."""
    if not _enabled() or _init_failed:
        return 0, 0
    try:
        coll = _get_collection()
        if coll is None:
            return 0, 0
        total = int(coll.count_documents({"ts_dt": {"$gte": since_dt}}))  # type: ignore[attr-defined]
        critical = int(
            coll.count_documents({"ts_dt": {"$gte": since_dt}, "severity": {"$regex": "^critical$", "$options": "i"}})  # type: ignore[attr-defined]
        )
        return total, critical
    except Exception:
        return 0, 0


def count_alerts_last_hours(hours: int = 24) -> tuple[int, int]:
    if hours <= 0:
        return 0, 0
    since = datetime.now(timezone.utc) - timedelta(hours=int(hours))
    return count_alerts_since(since)
