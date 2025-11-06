from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

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


def _sanitize_text(s: Any, max_len: int) -> str:
    try:
        t = (s or "").strip()
    except Exception:
        t = ""
    if len(t) > max_len:
        t = t[:max_len]
    return t


def submit_snippet(
    *,
    title: str,
    description: str,
    code: str,
    language: str,
    user_id: int,
    username: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new pending snippet proposal with basic validation.

    Returns dict with ok/error and id when available.
    """
    title_s = _sanitize_text(title, 180)
    desc_s = _sanitize_text(description, 1000)
    lang_s = _sanitize_text(language, 40)
    if len(title_s) < 3:
        return {"ok": False, "error": "הכותרת חייבת להיות 3..180 תווים"}
    if len(desc_s) < 4:
        return {"ok": False, "error": "התיאור קצר מדי"}
    if not code or not str(code).strip():
        return {"ok": False, "error": "נדרש קוד עבור הסניפט"}
    if not lang_s:
        return {"ok": False, "error": "נדרשת שפה"}

    try:
        inserted_id = _db._get_repo().create_snippet_proposal(
            title=title_s,
            description=desc_s,
            code=code,
            language=lang_s,
            user_id=int(user_id),
        )
        if not inserted_id:
            emit_event("snippet_submit_error", severity="warn", error="persist_failed")
            return {"ok": False, "error": "persist_failed"}
        emit_event("snippet_submitted", severity="info", user_id=int(user_id))
        return {"ok": True, "id": str(inserted_id)}
    except Exception as e:
        emit_event("snippet_submit_error", severity="warn", error=str(e))
        return {"ok": False, "error": "persist_failed"}


def approve_snippet(item_id: str, admin_id: int) -> bool:
    try:
        ok = _db._get_repo().approve_snippet(item_id, int(admin_id))
        if ok:
            emit_event("snippet_approved", severity="info", admin_id=int(admin_id))
        return ok
    except Exception as e:
        emit_event("snippet_approve_error", severity="warn", error=str(e))
        return False


def reject_snippet(item_id: str, admin_id: int, reason: str) -> bool:
    try:
        ok = _db._get_repo().reject_snippet(item_id, int(admin_id), _sanitize_text(reason, 300))
        if ok:
            emit_event("snippet_rejected", severity="info", admin_id=int(admin_id))
        return ok
    except Exception as e:
        emit_event("snippet_reject_error", severity="warn", error=str(e))
        return False


def list_pending_snippets(limit: int = 20, skip: int = 0) -> List[Dict[str, Any]]:
    try:
        return _db._get_repo().list_pending_snippets(limit=limit, skip=skip)
    except Exception:
        return []


def list_public_snippets(
    *,
    q: Optional[str] = None,
    language: Optional[str] = None,
    page: int = 1,
    per_page: int = 30,
) -> Tuple[List[Dict[str, Any]], int]:
    try:
        return _db._get_repo().list_public_snippets(q=q, language=language, page=page, per_page=per_page)
    except Exception:
        return [], 0
