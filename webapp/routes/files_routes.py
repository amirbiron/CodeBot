"""
Files Routes - API endpoints moved from app.py
"""
from __future__ import annotations

import asyncio
import logging
from functools import wraps

from flask import Blueprint, jsonify, request, session, redirect, url_for

from src.infrastructure.composition.webapp_container import get_files_facade

# Manual tracing decorator (fail-open)
try:  # type: ignore
    from observability_instrumentation import traced  # type: ignore
except Exception:  # pragma: no cover
    def traced(*_a, **_k):  # type: ignore
        def _inner(f):
            return f
        return _inner


logger = logging.getLogger(__name__)

files_bp = Blueprint("files_api", __name__, url_prefix="/api/files")


def login_required(f):
    """Local login guard for API routes."""
    try:
        is_async = asyncio.iscoroutinefunction(f)  # type: ignore[attr-defined]
    except Exception:
        is_async = False

    if is_async:
        @wraps(f)
        async def decorated_function(*args, **kwargs):
            if "user_id" not in session:
                try:
                    wants_json = (
                        (request.path or "").startswith("/api/")
                        or ("application/json" in (request.headers.get("Accept") or ""))
                    )
                except Exception:
                    wants_json = False
                if wants_json:
                    return jsonify({"error": "נדרש להתחבר"}), 401
                next_url = request.full_path if request.query_string else request.path
                return redirect(url_for("login", next=next_url))
            return await f(*args, **kwargs)
        return decorated_function

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            try:
                wants_json = (
                    (request.path or "").startswith("/api/")
                    or ("application/json" in (request.headers.get("Accept") or ""))
                )
            except Exception:
                wants_json = False
            if wants_json:
                return jsonify({"error": "נדרש להתחבר"}), 401
            next_url = request.full_path if request.query_string else request.path
            return redirect(url_for("login", next=next_url))
        return f(*args, **kwargs)
    return decorated_function


def safe_iso(value, field: str = "") -> str:
    """Safe ISO8601 conversion without raising."""
    if isinstance(value, str):
        return value
    try:
        return value.isoformat()
    except Exception:
        try:
            logger.warning(
                "Non-datetime value in isoformat field=%s type=%s",
                field,
                type(value).__name__,
            )
        except Exception:
            pass
        try:
            return str(value)
        except Exception:
            return ""


@files_bp.route("/resolve")
@login_required
@traced("files.resolve")
def api_resolve_file_by_name():
    """Resolve latest active file id by exact file_name for current user."""
    try:
        user_id = session["user_id"]
        name = (request.args.get("name") or "").strip()
        if not name:
            return jsonify({"ok": False, "error": "missing name"}), 400

        facade = get_files_facade()
        result = facade.resolve_file_by_name(user_id, name)
        status = result.get("status")

        if status == "found":
            doc = result.get("doc") or {}
            lang = (doc.get("programming_language") or "text").lower()
            return jsonify(
                {
                    "ok": True,
                    "id": str(doc.get("_id")),
                    "file_name": doc.get("file_name"),
                    "language": lang,
                }
            )

        if status == "trashed":
            trashed_doc = result.get("doc") or {}
            return jsonify(
                {
                    "ok": False,
                    "error": "in_recycle_bin",
                    "file_name": trashed_doc.get("file_name"),
                    "deleted_at": safe_iso(trashed_doc.get("deleted_at"), "deleted_at"),
                    "recycle_expires_at": safe_iso(
                        trashed_doc.get("deleted_expires_at"), "deleted_expires_at"
                    ),
                }
            )

        return jsonify({"ok": False, "error": "not_found"})
    except Exception as e:
        try:
            logger.error("api_resolve_file_by_name failed: %s", e)
        except Exception:
            pass
        return jsonify({"ok": False, "error": "internal_error"}), 500
