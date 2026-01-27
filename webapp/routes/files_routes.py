"""
Files Routes - API endpoints moved from app.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import time
from datetime import datetime, timezone
from functools import wraps

from bson import ObjectId
from flask import Blueprint, jsonify, request, session, redirect, url_for, send_file

from src.infrastructure.composition.webapp_container import get_files_facade
try:  # keep config optional for docs/CI
    from config import config as _cfg  # type: ignore
except Exception:  # pragma: no cover
    _cfg = None

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

DEFAULT_WEBAPP_URL = "https://code-keeper-webapp.onrender.com"


def _get_webapp_url() -> str:
    value = None
    if _cfg is not None:
        try:
            value = getattr(_cfg, "WEBAPP_URL", None)
        except Exception:
            value = None
    if value in (None, ""):
        value = os.getenv("WEBAPP_URL") or DEFAULT_WEBAPP_URL
    return str(value)


def _get_public_share_ttl_days() -> int:
    raw = os.getenv("PUBLIC_SHARE_TTL_DAYS", "7")
    try:
        return max(1, int(raw))
    except Exception:
        return 7


def _get_recycle_ttl_days_default() -> int:
    raw = os.getenv("RECYCLE_TTL_DAYS", "7") or "7"
    try:
        return max(1, int(raw))
    except Exception:
        return 7


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


@files_bp.route("/recent")
@login_required
def api_recent_files():
    """Return recently opened files for the current user."""
    try:
        user_id = session["user_id"]
        facade = get_files_facade()
        results = facade.get_recent_files(user_id, limit=10)
        return jsonify(results)
    except Exception as e:
        try:
            logger.exception("Error fetching recent files", extra={"error": str(e)})
        except Exception:
            pass
        return jsonify({"error": "Failed to fetch recent files"}), 500


@files_bp.route("/bulk-favorite", methods=["POST"])
@login_required
@traced("files.bulk_favorite")
def api_files_bulk_favorite():
    """הוספת is_favorite=True לקבוצת קבצים של המשתמש."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get("file_ids") or [])
        if not file_ids:
            return jsonify({"success": False, "error": "No files selected"}), 400
        if len(file_ids) > 100:
            return jsonify({"success": False, "error": "Too many files (max 100)"}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({"success": False, "error": "Invalid file id"}), 400

        facade = get_files_facade()
        user_id = session["user_id"]
        updated = facade.bulk_set_favorite(user_id, object_ids, True)
        return jsonify({"success": True, "updated": int(updated)})
    except Exception:
        return jsonify({"success": False, "error": "שגיאה לא צפויה"}), 500


@files_bp.route("/bulk-unfavorite", methods=["POST"])
@login_required
@traced("files.bulk_unfavorite")
def api_files_bulk_unfavorite():
    """ביטול is_favorite לקבוצת קבצים של המשתמש."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get("file_ids") or [])
        if not file_ids:
            return jsonify({"success": False, "error": "No files selected"}), 400
        if len(file_ids) > 100:
            return jsonify({"success": False, "error": "Too many files (max 100)"}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({"success": False, "error": "Invalid file id"}), 400

        facade = get_files_facade()
        user_id = session["user_id"]
        updated = facade.bulk_set_favorite(user_id, object_ids, False)
        return jsonify({"success": True, "updated": int(updated)})
    except Exception:
        return jsonify({"success": False, "error": "שגיאה לא צפויה"}), 500


@files_bp.route("/bulk-tag", methods=["POST"])
@login_required
@traced("files.bulk_tag")
def api_files_bulk_tag():
    """הוספת תגיות לקבוצת קבצים של המשתמש ללא כפילויות."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get("file_ids") or [])
        tags = list(data.get("tags") or [])
        if not file_ids:
            return jsonify({"success": False, "error": "No files selected"}), 400
        if len(file_ids) > 100:
            return jsonify({"success": False, "error": "Too many files (max 100)"}), 400
        # נרמול תגיות – מחרוזות לא ריקות בלבד
        safe_tags = []
        for t in tags:
            try:
                s = str(t).strip()
            except Exception:
                s = ""
            if s:
                safe_tags.append(s)
        # הסר כפילויות תוך שמירה על סדר יחסי
        seen = set()
        norm_tags = [x for x in safe_tags if not (x in seen or seen.add(x))]
        if not norm_tags:
            return jsonify({"success": False, "error": "No tags provided"}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({"success": False, "error": "Invalid file id"}), 400

        facade = get_files_facade()
        user_id = session["user_id"]
        updated = facade.bulk_add_tags(user_id, object_ids, norm_tags)
        return jsonify({"success": True, "updated": int(updated)})
    except Exception:
        return jsonify({"success": False, "error": "שגיאה לא צפויה"}), 500


@files_bp.route("/create-zip", methods=["POST"])
@login_required
@traced("files.create_zip")
def api_files_create_zip():
    """יצירת קובץ ZIP עם קבצים נבחרים של המשתמש."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get("file_ids") or [])
        if not file_ids:
            return jsonify({"success": False, "error": "No files selected"}), 400
        if len(file_ids) > 100:
            return jsonify({"success": False, "error": "Too many files (max 100)"}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({"success": False, "error": "Invalid file id"}), 400

        facade = get_files_facade()
        user_id = session["user_id"]
        docs = facade.get_user_files_by_ids(user_id, object_ids)

        from io import BytesIO
        import zipfile

        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for doc in docs:
                filename = (
                    doc.get("file_name")
                    or f"file_{str(doc.get('_id'))}.txt"
                ).strip() or f"file_{str(doc.get('_id'))}.txt"
                # ודא שם ייחודי אם יש כפילויות
                try:
                    # מניעת שמות תיקיה מסוכנים
                    filename = filename.replace("..", "_").replace("/", "_").replace("\\", "_")
                except Exception:
                    filename = f"file_{str(doc.get('_id'))}.txt"
                content = doc.get("code")
                if not isinstance(content, str):
                    content = ""
                zf.writestr(filename, content)

        zip_buffer.seek(0)
        ts = int(time.time())
        return send_file(
            zip_buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=f"code_files_{ts}.zip",
        )
    except Exception:
        return jsonify({"success": False, "error": "שגיאה לא צפויה"}), 500


@files_bp.route("/create-share-link", methods=["POST"])
@login_required
@traced("share.create_multi")
def api_files_create_share_link():
    """יוצר קישור שיתוף ציבורי לקבצים נבחרים ומחזיר URL."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get("file_ids") or [])
        if not file_ids:
            return jsonify({"success": False, "error": "No files selected"}), 400
        if len(file_ids) > 100:
            return jsonify({"success": False, "error": "Too many files (max 100)"}), 400

        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({"success": False, "error": "Invalid file id"}), 400

        facade = get_files_facade()
        user_id = session["user_id"]

        owned_count = facade.count_user_files_by_ids(user_id, object_ids)
        if owned_count != len(object_ids):
            return jsonify({"success": False, "error": "Some files not found"}), 404

        token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        share_doc = facade.create_share_link(
            user_id=user_id,
            object_ids=object_ids,
            ttl_days=_get_public_share_ttl_days(),
            token=token,
            created_at=now,
        )
        if not share_doc:
            return jsonify({"success": False, "error": "שגיאה לא צפויה"}), 500

        base_url = (_get_webapp_url() or request.host_url.rstrip("/")).rstrip("/")
        share_url = f"{base_url}/shared/{token}"
        expires_at = share_doc.get("expires_at", now)
        return jsonify(
            {
                "success": True,
                "share_url": share_url,
                "expires_at": expires_at.isoformat(),
                "token": token,
            }
        )
    except Exception:
        return jsonify({"success": False, "error": "שגיאה לא צפויה"}), 500


@files_bp.route("/bulk-delete", methods=["POST"])
@login_required
@traced("files.bulk_delete")
def api_files_bulk_delete():
    """מחיקה רכה (soft delete) לקבוצת קבצים – מסמן is_active=False עם תוקף שחזור."""
    try:
        data = request.get_json(silent=True) or {}
        file_ids = list(data.get("file_ids") or [])
        raw_ttl = data.get("ttl_days")
        if raw_ttl is None or str(raw_ttl).strip() == "":
            ttl_days = _get_recycle_ttl_days_default()
        else:
            try:
                ttl_days = int(raw_ttl)
            except Exception:
                ttl_days = _get_recycle_ttl_days_default()
        if ttl_days < 1:
            ttl_days = _get_recycle_ttl_days_default()
        if ttl_days > 30:
            ttl_days = 30

        if not file_ids:
            return jsonify({"success": False, "error": "No files selected"}), 400
        try:
            object_ids = [ObjectId(fid) for fid in file_ids]
        except Exception:
            return jsonify({"success": False, "error": "Invalid file id"}), 400
        unique_object_ids = list(dict.fromkeys(object_ids))
        if len(unique_object_ids) > 100:
            return jsonify({"success": False, "error": "Too many files (max 100)"}), 400

        facade = get_files_facade()
        user_id = session["user_id"]
        result = facade.bulk_soft_delete(user_id, unique_object_ids, ttl_days)
        if int(result.get("found", 0)) != len(unique_object_ids):
            return jsonify({"success": False, "error": "Some files not found"}), 404

        return jsonify(
            {
                "success": True,
                "deleted": int(result.get("deleted", 0)),
                "skipped_already_deleted": int(result.get("skipped_already_deleted", 0)),
                "requested": len(unique_object_ids),
                "message": f"הקבצים הועברו לסל המחזור ל-{ttl_days} ימים",
            }
        )
    except Exception:
        return jsonify({"success": False, "error": "שגיאה לא צפויה"}), 500
