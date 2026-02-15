"""
Personal Backup API — ייצוא ושחזור גיבוי אישי.

Endpoints:
- GET  /api/backup/export   — הורדת ZIP עם כל נתוני המשתמש
- POST /api/backup/restore  — שחזור נתונים מקובץ ZIP
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from functools import wraps

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


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"ok": False, "error": "נדרש להתחבר"}), 401
        return f(*args, **kwargs)

    return decorated


def _get_db():
    from webapp.app import get_db

    return get_db()


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

    # קריאת התוכן
    zip_bytes = uploaded.read()
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

