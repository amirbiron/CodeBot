"""
MongoDB-backed Drill history storage (best-effort, fail-open).

Design goals:
- Fail-open: never throw from public APIs
- Lazy init: connect to Mongo only on first use
- TTL-based retention (default 90 days) to keep the collection bounded

Environment variables:
- DRILLS_DB_ENABLED: "true/1/yes" to enable writes (fallback to ALERTS_DB_ENABLED/METRICS_DB_ENABLED)
- DRILLS_COLLECTION: Collection name (default: drill_history)
- DRILLS_TTL_DAYS: TTL for documents (default: 90)
- MONGODB_URL, DATABASE_NAME: shared with alerts storage
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
import os


def _is_true(val: Optional[str]) -> bool:
    return str(val or "").lower() in {"1", "true", "yes", "on"}


def _enabled() -> bool:
    if _is_true(os.getenv("DRILLS_DB_ENABLED")):
        return True
    if _is_true(os.getenv("DISABLE_DB")):
        return False
    # Fall back to alerts DB flag (same Mongo) and then global metrics flag
    if _is_true(os.getenv("ALERTS_DB_ENABLED")):
        return True
    return _is_true(os.getenv("METRICS_DB_ENABLED"))


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

        mongo_url = os.getenv("MONGODB_URL") or "mongodb://localhost:27017"
        db_name = os.getenv("DATABASE_NAME") or "code_keeper_bot"
        coll_name = os.getenv("DRILLS_COLLECTION") or "drill_history"

        _client = MongoClient(
            mongo_url,
            maxPoolSize=10,
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
            pass

        # TTL index
        try:
            try:
                ttl_days = int(os.getenv("DRILLS_TTL_DAYS", "90") or "90")
            except Exception:
                ttl_days = 90
            if ttl_days > 0:
                _collection.create_index([("ts_dt", ASCENDING)], expireAfterSeconds=ttl_days * 24 * 3600)  # type: ignore[attr-defined]
        except Exception:
            pass
        # Unique drill_id
        try:
            _collection.create_index([("drill_id", ASCENDING)], unique=True, sparse=True)  # type: ignore[attr-defined]
        except Exception:
            pass
        # Sort index
        try:
            _collection.create_index([("started_at", ASCENDING)])  # type: ignore[attr-defined]
        except Exception:
            pass

        return _collection
    except Exception:
        _init_failed = True
        return None


def _isoformat_utc(value: Any) -> Optional[str]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        dt = value.replace(tzinfo=timezone.utc)
    else:
        try:
            dt = value.astimezone(timezone.utc)
        except Exception:
            dt = value.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _normalize_doc_for_json(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert non-JSON types (datetime) to serializable forms."""
    out = dict(doc or {})
    try:
        if "ts_dt" in out:
            ts_iso = _isoformat_utc(out.get("ts_dt"))
            if ts_iso:
                out["ts_dt"] = ts_iso
            else:
                # If something odd slips in, drop field to keep fail-open API behavior
                out.pop("ts_dt", None)
    except Exception:
        out.pop("ts_dt", None)
    return out


def record_drill(
    *,
    drill_id: str,
    scenario_id: str,
    started_at_iso: str,
    alert: Dict[str, Any],
    pipeline: Dict[str, Any],
    telegram_sent: bool,
    requested_by: Optional[str] = None,
) -> None:
    if not _enabled() or _init_failed:
        return
    try:
        coll = _get_collection()
        if coll is None:
            return
        now = datetime.now(timezone.utc)
        doc = {
            "ts_dt": now,
            "drill_id": str(drill_id or ""),
            "scenario_id": str(scenario_id or ""),
            "started_at": str(started_at_iso or ""),
            "requested_by": str(requested_by or ""),
            "alert": alert or {},
            "pipeline": pipeline or {},
            "telegram_sent": bool(telegram_sent),
        }
        try:
            coll.update_one({"drill_id": doc["drill_id"]}, {"$setOnInsert": doc}, upsert=True)  # type: ignore[attr-defined]
        except Exception:
            try:
                coll.insert_one(doc)  # type: ignore[attr-defined]
            except Exception:
                pass
    except Exception:
        return


def list_drills(limit: int = 20) -> List[Dict[str, Any]]:
    coll = _get_collection()
    if coll is None:
        return []
    try:
        lim = max(1, min(200, int(limit or 20)))
    except Exception:
        lim = 20
    try:
        cursor = (
            coll.find({}, {"_id": 0})  # type: ignore[attr-defined]
            .sort([("ts_dt", -1)])  # type: ignore[attr-defined]
            .limit(lim)  # type: ignore[attr-defined]
        )
        rows = list(cursor)
        return [_normalize_doc_for_json(doc) for doc in rows if isinstance(doc, dict)]
    except Exception:
        return []


def get_drill(drill_id: str) -> Optional[Dict[str, Any]]:
    coll = _get_collection()
    if coll is None:
        return None
    key = str(drill_id or "").strip()
    if not key:
        return None
    try:
        doc = coll.find_one({"drill_id": key}, {"_id": 0})  # type: ignore[attr-defined]
        if not isinstance(doc, dict):
            return None
        return _normalize_doc_for_json(doc)
    except Exception:
        return None

