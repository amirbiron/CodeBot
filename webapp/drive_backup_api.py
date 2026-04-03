"""
Drive & Disk Backup API — ניהול גיבויים אוטומטיים מהוובאפ.

Endpoints:
- POST /api/drive/schedule       — הגדרת תזמון גיבוי ל-Drive
- POST /api/drive/backup-now     — גיבוי מיידי ל-Drive
- GET  /api/drive/backup-status  — סטטוס גיבוי Drive
- POST /api/disk-backup/schedule — הגדרת תזמון גיבוי לדיסק
- POST /api/disk-backup/now      — גיבוי מיידי לדיסק
- GET  /api/disk-backup/status   — סטטוס גיבוי דיסק
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import wraps

from flask import Blueprint, jsonify, request, session

logger = logging.getLogger(__name__)

try:
    from observability import emit_event
except Exception:
    def emit_event(event: str, severity: str = "info", **fields):
        return None

drive_backup_bp = Blueprint("drive_backup", __name__)

_backup_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="backup-trigger")

VALID_SCHEDULES = {"daily", "every3", "weekly", "biweekly", "monthly", "off"}


def _require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({"ok": False, "error": "נדרש להתחבר"}), 401
        return f(*args, **kwargs)
    return decorated


def _get_db():
    from database import db as _db
    return _db


# ==================== Drive API ====================

@drive_backup_bp.route("/api/drive/schedule", methods=["POST"])
@_require_auth
def set_drive_schedule():
    """הגדרת תזמון גיבוי אוטומטי ל-Drive."""
    user_id = session["user_id"]
    db = _get_db()

    data = request.get_json(silent=True) or {}
    schedule = data.get("schedule", "off")
    if schedule not in VALID_SCHEDULES:
        return jsonify({"ok": False, "error": "תדירות לא חוקית"}), 400

    # בדוק שיש חיבור Drive
    if schedule != "off":
        try:
            tokens = db.get_drive_tokens(int(user_id))
            if not tokens or not tokens.get("access_token"):
                return jsonify({"ok": False, "error": "יש לחבר Google Drive קודם"}), 400
        except Exception:
            return jsonify({"ok": False, "error": "שגיאה בבדיקת חיבור Drive"}), 500

    try:
        from webapp.backup_scheduler import _compute_next_at
        update = {"schedule_key": schedule}
        if schedule != "off":
            update["schedule_next_at"] = _compute_next_at(schedule)
        else:
            update["schedule_next_at"] = None

        # $set ישיר על שדות ספציפיים — לא read-modify-write שיכול לדרוס sentinel
        set_fields = {
            "drive_prefs.schedule_key": schedule,
            "drive_prefs.schedule_next_at": update["schedule_next_at"],
        }
        update_ops = {"$set": set_fields}
        # ניקוי שדות legacy כדי שה-scheduler לא יתפוס משתמש שכיבה schedule
        if schedule == "off":
            update_ops["$unset"] = {"drive_prefs.schedule": ""}
        db.db.users.update_one({"user_id": int(user_id)}, update_ops)

        emit_event("webapp_drive_schedule_set", user_id=int(user_id), schedule=schedule)
        return jsonify({"ok": True, "schedule": schedule})
    except Exception as e:
        logger.exception("Error setting Drive schedule")
        return jsonify({"ok": False, "error": "שגיאה בהגדרת תזמון"}), 500


def _run_drive_backup_bg(user_id: int):
    """רץ ב-thread — מבצע גיבוי Drive ומעדכן סטטוס ב-DB."""
    try:
        from webapp.backup_scheduler import trigger_drive_backup_now
        result = trigger_drive_backup_now(user_id)
        ok = result.get("ok", False) if isinstance(result, dict) else False
    except Exception:
        logger.exception("Background Drive backup error for user %s", user_id)
        ok = False

    # עדכון סטטוס — ה-UI עושה polling דרך backup-status
    try:
        db = _get_db()
        db.db.users.update_one(
            {"user_id": user_id},
            {"$set": {
                "drive_prefs.manual_backup_status": "done" if ok else "error",
                "drive_prefs.manual_backup_finished_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    except Exception:
        pass


@drive_backup_bp.route("/api/drive/backup-now", methods=["POST"])
@_require_auth
def drive_backup_now():
    """גיבוי מיידי ל-Drive — רץ ברקע, מחזיר מיד."""
    user_id = session["user_id"]
    db = _get_db()

    # וידוא חיבור
    try:
        tokens = db.get_drive_tokens(int(user_id))
        if not tokens or not tokens.get("access_token"):
            return jsonify({"ok": False, "error": "יש לחבר Google Drive קודם"}), 400
    except Exception:
        return jsonify({"ok": False, "error": "שגיאה בבדיקת חיבור"}), 500

    # סימון "running" ב-DB והפעלה ברקע
    try:
        db.db.users.update_one(
            {"user_id": int(user_id)},
            {"$set": {
                "drive_prefs.manual_backup_status": "running",
                "drive_prefs.manual_backup_finished_at": None,
            }},
        )
        _backup_executor.submit(_run_drive_backup_bg, int(user_id))
        return jsonify({"ok": True, "status": "running"})
    except Exception as e:
        logger.exception("Error triggering Drive backup")
        return jsonify({"ok": False, "error": "שגיאה בהפעלת גיבוי"}), 500


@drive_backup_bp.route("/api/drive/backup-status")
@_require_auth
def drive_backup_status():
    """סטטוס גיבוי Drive."""
    user_id = session["user_id"]
    db = _get_db()

    try:
        prefs = db.get_drive_prefs(int(user_id)) or {}
        return jsonify({
            "ok": True,
            "last_backup_at": prefs.get("last_backup_at"),
            "last_full_backup_at": prefs.get("last_full_backup_at"),
            "schedule_next_at": prefs.get("schedule_next_at"),
            "manual_backup_status": prefs.get("manual_backup_status"),
        })
    except Exception:
        return jsonify({"ok": True, "last_backup_at": None})


# ==================== Disk Backup API ====================

@drive_backup_bp.route("/api/disk-backup/schedule", methods=["POST"])
@_require_auth
def set_disk_schedule():
    """הגדרת תזמון גיבוי אוטומטי לדיסק."""
    user_id = session["user_id"]
    db = _get_db()

    data = request.get_json(silent=True) or {}
    schedule = data.get("schedule", "off")
    if schedule not in VALID_SCHEDULES:
        return jsonify({"ok": False, "error": "תדירות לא חוקית"}), 400

    try:
        from webapp.backup_scheduler import _compute_next_at
        update = {
            "disk_backup_prefs.schedule_key": schedule,
        }
        if schedule != "off":
            update["disk_backup_prefs.schedule_next_at"] = _compute_next_at(schedule)
        else:
            update["disk_backup_prefs.schedule_next_at"] = None

        db.db.users.update_one(
            {"user_id": int(user_id)},
            {"$set": update},
        )
        emit_event("webapp_disk_schedule_set", user_id=int(user_id), schedule=schedule)
        return jsonify({"ok": True, "schedule": schedule})
    except Exception as e:
        logger.exception("Error setting Disk schedule")
        return jsonify({"ok": False, "error": "שגיאה בהגדרת תזמון"}), 500


@drive_backup_bp.route("/api/disk-backup/now", methods=["POST"])
@_require_auth
def disk_backup_now():
    """גיבוי מיידי לדיסק."""
    user_id = session["user_id"]

    try:
        from webapp.backup_scheduler import trigger_disk_backup_now
        future = _backup_executor.submit(trigger_disk_backup_now, int(user_id))
        result = future.result(timeout=120)
        return jsonify(result)
    except Exception as e:
        logger.exception("Error triggering Disk backup")
        return jsonify({"ok": False, "error": "שגיאה בהפעלת גיבוי"}), 500


@drive_backup_bp.route("/api/disk-backup/status")
@_require_auth
def disk_backup_status():
    """סטטוס גיבוי דיסק."""
    user_id = session["user_id"]

    try:
        from webapp.backup_scheduler import get_disk_backup_info
        info = get_disk_backup_info(int(user_id))

        # קרא גם schedule מה-DB
        db = _get_db()
        user_doc = db.db.users.find_one({"user_id": int(user_id)}, {"disk_backup_prefs": 1})
        disk_prefs = (user_doc or {}).get("disk_backup_prefs") or {}

        return jsonify({
            "ok": True,
            "schedule": disk_prefs.get("schedule_key", "off"),
            "last_backup_at": disk_prefs.get("last_backup_at"),
            "schedule_next_at": disk_prefs.get("schedule_next_at"),
            "count": info.get("count", 0),
            "total_size": info.get("total_size", 0),
            "backups": info.get("backups", [])[:5],
        })
    except Exception as e:
        logger.exception("Error getting Disk backup status")
        return jsonify({"ok": True, "schedule": "off", "count": 0})
