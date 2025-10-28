"""
Mongo-backed alert silences for ChatOps.

Goals:
- Fail-open: never raise; return safe defaults
- Lazy init with env-only config (avoid global config import cycles)
- TTL on until_ts so expired silences auto-clean
- Active flag to allow manual unsilence before TTL

ENV:
- ALERTS_DB_ENABLED or METRICS_DB_ENABLED: enable DB access
- MONGODB_URL, DATABASE_NAME
- ALERTS_SILENCES_COLLECTION (default: alerts_silences)
- SILENCE_MAX_DAYS (default: 7)
- SILENCES_MAX_ACTIVE (default: 50)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import os
import re
import uuid


def _is_true(val: Optional[str]) -> bool:
    return str(val or "").lower() in {"1", "true", "yes", "on"}


def _enabled() -> bool:
    if _is_true(os.getenv("DISABLE_DB")):
        return False
    return _is_true(os.getenv("ALERTS_DB_ENABLED")) or _is_true(os.getenv("METRICS_DB_ENABLED"))


_client = None  # type: ignore
_collection = None  # type: ignore
_init_failed = False


def _get_collection():  # pragma: no cover
    global _client, _collection, _init_failed
    if _collection is not None or _init_failed:
        return _collection
    if not _enabled():
        _init_failed = True
        return None
    try:
        try:
            from pymongo import MongoClient, ASCENDING  # type: ignore
        except Exception:
            _init_failed = True
            return None
        mongo_url = os.getenv("MONGODB_URL")
        db_name = os.getenv("DATABASE_NAME") or "code_keeper_bot"
        coll_name = os.getenv("ALERTS_SILENCES_COLLECTION") or "alerts_silences"
        client_kwargs = dict(
            maxPoolSize=20,
            minPoolSize=0,
            serverSelectionTimeoutMS=2000,
            socketTimeoutMS=5000,
            connectTimeoutMS=2000,
            retryWrites=True,
            retryReads=True,
            tz_aware=True,
        )
        # Allow operation without explicit MONGODB_URL (useful for tests with stubbed MongoClient)
        try:
            if mongo_url:
                _client = MongoClient(mongo_url, **client_kwargs)
            else:
                # Try without URI; fall back to localhost if signature requires a URI
                try:
                    _client = MongoClient(**client_kwargs)
                except TypeError:
                    _client = MongoClient("mongodb://localhost:27017", **client_kwargs)
        except Exception:
            _init_failed = True
            return None
        db = _client[db_name]
        _collection = db[coll_name]
        try:
            _client.admin.command("ping")
        except Exception:
            pass
        # Indexes: TTL on until_ts, plus pattern and active
        try:
            _collection.create_index([("until_ts", ASCENDING)], expireAfterSeconds=0)  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            _collection.create_index([("pattern", ASCENDING)])  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            _collection.create_index([("active", ASCENDING)])  # type: ignore[attr-defined]
        except Exception:
            pass
        try:
            _collection.create_index([("severity", ASCENDING)])  # type: ignore[attr-defined]
        except Exception:
            pass
        return _collection
    except Exception:
        _init_failed = True
        return None


def parse_duration_to_seconds(text: str, *, max_days: int = 7) -> Optional[int]:
    """Parse duration like "30s", "5m", "2h", "3d" to seconds, bounded by max_days.
    Returns None on invalid.
    """
    try:
        s = (text or "").strip().lower()
        if not s:
            return None
        match = re.fullmatch(r"\s*(\d+)\s*([smhd])\s*", s)
        if not match:
            return None
        num = int(match.group(1))
        unit = match.group(2)
        if unit == "s":
            seconds = num
        elif unit == "m":
            seconds = num * 60
        elif unit == "h":
            seconds = num * 3600
        else:
            seconds = num * 86400
        max_seconds = max(1, int(max_days or 7)) * 86400
        if seconds <= 0:
            return None
        if seconds > max_seconds:
            return max_seconds
        return seconds
    except Exception:
        return None


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _max_active_allowed() -> int:
    try:
        return max(1, int(os.getenv("SILENCES_MAX_ACTIVE", "50") or 50))
    except Exception:
        return 50


def create_silence(
    *,
    pattern: str,
    duration_seconds: int,
    created_by: int,
    reason: str = "",
    severity: Optional[str] = None,
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """Create a new active silence. Returns stored document on success, else None."""
    if not _enabled() or _init_failed:
        return None
    try:
        patt = (pattern or "").strip()
        if not patt:
            return None
        # Guard against overly broad patterns unless forced
        dangerous = {".*", "^.*$", "(?s).*", ".+", "^.+$"}
        if patt in dangerous and not force:
            return None
        coll = _get_collection()
        if coll is None:
            return None
        # Limit active silences
        now = _now_dt()
        active_count = int(coll.count_documents({"active": True, "until_ts": {"$gte": now}}))  # type: ignore[attr-defined]
        if active_count >= _max_active_allowed():
            return None
        # Normalize severity
        sev = (severity or "").strip().lower() or None
        # Bound duration to SILENCE_MAX_DAYS
        try:
            max_days = int(os.getenv("SILENCE_MAX_DAYS", "7") or 7)
        except Exception:
            max_days = 7
        max_seconds = max(1, max_days) * 86400
        dur = max(1, int(duration_seconds or 0))
        if dur > max_seconds:
            dur = max_seconds
        until = now + timedelta(seconds=dur)
        doc = {
            "_id": uuid.uuid4().hex,
            "pattern": patt,
            "severity": sev,
            "created_by": int(created_by or 0),
            "created_at": now,
            "until_ts": until,
            "reason": str(reason or ""),
            "active": True,
        }
        try:
            coll.insert_one(doc)  # type: ignore[attr-defined]
        except Exception:
            return None
        return doc
    except Exception:
        return None


def _iter_active(coll) -> List[Dict[str, Any]]:
    try:
        now = _now_dt()
        cursor = coll.find({"active": True, "until_ts": {"$gte": now}}).sort("until_ts", 1)  # type: ignore[attr-defined]
        return list(cursor)
    except Exception:
        return []


def is_silenced(name: str, severity: Optional[str] = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Return (True, silence_doc) if any active silence matches alert name and optional severity."""
    if not _enabled() or _init_failed:
        return False, None
    try:
        coll = _get_collection()
        if coll is None:
            return False, None
        items = _iter_active(coll)
        if not items:
            return False, None
        sev_in = (severity or "").strip().lower()
        for it in items:
            try:
                patt = str(it.get("pattern") or "")
                sev = (it.get("severity") or "").strip().lower()
                if sev and sev_in and sev != sev_in:
                    continue
                if patt:
                    try:
                        if re.search(patt, name or "", flags=re.IGNORECASE):
                            return True, it
                    except re.error:
                        # Invalid regex in DB: fall back to exact compare
                        if patt.lower() == (name or "").lower():
                            return True, it
            except Exception:
                continue
        return False, None
    except Exception:
        return False, None


def unsilence_by_id(silence_id: str) -> bool:
    if not _enabled() or _init_failed:
        return False
    try:
        coll = _get_collection()
        if coll is None:
            return False
        res = coll.update_one({"_id": str(silence_id)}, {"$set": {"active": False}})  # type: ignore[attr-defined]
        try:
            return bool(getattr(res, "modified_count", 0) or getattr(res, "matched_count", 0))
        except Exception:
            return False
    except Exception:
        return False


def unsilence_by_pattern(pattern: str) -> int:
    if not _enabled() or _init_failed:
        return 0
    try:
        coll = _get_collection()
        if coll is None:
            return 0
        res = coll.update_many({"pattern": str(pattern or ""), "active": True}, {"$set": {"active": False}})  # type: ignore[attr-defined]
        try:
            return int(getattr(res, "modified_count", 0) or 0)
        except Exception:
            return 0
    except Exception:
        return 0


def list_active_silences(limit: int = 50) -> List[Dict[str, Any]]:
    if not _enabled() or _init_failed:
        return []
    try:
        coll = _get_collection()
        if coll is None:
            return []
        items = _iter_active(coll)
        if not items:
            return []
        return items[: max(1, int(limit or 50))]
    except Exception:
        return []
