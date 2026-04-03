"""
Personal Backup API — ייצוא ושחזור גיבוי אישי.

Endpoints:
- GET  /api/backup/export           — הורדת ZIP עם כל נתוני המשתמש
- POST /api/backup/restore          — שחזור נתונים מקובץ ZIP (סינכרוני)
- POST /api/backup/restore-async    — שחזור ברקע עם דיווח התקדמות
- GET  /api/backup/restore-progress/<id> — מצב התקדמות שחזור
"""
from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import wraps
from threading import Lock

from flask import Blueprint, jsonify, request, send_file, session

logger = logging.getLogger(__name__)

try:
    from observability import emit_event
except Exception:

    def emit_event(event: str, severity: str = "info", **fields):
        return None


try:
    from observability_instrumentation import traced
except Exception:

    def traced(*_a, **_k):
        def _inner(f):
            return f

        return _inner


backup_bp = Blueprint("backup", __name__)

# --- Async restore state ---
_restore_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="restore")
_active_restores: dict = {}  # restore_id -> {status, progress, step, result, user_id, created_at}
_restores_lock = Lock()
_RESTORE_MAX_AGE = 3600  # שעה — entries ישנים יותר ינוקו


def _cleanup_stale_restores():
    """מנקה entries ישנים מעל שעה שלא נקראו (מניעת דליפת זיכרון)."""
    now = time.time()
    with _restores_lock:
        stale = [rid for rid, e in _active_restores.items()
                 if now - e.get("created_at", 0) > _RESTORE_MAX_AGE]
        for rid in stale:
            _active_restores.pop(rid, None)

# Per-route upload limit (avoid global MAX_CONTENT_LENGTH side effects)
@backup_bp.before_request
def _limit_restore_upload_size():
    try:
        # Limit only the restore endpoint; export is GET anyway.
        if request.endpoint == "backup.restore_backup":
            request.max_content_length = MAX_UPLOAD_SIZE
    except Exception:
        pass


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"ok": False, "error": "נדרש להתחבר"}), 401
        return f(*args, **kwargs)

    return decorated


def _get_db():
    # חשוב: PersonalBackupService מצפה ל-DatabaseManager (database/manager.py),
    # ולא ל-pymongo Database שמוחזר מ-webapp.app.get_db().
    from database import db as _db

    return _db


def _get_backup_service():
    from services.personal_backup_service import PersonalBackupService

    return PersonalBackupService(_get_db())


# גודל מקסימלי לקובץ ZIP (100MB)
MAX_UPLOAD_SIZE = 100 * 1024 * 1024


@backup_bp.route("/api/backup/export", methods=["GET"])
@_require_auth
@traced("backup.export")
def export_backup():
    """ייצוא גיבוי אישי כ-ZIP."""
    user_id = session["user_id"]

    try:
        service = _get_backup_service()
        buffer = service.export_user_data(int(user_id))

        # שם קובץ עם תאריך
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"codebot_backup_{user_id}_{ts}.zip"

        response = send_file(
            buffer,
            mimetype="application/zip",
            as_attachment=True,
            download_name=filename,
        )
        response.headers["Cache-Control"] = "no-store"
        return response

    except Exception as e:
        logger.error(f"שגיאה בייצוא גיבוי: {e}")
        emit_event(
            "personal_backup_export_error",
            severity="error",
            user_id=int(user_id),
            error=str(e),
        )
        return jsonify({"ok": False, "error": "שגיאה ביצירת הגיבוי"}), 500


@backup_bp.route("/api/backup/restore", methods=["POST"])
@_require_auth
@traced("backup.restore")
def restore_backup():
    """שחזור מגיבוי ZIP."""
    user_id = session["user_id"]

    # בדיקת קובץ
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "לא נבחר קובץ"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"ok": False, "error": "לא נבחר קובץ"}), 400

    if not uploaded.filename.lower().endswith(".zip"):
        return jsonify({"ok": False, "error": "יש להעלות קובץ ZIP בלבד"}), 400

    # הגנה: אל תקרא קובץ ענק לזיכרון לפני בדיקת גודל
    try:
        content_len = int(request.content_length or 0)
    except Exception:
        content_len = 0
    if content_len and content_len > MAX_UPLOAD_SIZE:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": f"הקובץ גדול מדי (מקסימום {MAX_UPLOAD_SIZE // (1024*1024)}MB)",
                }
            ),
            413,
        )

    # קריאת התוכן עד MAX_UPLOAD_SIZE+1 כדי לזהות חריגה בלי OOM
    try:
        zip_bytes = uploaded.stream.read(MAX_UPLOAD_SIZE + 1)
    except Exception:
        # fallback
        zip_bytes = uploaded.read(MAX_UPLOAD_SIZE + 1)
    if len(zip_bytes) > MAX_UPLOAD_SIZE:
        return (
            jsonify(
                {
                    "ok": False,
                    "error": f"הקובץ גדול מדי (מקסימום {MAX_UPLOAD_SIZE // (1024*1024)}MB)",
                }
            ),
            413,
        )

    # פרמטרים
    overwrite = request.form.get("overwrite", "false").lower() in ("true", "1", "yes")

    try:
        service = _get_backup_service()
        result = service.restore_user_data(int(user_id), zip_bytes, overwrite=overwrite)
        return jsonify(result)

    except Exception as e:
        logger.error(f"שגיאה בשחזור גיבוי: {e}")
        emit_event(
            "personal_backup_restore_error",
            severity="error",
            user_id=int(user_id),
            error=str(e),
        )
        return jsonify({"ok": False, "error": "שגיאה בשחזור הגיבוי"}), 500


# --- Async restore ---

def _run_restore_in_background(restore_id: str, user_id: int, zip_bytes: bytes, overwrite: bool):
    """רץ ב-thread — מבצע שחזור ומעדכן progress."""
    def _progress(pct: int, step: str):
        with _restores_lock:
            entry = _active_restores.get(restore_id)
            if entry:
                entry["progress"] = pct
                entry["step"] = step

    try:
        service = _get_backup_service()
        result = service.restore_user_data(
            int(user_id), zip_bytes, overwrite=overwrite, progress_cb=_progress,
        )
        with _restores_lock:
            entry = _active_restores.get(restore_id)
            if entry:
                entry["status"] = "done"
                entry["progress"] = 100
                entry["step"] = "השחזור הושלם"
                entry["result"] = result
    except Exception as e:
        logger.error(f"שגיאה בשחזור אסינכרוני: {e}")
        with _restores_lock:
            entry = _active_restores.get(restore_id)
            if entry:
                entry["status"] = "error"
                entry["step"] = "שגיאה בשחזור"
                entry["result"] = {"ok": False, "error": str(e)}


@backup_bp.route("/api/backup/restore-async", methods=["POST"])
@_require_auth
@traced("backup.restore_async")
def restore_backup_async():
    """שחזור מגיבוי ZIP — רץ ברקע עם דיווח התקדמות."""
    user_id = session["user_id"]

    # בדיקת קובץ (אותה לוגיקה כמו restore רגיל)
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "לא נבחר קובץ"}), 400

    uploaded = request.files["file"]
    if not uploaded.filename:
        return jsonify({"ok": False, "error": "לא נבחר קובץ"}), 400

    if not uploaded.filename.lower().endswith(".zip"):
        return jsonify({"ok": False, "error": "יש להעלות קובץ ZIP בלבד"}), 400

    try:
        content_len = int(request.content_length or 0)
    except Exception:
        content_len = 0
    if content_len and content_len > MAX_UPLOAD_SIZE:
        return (
            jsonify({"ok": False, "error": f"הקובץ גדול מדי (מקסימום {MAX_UPLOAD_SIZE // (1024*1024)}MB)"}),
            413,
        )

    try:
        zip_bytes = uploaded.stream.read(MAX_UPLOAD_SIZE + 1)
    except Exception:
        zip_bytes = uploaded.read(MAX_UPLOAD_SIZE + 1)
    if len(zip_bytes) > MAX_UPLOAD_SIZE:
        return (
            jsonify({"ok": False, "error": f"הקובץ גדול מדי (מקסימום {MAX_UPLOAD_SIZE // (1024*1024)}MB)"}),
            413,
        )

    overwrite = request.form.get("overwrite", "false").lower() in ("true", "1", "yes")

    # יצירת restore_id והפעלת ריצה ברקע
    restore_id = uuid.uuid4().hex[:12]
    with _restores_lock:
        _active_restores[restore_id] = {
            "status": "running",
            "progress": 0,
            "step": "מתחיל שחזור...",
            "result": None,
            "user_id": user_id,
            "created_at": time.time(),
        }

    _restore_executor.submit(_run_restore_in_background, restore_id, user_id, zip_bytes, overwrite)

    return jsonify({"ok": True, "restore_id": restore_id})


@backup_bp.route("/api/backup/restore-progress/<restore_id>", methods=["GET"])
@_require_auth
@traced("backup.restore_progress")
def restore_progress(restore_id):
    """מחזיר מצב התקדמות שחזור."""
    user_id = session["user_id"]

    # ניקוי entries ישנים (best-effort)
    try:
        _cleanup_stale_restores()
    except Exception:
        pass

    # Snapshot כל השדות בתוך ה-lock כדי למנוע race condition
    # בדיקת בעלות *לפני* מחיקה — כדי שלא למחוק entry של משתמש אחר
    with _restores_lock:
        entry = _active_restores.get(restore_id)
        if not entry:
            return jsonify({"ok": False, "error": "שחזור לא נמצא"}), 404

        # בדיקת בעלות בתוך ה-lock, לפני pop
        if str(entry.get("user_id")) != str(user_id):
            return jsonify({"ok": False, "error": "שחזור לא נמצא"}), 404

        snapshot = {
            "status": entry["status"],
            "progress": entry["progress"],
            "step": entry["step"],
            "result": entry.get("result"),
        }
        # ניקוי אם סיים — בתוך אותו lock, אחרי שוידאנו בעלות
        if entry["status"] in ("done", "error"):
            _active_restores.pop(restore_id, None)

    resp = {
        "ok": True,
        "status": snapshot["status"],
        "progress": snapshot["progress"],
        "step": snapshot["step"],
    }
    if snapshot["status"] in ("done", "error"):
        resp["result"] = snapshot["result"]

    return jsonify(resp)

