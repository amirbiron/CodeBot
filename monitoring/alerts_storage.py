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
from typing import Any, Dict, List, Optional, Tuple
import hashlib
import os
import re


def _is_true(val: Optional[str]) -> bool:
    return str(val or "").lower() in {"1", "true", "yes", "on"}


def _enabled() -> bool:
    # Explicit opt-in wins over global disable to support tests and targeted writes
    if _is_true(os.getenv("ALERTS_DB_ENABLED")):
        return True
    if _is_true(os.getenv("DISABLE_DB")):
        return False
    # Fall back to metrics DB flag when explicit alerts flag is not set
    return _is_true(os.getenv("METRICS_DB_ENABLED"))


_client = None  # type: ignore
_collection = None  # type: ignore
_catalog_collection = None  # type: ignore
_init_failed = False

_SENSITIVE_DETAIL_KEYS = {
    "token",
    "password",
    "secret",
    "authorization",
    "auth",
    "email",
    "phone",
    "session",
    "cookie",
}
_ENDPOINT_HINT_KEYS = ("endpoint", "path", "route", "url", "request_path")
_ALERT_TYPE_HINT_KEYS = ("alert_type", "type", "category", "kind")
_DETAIL_TEXT_LIMIT = 512


def _safe_str(value: Any, *, limit: int = 256) -> str:
    try:
        text = str(value or "").strip()
    except Exception:
        text = ""
    if limit and len(text) > limit:
        return text[:limit]
    return text


def _sanitize_details(details: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(details, dict):
        return {}
    clean: Dict[str, Any] = {}
    for key, value in details.items():
        try:
            lk = str(key).lower()
        except Exception:
            continue
        if lk in _SENSITIVE_DETAIL_KEYS:
            continue
        if value is None:
            continue
        if isinstance(value, (int, float)):
            clean[str(key)] = value
            continue
        if isinstance(value, bool):
            clean[str(key)] = bool(value)
            continue
        clean[str(key)] = _safe_str(value, limit=_DETAIL_TEXT_LIMIT)
    return clean


def _extract_endpoint(details: Dict[str, Any]) -> Optional[str]:
    for key in _ENDPOINT_HINT_KEYS:
        try:
            value = details.get(key)
        except Exception:
            continue
        if value not in (None, ""):
            text = _safe_str(value, limit=256)
            if text:
                return text
    return None


def _extract_alert_type(name: str, details: Dict[str, Any]) -> Optional[str]:
    for key in _ALERT_TYPE_HINT_KEYS:
        try:
            value = details.get(key)
        except Exception:
            continue
        if value not in (None, ""):
            return _safe_str(value, limit=128).lower()
    if name and name.lower() == "deployment_event":
        return "deployment_event"
    return None


def _extract_duration(details: Dict[str, Any]) -> Optional[float]:
    for key in ("duration_seconds", "duration", "duration_secs", "duration_ms"):
        try:
            value = details.get(key)
        except Exception:
            continue
        if value in (None, ""):
            continue
        try:
            num = float(value)
        except Exception:
            continue
        if key.endswith("_ms"):
            num = num / 1000.0
        if num >= 0:
            return num
    return None


def _build_search_blob(name: str, summary: str, details: Dict[str, Any]) -> str:
    parts = [name or "", summary or ""]
    if details:
        for key, value in details.items():
            try:
                parts.append(f"{key}:{value}")
            except Exception:
                continue
    text = " | ".join(part for part in parts if part)
    return _safe_str(text, limit=2048)


def _build_time_filter(start_dt: Optional[datetime], end_dt: Optional[datetime]) -> Dict[str, Any]:
    if not start_dt and not end_dt:
        return {}
    match: Dict[str, Any] = {}
    window: Dict[str, Any] = {}
    if start_dt:
        window["$gte"] = start_dt
    if end_dt:
        window["$lte"] = end_dt
    if window:
        match["ts_dt"] = window
    return match


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

        # Allow tests/environments without explicit URL to fall back to localhost.
        # This keeps public APIs fail-open and enables unit-test fakes for pymongo.
        mongo_url = os.getenv("MONGODB_URL") or "mongodb://localhost:27017"

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


def _get_catalog_collection():  # pragma: no cover - exercised indirectly
    """Return (and lazily create) the alert types catalog collection."""
    global _catalog_collection
    if _catalog_collection is not None or _init_failed:
        return _catalog_collection
    # Ensure base client is initialized (same DB/cluster settings)
    try:
        coll = _get_collection()
        if coll is None:
            return None
    except Exception:
        return None
    try:
        # Reuse the same client/db, create a separate collection
        db_name = os.getenv("DATABASE_NAME") or "code_keeper_bot"
        catalog_name = os.getenv("ALERT_TYPES_CATALOG_COLLECTION") or "alert_types_catalog"
        db = _client[db_name]  # type: ignore[index]
        _catalog_collection = db[catalog_name]
        # Best-effort indexes
        try:
            from pymongo import ASCENDING  # type: ignore

            _catalog_collection.create_index([("alert_type", ASCENDING)], unique=True)  # type: ignore[attr-defined]
            _catalog_collection.create_index([("last_seen_dt", ASCENDING)])  # type: ignore[attr-defined]
        except Exception:
            pass
        return _catalog_collection
    except Exception:
        return None


def _isoformat_utc(value: Optional[datetime]) -> Optional[str]:
    """Return ISO string with UTC tzinfo for Mongo datetimes."""
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


def _build_key(alert_id: Optional[str], name: str, severity: str, summary: str, ts_dt: datetime) -> str:
    if alert_id:
        return f"id:{alert_id}"
    # Fallback: stable hash by minute bucket
    minute_bucket = ts_dt.replace(second=0, microsecond=0).isoformat()
    raw = "|".join([name.strip(), severity.strip().lower(), summary.strip(), minute_bucket])
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"h:{digest}"


def record_alert(
    *,
    alert_id: Optional[str],
    name: str,
    severity: str,
    summary: str = "",
    source: str = "",
    silenced: bool = False,
    details: Optional[Dict[str, Any]] = None,
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
        clean_details = _sanitize_details(details)
        endpoint = _extract_endpoint(clean_details) if clean_details else None
        alert_type = _extract_alert_type(str(name or ""), clean_details)
        duration_seconds = _extract_duration(clean_details)
        search_blob = _build_search_blob(str(name or ""), str(summary or ""), clean_details)

        doc = {
            "ts_dt": now,
            "name": str(name or "alert"),
            "severity": str(severity or "info").lower(),
            "summary": str(summary or ""),
            "source": str(source or ""),
            "_key": key,
            "search_blob": search_blob,
        }
        # Transparency: mark whether this alert was silenced at dispatch time
        try:
            doc["silenced"] = bool(silenced)
        except Exception:
            doc["silenced"] = False
        if clean_details:
            doc["details"] = clean_details
        if endpoint:
            doc["endpoint"] = endpoint
        if alert_type:
            doc["alert_type"] = alert_type
        if duration_seconds is not None:
            doc["duration_seconds"] = float(duration_seconds)
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

        # --- Catalog (Registry): persist observed alert_type forever (best-effort) ---
        try:
            # Do not pollute catalog with drills
            if clean_details and bool(clean_details.get("is_drill")):
                return
        except Exception:
            pass
        try:
            if alert_type:
                _upsert_alert_type_catalog(
                    alert_type=alert_type,
                    name=str(name or "alert"),
                    summary=str(summary or ""),
                    seen_dt=now,
                )
        except Exception:
            pass
    except Exception:
        return


def _upsert_alert_type_catalog(
    *,
    alert_type: str,
    name: str,
    summary: str,
    seen_dt: datetime,
) -> None:
    coll = _get_catalog_collection()
    if coll is None:
        return
    key = _safe_str(alert_type, limit=128).lower()
    if not key:
        return
    now = seen_dt if isinstance(seen_dt, datetime) else datetime.now(timezone.utc)
    payload = {
        "alert_type": key,
        "last_seen_dt": now,
        "last_seen_name": _safe_str(name, limit=128),
        "last_seen_summary": _safe_str(summary, limit=256),
        "updated_at": now,
    }
    try:
        coll.update_one(
            {"alert_type": key},
            {
                "$setOnInsert": {"first_seen_dt": now, "created_at": now},
                "$set": payload,
                "$inc": {"total_count": 1},
            },
            upsert=True,
        )  # type: ignore[attr-defined]
    except Exception:
        return


def fetch_alert_type_catalog(
    *,
    min_total_count: int = 1,
    limit: int = 5000,
) -> List[Dict[str, Any]]:
    """Return catalog of all observed alert types (fail-open).

    Each row includes:
      alert_type, total_count, first_seen_dt, last_seen_dt, sample_name, sample_title
    """
    coll = _get_catalog_collection()
    if coll is None:
        return []
    try:
        min_total = int(min_total_count)
    except Exception:
        min_total = 1
    min_total = max(1, min_total)
    try:
        lim = int(limit)
    except Exception:
        lim = 5000
    lim = max(1, min(50_000, lim))
    try:
        match: Dict[str, Any] = {"total_count": {"$gte": min_total}}
        cursor = (
            coll.find(
                match,
                {
                    "_id": 0,
                    "alert_type": 1,
                    "total_count": 1,
                    "first_seen_dt": 1,
                    "last_seen_dt": 1,
                    "last_seen_name": 1,
                    "last_seen_summary": 1,
                },
            )  # type: ignore[attr-defined]
            .sort([("last_seen_dt", -1)])  # type: ignore[attr-defined]
            .limit(lim)  # type: ignore[attr-defined]
        )
    except Exception:
        return []
    out: List[Dict[str, Any]] = []
    try:
        for doc in cursor:
            try:
                a_type = _safe_str(doc.get("alert_type"), limit=128).lower()
                if not a_type:
                    continue
                out.append(
                    {
                        "alert_type": a_type,
                        "count": int(doc.get("total_count", 0) or 0),
                        "first_seen_dt": doc.get("first_seen_dt"),
                        "last_seen_dt": doc.get("last_seen_dt"),
                        "sample_name": _safe_str(doc.get("last_seen_name"), limit=128),
                        "sample_title": _safe_str(doc.get("last_seen_summary"), limit=256),
                    }
                )
            except Exception:
                continue
    except Exception:
        return []
    return out


def fetch_alerts_by_type(
    *,
    alert_type: str,
    limit: int = 100,
    include_details: bool = True,
) -> List[Dict[str, Any]]:
    """Fetch recent alerts of a specific type with Sentry details.

    Returns a list of dicts, for example::

        {
          "alert_id": str,
          "ts_dt": datetime,
          "name": str,
          "summary": str,
          "sentry_issue_id": Optional[str],
          "sentry_permalink": Optional[str],
          "sentry_short_id": Optional[str],
        }
    """
    coll = _get_collection()
    if coll is None:
        return []

    normalized_type = _safe_str(alert_type, limit=128).lower()
    if not normalized_type:
        return []

    try:
        limit_int = max(1, min(500, int(limit)))
    except Exception:
        limit_int = 100

    safe_pattern = re.escape(normalized_type)
    match = {
        "alert_type": {"$regex": f"^{safe_pattern}$", "$options": "i"},
        "details.is_drill": {"$ne": True},
    }

    projection = {
        "_id": 0,
        "alert_id": 1,
        "ts_dt": 1,
        "name": 1,
        "summary": 1,
    }

    if include_details:
        projection["details.sentry_issue_id"] = 1
        projection["details.sentry_permalink"] = 1
        projection["details.sentry_short_id"] = 1
        projection["details.error_signature"] = 1

    try:
        cursor = coll.find(match, projection).sort([("ts_dt", -1)]).limit(limit_int)  # type: ignore[attr-defined]
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for doc in cursor:
        try:
            details = doc.get("details") or {}
            out.append(
                {
                    "alert_id": str(doc.get("alert_id") or ""),
                    "ts_dt": doc.get("ts_dt"),
                    "name": _safe_str(doc.get("name"), limit=128),
                    "summary": _safe_str(doc.get("summary"), limit=256),
                    "sentry_issue_id": _safe_str(details.get("sentry_issue_id"), limit=64),
                    "sentry_permalink": _safe_str(details.get("sentry_permalink"), limit=512),
                    "sentry_short_id": _safe_str(details.get("sentry_short_id"), limit=32),
                    "error_signature": _safe_str(details.get("error_signature"), limit=128),
                }
            )
        except Exception:
            continue
    return out


def count_alerts_since(since_dt: datetime) -> tuple[int, int]:
    """Return (total, critical) counts since the given datetime (UTC recommended)."""
    if not _enabled() or _init_failed:
        return 0, 0
    try:
        coll = _get_collection()
        if coll is None:
            return 0, 0
        match: Dict[str, Any] = {"ts_dt": {"$gte": since_dt}}
        # Default: exclude Drill alerts from stats to prevent metric pollution
        match["details.is_drill"] = {"$ne": True}
        total = int(coll.count_documents(match))  # type: ignore[attr-defined]
        critical = int(
            coll.count_documents(
                {
                    **match,
                    "severity": {"$regex": "^critical$", "$options": "i"},
                }
            )  # type: ignore[attr-defined]
        )
        return total, critical
    except Exception:
        return 0, 0


def count_alerts_last_hours(hours: int = 24) -> tuple[int, int]:
    if hours <= 0:
        return 0, 0
    since = datetime.now(timezone.utc) - timedelta(hours=int(hours))
    return count_alerts_since(since)


def list_recent_alert_ids(limit: int = 10) -> List[str]:
    """Return recent alert identifiers from the DB (fail-open).

    Preference order: document ``alert_id`` when present, otherwise the
    stable unique ``_key`` used for de-duplication. Results are ordered by
    ``ts_dt`` descending and truncated to ``limit``.
    """
    if not _enabled() or _init_failed:
        return []
    try:
        coll = _get_collection()
        if coll is None:
            return []
        try:
            # Projection keeps payload small; sorting by time desc
            cursor = (
                coll.find({}, {"alert_id": 1, "_key": 1, "ts_dt": 1})  # type: ignore[attr-defined]
                .sort([("ts_dt", -1)])  # type: ignore[attr-defined]
                .limit(max(1, min(200, int(limit or 10))))  # type: ignore[attr-defined]
            )
        except Exception:
            return []
        out: List[str] = []
        try:
            for doc in cursor:  # type: ignore[assignment]
                try:
                    ident = doc.get("alert_id") or doc.get("_key")
                    if ident:
                        out.append(str(ident))
                except Exception:
                    continue
        except Exception:
            return []
        return out
    except Exception:
        return []


def fetch_alerts(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    severity: Optional[str] = None,
    alert_type: Optional[str] = None,
    endpoint: Optional[str] = None,
    search: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> Tuple[List[Dict[str, Any]], int]:
    """Return paginated alert documents filtered by the provided criteria."""
    coll = _get_collection()
    if coll is None:
        return [], 0

    try:
        per_page = max(1, min(200, int(per_page)))
    except Exception:
        per_page = 50
    try:
        page = max(1, int(page))
    except Exception:
        page = 1
    skip = (page - 1) * per_page

    match = _build_time_filter(start_dt, end_dt)
    if severity:
        match["severity"] = str(severity).lower()
    if alert_type:
        match["alert_type"] = str(alert_type).lower()
    if endpoint:
        match["endpoint"] = str(endpoint)
    if search:
        pattern = _safe_str(search, limit=256)
        if pattern:
            match["$or"] = [
                {"name": {"$regex": pattern, "$options": "i"}},
                {"summary": {"$regex": pattern, "$options": "i"}},
                {"search_blob": {"$regex": pattern, "$options": "i"}},
            ]

    projection = {
        "_id": 0,
        "ts_dt": 1,
        "name": 1,
        "severity": 1,
        "summary": 1,
        "details": 1,
        "duration_seconds": 1,
        "alert_type": 1,
        "endpoint": 1,
        "source": 1,
        "silenced": 1,
    }

    try:
        cursor = (
            coll.find(match, projection)  # type: ignore[attr-defined]
            .sort("ts_dt", -1)  # type: ignore[attr-defined]
            .skip(skip)  # type: ignore[attr-defined]
            .limit(per_page)  # type: ignore[attr-defined]
        )
    except Exception:
        return [], 0

    alerts: List[Dict[str, Any]] = []
    for doc in cursor:
        ts = doc.get("ts_dt")
        ts_iso = _isoformat_utc(ts)
        alerts.append(
            {
                "timestamp": ts_iso,
                "name": doc.get("name"),
                "severity": doc.get("severity"),
                "summary": doc.get("summary"),
                "metadata": doc.get("details") or {},
                "duration_seconds": doc.get("duration_seconds"),
                "alert_type": doc.get("alert_type"),
                "endpoint": doc.get("endpoint"),
                "source": doc.get("source"),
                "silenced": bool(doc.get("silenced", False)),
            }
        )

    try:
        total = int(coll.count_documents(match))  # type: ignore[attr-defined]
    except Exception:
        total = len(alerts)
    return alerts, total


def aggregate_alert_type_stats(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    min_count: int = 1,
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Aggregate active alert_types with counts and last_seen (exclude drills).

    Returns a list of dicts:
      { "alert_type": str, "count": int, "last_seen_dt": datetime, "sample_title": str, "sample_name": str }

    Fail-open: returns [] on any error / when storage is unavailable.
    """
    coll = _get_collection()
    if coll is None:
        return []

    try:
        min_count_int = int(min_count)
    except Exception:
        min_count_int = 1
    min_count_int = max(1, min_count_int)

    try:
        limit_int = int(limit)
    except Exception:
        limit_int = 500
    limit_int = max(1, min(2000, limit_int))

    match = _build_time_filter(start_dt, end_dt)
    # Default: exclude Drill alerts from analytics helpers
    match["details.is_drill"] = {"$ne": True}
    # Only consider documents with a real alert_type (avoid grouping null/empty)
    match["alert_type"] = {"$type": "string", "$ne": ""}

    pipeline = [
        {"$match": match},
        {"$sort": {"ts_dt": -1}},
        {
            "$group": {
                "_id": {"$toLower": "$alert_type"},
                "count": {"$sum": 1},
                "last_seen_dt": {"$first": "$ts_dt"},
                "sample_title": {"$first": "$summary"},
                "sample_name": {"$first": "$name"},
            }
        },
        {"$match": {"count": {"$gte": min_count_int}}},
        {"$sort": {"count": -1, "last_seen_dt": -1}},
        {"$limit": limit_int},
    ]

    try:
        rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for row in rows:
        try:
            alert_type = _safe_str(row.get("_id"), limit=128).lower()
            if not alert_type:
                continue
            last_seen_dt = row.get("last_seen_dt")
            if not isinstance(last_seen_dt, datetime):
                continue
            out.append(
                {
                    "alert_type": alert_type,
                    "count": int(row.get("count", 0) or 0),
                    "last_seen_dt": last_seen_dt,
                    "sample_title": _safe_str(row.get("sample_title"), limit=256),
                    "sample_name": _safe_str(row.get("sample_name"), limit=128),
                }
            )
        except Exception:
            continue
    return out


def aggregate_alert_summary(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
) -> Dict[str, int]:
    """Aggregate alert counts by severity and deployment flag."""
    coll = _get_collection()
    if coll is None:
        return {"total": 0, "critical": 0, "anomaly": 0, "deployment": 0}
    match = _build_time_filter(start_dt, end_dt)
    # Default: exclude Drill alerts from summary/analytics
    match["details.is_drill"] = {"$ne": True}
    pipeline = [
        {"$match": match},
        {
            "$group": {
                "_id": None,
                "total": {"$sum": 1},
                "critical": {
                    "$sum": {
                        "$cond": [{"$eq": ["$severity", "critical"]}, 1, 0],
                    }
                },
                "anomaly": {
                    "$sum": {
                        "$cond": [{"$eq": ["$severity", "anomaly"]}, 1, 0],
                    }
                },
                "deployment": {
                    "$sum": {
                        "$cond": [
                            {
                                "$or": [
                                    {"$eq": ["$alert_type", "deployment_event"]},
                                    {"$eq": ["$name", "deployment_event"]},
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
            }
        },
    ]
    try:
        result = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]
        if not result:
            return {"total": 0, "critical": 0, "anomaly": 0, "deployment": 0}
        doc = result[0]
        return {
            "total": int(doc.get("total", 0)),
            "critical": int(doc.get("critical", 0)),
            "anomaly": int(doc.get("anomaly", 0)),
            "deployment": int(doc.get("deployment", 0)),
        }
    except Exception:
        return {"total": 0, "critical": 0, "anomaly": 0, "deployment": 0}


def fetch_alert_timestamps(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    severity: Optional[str] = None,
    alert_type: Optional[str] = None,
    limit: int = 500,
) -> List[datetime]:
    """Return recent alert timestamps matching the given filters."""
    coll = _get_collection()
    if coll is None:
        return []
    match = _build_time_filter(start_dt, end_dt)
    # Default: exclude Drill alerts from analytics helpers
    match["details.is_drill"] = {"$ne": True}
    if severity:
        match["severity"] = str(severity).lower()
    if alert_type:
        match["alert_type"] = str(alert_type).lower()
    try:
        cursor = (
            coll.find(match, {"ts_dt": 1})  # type: ignore[attr-defined]
            .sort("ts_dt", -1)  # type: ignore[attr-defined]
            .limit(max(1, limit))  # type: ignore[attr-defined]
        )
    except Exception:
        return []
    out: List[datetime] = []
    for doc in cursor:
        ts = doc.get("ts_dt")
        if isinstance(ts, datetime):
            out.append(ts)
    return out


def aggregate_alert_timeseries(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    granularity_seconds: int,
) -> List[Dict[str, Any]]:
    """Aggregate alert counts per severity over time buckets."""
    coll = _get_collection()
    if coll is None:
        return []
    try:
        bucket_seconds = max(1, int(granularity_seconds or 60))
    except Exception:
        bucket_seconds = 3600
    bucket_ms = bucket_seconds * 1000
    match = _build_time_filter(start_dt, end_dt)
    # Default: exclude Drill alerts from timeseries to prevent metric pollution
    match["details.is_drill"] = {"$ne": True}
    pipeline = [
        {"$match": match},
        {
            "$project": {
                "bucket": {
                    "$toDate": {
                        "$subtract": [
                            {"$toLong": "$ts_dt"},
                            {"$mod": [{"$toLong": "$ts_dt"}, bucket_ms]},
                        ]
                    }
                },
                "severity": {
                    "$toLower": {"$ifNull": ["$severity", "info"]},
                },
            }
        },
        {
            "$group": {
                "_id": {"bucket": "$bucket", "severity": "$severity"},
                "count": {"$sum": 1},
            }
        },
        {
            "$group": {
                "_id": "$_id.bucket",
                "counts": {
                    "$push": {
                        "severity": "$_id.severity",
                        "count": "$count",
                    }
                },
                "total": {"$sum": "$count"},
            }
        },
        {"$sort": {"_id": 1}},
    ]
    try:
        rows = list(coll.aggregate(pipeline))  # type: ignore[attr-defined]
    except Exception:
        return []

    result: List[Dict[str, Any]] = []
    for row in rows:
        bucket = row.get("_id")
        ts_iso = _isoformat_utc(bucket)
        counts = {"critical": 0, "anomaly": 0, "warning": 0, "info": 0}
        for entry in row.get("counts", []):
            severity = str(entry.get("severity") or "info").lower()
            if severity not in counts:
                if severity.startswith("crit"):
                    severity = "critical"
                elif severity.startswith("warn"):
                    severity = "warning"
                elif severity.startswith("anom"):
                    severity = "anomaly"
                else:
                    severity = "info"
            counts[severity] += int(entry.get("count", 0))
        counts["total"] = int(row.get("total", 0))
        counts["timestamp"] = ts_iso
        result.append(counts)
    return result
