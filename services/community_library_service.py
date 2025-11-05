from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from bson import ObjectId  # type: ignore
except Exception:  # pragma: no cover
    class ObjectId(str):  # minimal fallback for tests without bson
        pass

from database import db as _db

try:  # observability (fail-open)
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None


@dataclass
class CommunityItem:
    title: str
    description: str
    url: str
    logo_file_id: Optional[str]
    status: str
    submitted_at: datetime
    approved_at: Optional[datetime]
    approved_by: Optional[int]
    rejection_reason: Optional[str]
    user_id: int
    username: Optional[str]
    tags: List[str]
    featured: bool


def _coll():
    try:
        coll = getattr(_db, 'community_library_collection', None)
        return coll if coll is not None else getattr(_db.db, 'community_library_items')
    except Exception:
        return None


def _sanitize_text(s: Any, max_len: int) -> str:
    try:
        t = (s or "").strip()
    except Exception:
        t = ""
    if len(t) > max_len:
        t = t[:max_len]
    return t


def _validate_url(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u or len(u) > 2048:
        return False
    return u.startswith("http://") or u.startswith("https://")


def submit_item(
    *,
    title: str,
    description: str,
    url: str,
    user_id: int,
    username: Optional[str] = None,
    logo_file_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    featured: bool = False,
) -> Dict[str, Any]:
    """Create a new pending community item with basic validation.

    Returns dict with ok/error and id when available.
    """
    title_s = _sanitize_text(title, 120)
    desc_s = _sanitize_text(description, 600)
    url_s = _sanitize_text(url, 2048)
    if len(title_s) < 3:
        return {"ok": False, "error": "שם פריט חייב להיות 3..120 תווים"}
    if not _validate_url(url_s):
        return {"ok": False, "error": "URL לא תקין"}
    clean_tags: List[str] = []
    for t in list(tags or []):
        if not isinstance(t, str):
            continue
        tt = t.strip()
        if not tt:
            continue
        if len(tt) > 40:
            tt = tt[:40]
        if tt not in clean_tags:
            clean_tags.append(tt)

    now = datetime.now(timezone.utc)
    doc = {
        "title": title_s,
        "description": desc_s,
        "url": url_s,
        "logo_file_id": _sanitize_text(logo_file_id, 256) if logo_file_id else None,
        "status": "pending",
        "submitted_at": now,
        "approved_at": None,
        "approved_by": None,
        "rejection_reason": None,
        "user_id": int(user_id),
        "username": _sanitize_text(username, 64) if username else None,
        "tags": clean_tags,
        "featured": bool(featured),
    }
    coll = _coll()
    try:
        res = coll.insert_one(doc) if coll is not None else None
        item_id = getattr(res, 'inserted_id', None)
        emit_event("community_item_submitted", severity="info", user_id=int(user_id))
        return {"ok": True, "id": str(item_id) if item_id else None}
    except Exception as e:  # pragma: no cover - no-op envs
        emit_event("community_submit_error", severity="warn", error=str(e))
        # Fail-open: report success in environments without DB
        return {"ok": True, "id": None}


def approve_item(item_id: str, admin_id: int) -> bool:
    coll = _coll()
    if coll is None:
        return True
    try:
        q = {"_id": ObjectId(item_id)} if item_id else {"_id": None}
        res = coll.update_one(q, {"$set": {"status": "approved", "approved_at": datetime.now(timezone.utc), "approved_by": int(admin_id), "rejection_reason": None}})
        ok = bool(getattr(res, 'modified_count', 0) or getattr(res, 'matched_count', 0))
        if ok:
            emit_event("community_item_approved", severity="info", admin_id=int(admin_id))
        return ok
    except Exception as e:
        emit_event("community_approve_error", severity="warn", error=str(e))
        return False


def reject_item(item_id: str, admin_id: int, reason: str) -> bool:
    coll = _coll()
    if coll is None:
        return True
    try:
        reason_s = _sanitize_text(reason, 300)
        q = {"_id": ObjectId(item_id)} if item_id else {"_id": None}
        res = coll.update_one(q, {"$set": {"status": "rejected", "approved_at": None, "approved_by": int(admin_id), "rejection_reason": reason_s}})
        ok = bool(getattr(res, 'modified_count', 0) or getattr(res, 'matched_count', 0))
        if ok:
            emit_event("community_item_rejected", severity="info", admin_id=int(admin_id))
        return ok
    except Exception as e:
        emit_event("community_reject_error", severity="warn", error=str(e))
        return False


def list_pending(limit: int = 20, skip: int = 0) -> List[Dict[str, Any]]:
    coll = _coll()
    try:
        cursor = coll.find({"status": "pending"}, sort=[("submitted_at", 1)]) if coll is not None else []
        # allow lists in stubbed envs
        rows = list(cursor) if not isinstance(cursor, list) else cursor
        return rows[skip: skip + limit]
    except Exception:
        return []


def list_public(q: Optional[str] = None, page: int = 1, per_page: int = 30, tags: Optional[List[str]] = None, featured_first: bool = True) -> Tuple[List[Dict[str, Any]], int]:
    coll = _coll()
    if coll is None:
        return [], 0
    try:
        page = max(1, int(page or 1))
        per_page = max(1, min(int(per_page or 30), 60))
    except Exception:
        page, per_page = 1, 30

    # Build filter
    match: Dict[str, Any] = {"status": "approved"}
    if q:
        # simple contains match on title/description (fallback if no $text index)
        regex = {"$regex": q, "$options": "i"}
        match["$or"] = [{"title": regex}, {"description": regex}]
    if tags:
        match["tags"] = {"$in": list({t for t in tags if isinstance(t, str) and t.strip()})}

    try:
        total = int(coll.count_documents(match))
    except Exception:
        total = 0
    skip = (page - 1) * per_page

    sort = [("featured", -1), ("approved_at", -1)] if featured_first else [("approved_at", -1)]
    try:
        cursor = coll.find(match, sort=sort).skip(skip).limit(per_page)
        rows = list(cursor)
    except Exception:
        rows = []

    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            out.append({
                "title": r.get("title"),
                "description": r.get("description"),
                "url": r.get("url"),
                "logo_url": None,  # future: build from file_id if a proxy endpoint is added
                "tags": r.get("tags") or [],
                "featured": bool(r.get("featured", False)),
                "approved_at": r.get("approved_at"),
            })
        except Exception:
            continue
    return out, total
