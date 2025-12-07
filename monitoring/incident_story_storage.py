from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    from pymongo import ASCENDING, DESCENDING, MongoClient

    _HAVE_PYMONGO = True
except Exception:  # pragma: no cover - pymongo optional in tests
    MongoClient = None  # type: ignore
    ASCENDING = 1  # type: ignore
    DESCENDING = -1  # type: ignore
    _HAVE_PYMONGO = False


_CLIENT = None  # type: ignore
_COLLECTION = None  # type: ignore
_INIT_FAILED = False

_FILE_PATH = Path(os.getenv("INCIDENT_STORY_FILE", "tmp/incident_stories.json"))
_FILE_LOCK = threading.Lock()

_TRUTHY = {"1", "true", "yes", "on"}


def _is_true(value: Optional[str]) -> bool:
    return str(value or "").strip().lower() in _TRUTHY


def _db_enabled() -> bool:
    if _is_true(os.getenv("DISABLE_DB")):
        return False
    if _is_true(os.getenv("INCIDENT_STORY_DB_ENABLED")):
        return True
    if _is_true(os.getenv("ALERTS_DB_ENABLED")):
        return True
    if _is_true(os.getenv("METRICS_DB_ENABLED")):
        return True
    return False


def _ensure_file_store() -> None:
    _FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not _FILE_PATH.exists():
        _FILE_PATH.write_text("[]", encoding="utf-8")


def _load_file_store() -> List[Dict[str, Any]]:
    _ensure_file_store()
    with _FILE_LOCK:
        try:
            text = _FILE_PATH.read_text(encoding="utf-8")
            data = json.loads(text or "[]")
            if isinstance(data, list):
                return [d for d in data if isinstance(d, dict)]
        except Exception:
            pass
    return []


def _write_file_store(entries: Iterable[Dict[str, Any]]) -> None:
    _ensure_file_store()
    with _FILE_LOCK:
        try:
            _FILE_PATH.write_text(json.dumps(list(entries), ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        try:
            dt = dt.astimezone(timezone.utc)
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _isoformat(dt: Optional[datetime]) -> Optional[str]:
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        try:
            dt = dt.astimezone(timezone.utc)
        except Exception:
            dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _serialize_doc(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(doc, dict):
        return None
    payload = dict(doc)
    for key in ("_id",):
        payload.pop(key, None)
    for field in ("created_at", "updated_at", "window_start_dt", "window_end_dt"):
        if isinstance(payload.get(field), datetime):
            payload[field] = _isoformat(payload.get(field))
    if "window_start_dt" in payload:
        payload.setdefault("time_window", {})
        if isinstance(payload["time_window"], dict):
            payload["time_window"].setdefault("start", payload.pop("window_start_dt"))
        else:
            payload["time_window"] = {"start": payload.pop("window_start_dt")}
    if "window_end_dt" in payload:
        payload.setdefault("time_window", {})
        if isinstance(payload["time_window"], dict):
            payload["time_window"].setdefault("end", payload.pop("window_end_dt"))
        else:
            payload["time_window"] = {"end": payload.pop("window_end_dt")}
    return payload


def _normalize_story_doc(story: Dict[str, Any]) -> Dict[str, Any]:
    doc = dict(story or {})
    doc.setdefault("story_id", doc.get("id") or uuid.uuid4().hex)
    doc.setdefault("created_at", _isoformat(datetime.now(timezone.utc)))
    doc.setdefault("updated_at", _isoformat(datetime.now(timezone.utc)))
    doc.setdefault("logs", [])
    doc.setdefault("what_we_did", {})
    doc.setdefault("what_we_saw", {})
    time_window = doc.get("time_window") or {}
    if not isinstance(time_window, dict):
        time_window = {}
    doc["time_window"] = time_window
    start_dt = _parse_iso(time_window.get("start"))
    end_dt = _parse_iso(time_window.get("end"))
    doc["window_start_dt"] = start_dt or datetime.now(timezone.utc)
    doc["window_end_dt"] = end_dt or doc["window_start_dt"]
    doc.setdefault("alert_uid", "")
    doc.setdefault("alert_name", "")
    doc.setdefault("alert_timestamp", time_window.get("start"))
    return doc


def _get_collection():
    global _CLIENT, _COLLECTION, _INIT_FAILED
    if _COLLECTION is not None or _INIT_FAILED:
        return _COLLECTION
    if not _db_enabled() or not _HAVE_PYMONGO:
        _INIT_FAILED = True
        return None
    mongo_url = os.getenv("MONGODB_URL")
    if not mongo_url:
        _INIT_FAILED = True
        return None
    db_name = os.getenv("DATABASE_NAME") or "code_keeper_bot"
    coll_name = os.getenv("INCIDENT_STORIES_COLLECTION") or "incident_stories"
    try:
        _CLIENT = MongoClient(
            mongo_url,
            maxPoolSize=20,
            minPoolSize=0,
            serverSelectionTimeoutMS=2000,
            socketTimeoutMS=5000,
            connectTimeoutMS=2000,
            retryWrites=True,
            retryReads=True,
            tz_aware=True,
        )
        db = _CLIENT[db_name]
        _COLLECTION = db[coll_name]
        try:
            _COLLECTION.create_index([("alert_uid", ASCENDING)], unique=True)  # type: ignore[attr-defined]
            _COLLECTION.create_index([("story_id", ASCENDING)], unique=True)  # type: ignore[attr-defined]
            _COLLECTION.create_index([("window_start_dt", DESCENDING)])  # type: ignore[attr-defined]
        except Exception:
            pass
        return _COLLECTION
    except Exception:
        _INIT_FAILED = True
        return None


def save_story(story: Dict[str, Any]) -> Dict[str, Any]:
    doc = _normalize_story_doc(story)
    collection = _get_collection()
    now = datetime.now(timezone.utc)
    doc["updated_at"] = now
    if collection is None:
        entries = _load_file_store()
        updated = []
        replaced = False
        for entry in entries:
            entry_id = entry.get("story_id")
            if entry_id == doc["story_id"] or entry.get("alert_uid") == doc.get("alert_uid"):
                merged = dict(entry)
                merged.update(doc)
                merged["updated_at"] = _isoformat(now)
                merged.setdefault("created_at", entry.get("created_at") or _isoformat(now))
                updated.append(merged)
                replaced = True
            else:
                updated.append(entry)
        if not replaced:
            doc["created_at"] = _isoformat(now)
            doc["updated_at"] = _isoformat(now)
            updated.append(doc)
        _write_file_store(updated)
        return doc

    lookup_filter: Dict[str, Any] = {"alert_uid": doc.get("alert_uid")}
    if doc.get("story_id"):
        lookup_filter = {"$or": [{"story_id": doc["story_id"]}, {"alert_uid": doc.get("alert_uid")}]}
    try:
        existing = collection.find_one(lookup_filter)  # type: ignore[attr-defined]
    except Exception:
        existing = None
    payload = dict(doc)
    payload["created_at"] = existing.get("created_at") if existing else now
    payload["updated_at"] = now
    payload["window_start_dt"] = doc.get("window_start_dt") or now
    payload["window_end_dt"] = doc.get("window_end_dt") or now
    try:
        if existing and existing.get("_id"):
            collection.update_one({"_id": existing["_id"]}, {"$set": payload}, upsert=False)  # type: ignore[attr-defined]
            stored = collection.find_one({"_id": existing["_id"]})  # type: ignore[attr-defined]
        else:
            res = collection.insert_one(payload)  # type: ignore[attr-defined]
            stored = collection.find_one({"_id": res.inserted_id})  # type: ignore[attr-defined]
    except Exception:
        stored = payload
    serialized = _serialize_doc(stored) or doc
    serialized["created_at"] = _isoformat(serialized.get("created_at")) or serialized.get("created_at")
    serialized["updated_at"] = _isoformat(serialized.get("updated_at")) or serialized.get("updated_at")
    return serialized


def get_story(story_id: str) -> Optional[Dict[str, Any]]:
    if not story_id:
        return None
    collection = _get_collection()
    if collection is None:
        for entry in _load_file_store():
            if entry.get("story_id") == story_id:
                return entry
        return None
    try:
        doc = collection.find_one({"story_id": story_id})  # type: ignore[attr-defined]
    except Exception:
        doc = None
    return _serialize_doc(doc)


def get_story_by_alert(alert_uid: str) -> Optional[Dict[str, Any]]:
    if not alert_uid:
        return None
    collection = _get_collection()
    if collection is None:
        for entry in _load_file_store():
            if entry.get("alert_uid") == alert_uid:
                return entry
        return None
    try:
        doc = collection.find_one({"alert_uid": alert_uid})  # type: ignore[attr-defined]
    except Exception:
        doc = None
    return _serialize_doc(doc)


def get_stories_by_alert_uids(alert_uids: List[str]) -> Dict[str, Dict[str, Any]]:
    if not alert_uids:
        return {}
    normalized = {str(uid) for uid in alert_uids if uid}
    if not normalized:
        return {}
    collection = _get_collection()
    results: Dict[str, Dict[str, Any]] = {}
    if collection is None:
        for entry in _load_file_store():
            uid = entry.get("alert_uid")
            if uid in normalized:
                results[uid] = entry
        return results
    try:
        cursor = collection.find({"alert_uid": {"$in": list(normalized)}})  # type: ignore[attr-defined]
        for doc in cursor:
            serialized = _serialize_doc(doc)
            if serialized and serialized.get("alert_uid"):
                results[serialized["alert_uid"]] = serialized
    except Exception:
        return results
    return results


def list_stories(
    *,
    start_dt: Optional[datetime],
    end_dt: Optional[datetime],
    limit: int = 50,
) -> List[Dict[str, Any]]:
    collection = _get_collection()
    if collection is None:
        entries = _load_file_store()
        filtered: List[Dict[str, Any]] = []
        for entry in entries:
            window = entry.get("time_window") or {}
            ts = _parse_iso(window.get("start")) or _parse_iso(entry.get("alert_timestamp"))
            if start_dt and ts and ts < start_dt:
                continue
            if end_dt and ts and ts > end_dt:
                continue
            filtered.append(entry)
        filtered.sort(key=lambda e: e.get("updated_at") or "", reverse=True)
        return filtered[:limit]
    query: Dict[str, Any] = {}
    if start_dt or end_dt:
        window: Dict[str, Any] = {}
        if start_dt:
            window["$gte"] = start_dt
        if end_dt:
            window["$lte"] = end_dt
        query["window_start_dt"] = window
    try:
        cursor = (
            collection.find(query)  # type: ignore[attr-defined]
            .sort([("window_start_dt", DESCENDING)])  # type: ignore[attr-defined]
            .limit(max(1, min(500, int(limit or 50))))  # type: ignore[attr-defined]
        )
    except Exception:
        return []
    stories: List[Dict[str, Any]] = []
    try:
        for doc in cursor:
            serialized = _serialize_doc(doc)
            if serialized:
                stories.append(serialized)
    except Exception:
        return stories
    return stories
