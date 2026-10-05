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
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file, session
from pymongo.errors import PyMongoError

from drive_owner import WEBAPP as DRIVE_OWNER, drive_fields

logger = logging.getLogger(__name__)

try:
    from observability import emit_event
except Exception:
    def emit_event(event: str, severity: str = "info", **fields):
        return None

drive_backup_bp = Blueprint("drive_backup", __name__)

_backup_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="backup-trigger")

VALID_SCHEDULES = {"daily", "every3", "weekly", "biweekly", "monthly", "off"}
DISK_BACKUP_DIR = os.getenv("WEBAPP_BACKUPS_DIR", "/var/data/repos/backups")
_SAFE_BACKUP_NAME = re.compile(r"^webapp_backup_\d+_\d{8}_\d{6}(_\d+)?\.zip$")


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
# כל נקודות הקצה כאן עובדות על החיבור וההעדפות של הוובאפ בלבד (``drive_owner.WEBAPP``),
# כך שתזמון או גיבוי מהוובאפ לא נוגעים בחיבור של הבוט — ראו drive_owner.py.
_DRIVE_FIELDS = drive_fields(DRIVE_OWNER)
_NOT_CONNECTED_ERROR = "יש לחבר Google Drive קודם"


def _connected_user_filter(user_id: int) -> dict:
    """פילטר שתואם את מסמך המשתמש רק כשיש לו חיבור Drive של הוובאפ (``access_token`` שמור ולא ריק).

    התנאי הזה יושב בפילטר של העדכון עצמו, ולא בקריאה שלפניו: ניתוק שנכנס בין בדיקה לכתיבה היה משאיר תזמון או גיבוי בלי חיבור. כשהעדכון לא תאם אף מסמך (``matched_count`` אפס), המשתמש לא מחובר.
    """
    return {"user_id": user_id, f"{_DRIVE_FIELDS.tokens}.access_token": {"$nin": [None, ""]}}


@drive_backup_bp.route("/api/drive/schedule", methods=["POST"])
@_require_auth
def set_drive_schedule():
    """הגדרת תזמון גיבוי אוטומטי ל-Drive."""
    user_id = int(session["user_id"])
    db = _get_db()

    data = request.get_json(silent=True)
    if data is None:
        # get_json(silent=True) מחזיר None כשאין גוף JSON תקין (Werkzeug 3.1.9, wrappers/request.py) — ואז ברירת המחדל היא "off"
        data = {}
    elif not isinstance(data, dict):
        return jsonify({"ok": False, "error": "תדירות לא חוקית"}), 400
    schedule = data.get("schedule", "off")
    # בדיקת טיפוס לפני בדיקת החברות: ערך לא-hashable היה זורק TypeError מתוך ה-in
    if not isinstance(schedule, str) or schedule not in VALID_SCHEDULES:
        return jsonify({"ok": False, "error": "תדירות לא חוקית"}), 400

    from webapp.backup_scheduler import _compute_next_at
    next_at = _compute_next_at(schedule) if schedule != "off" else None
    # הפעלת תזמון דורשת חיבור, ולכן היא נכתבת רק למסמך של משתמש מחובר; כיבוי נכתב תמיד
    query = _connected_user_filter(user_id) if schedule != "off" else {"user_id": user_id}
    try:
        # $set ישיר על שדות ספציפיים — לא read-modify-write שיכול לדרוס sentinel
        res = db.db.users.update_one(
            query,
            {"$set": {
                f"{_DRIVE_FIELDS.prefs}.schedule_key": schedule,
                f"{_DRIVE_FIELDS.prefs}.schedule_next_at": next_at,
            }},
        )
    except PyMongoError:
        logger.exception("Error setting Drive schedule")
        return jsonify({"ok": False, "error": "שגיאה בהגדרת תזמון"}), 500
    if not res.matched_count and schedule != "off":
        # אין מסמך של משתמש מחובר — התזמון לא נשמר. כיבוי בלי מסמך הוא כבר המצב המבוקש.
        return jsonify({"ok": False, "error": _NOT_CONNECTED_ERROR}), 400

    emit_event("webapp_drive_schedule_set", user_id=user_id, schedule=schedule)
    return jsonify({"ok": True, "schedule": schedule})


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
                f"{_DRIVE_FIELDS.prefs}.manual_backup_status": "done" if ok else "error",
                f"{_DRIVE_FIELDS.prefs}.manual_backup_finished_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
    except PyMongoError:
        # בלי העדכון ה-UI ימשיך להציג "רץ" — לכן נרשם, גם אם אין כאן מה לעשות מעבר לזה
        logger.exception("Failed to update manual Drive backup status for user %s", user_id)


@drive_backup_bp.route("/api/drive/backup-now", methods=["POST"])
@_require_auth
def drive_backup_now():
    """גיבוי מיידי ל-Drive — רץ ברקע, מחזיר מיד."""
    user_id = int(session["user_id"])
    db = _get_db()

    # סימון "running" ב-DB והפעלה ברקע — רק למשתמש מחובר (``_connected_user_filter``)
    try:
        res = db.db.users.update_one(
            _connected_user_filter(user_id),
            {"$set": {
                f"{_DRIVE_FIELDS.prefs}.manual_backup_status": "running",
                f"{_DRIVE_FIELDS.prefs}.manual_backup_finished_at": None,
            }},
        )
        if not res.matched_count:
            # לא סומן "running" ולא נשלח לרקע: בלי חיבור אין מה להעלות
            return jsonify({"ok": False, "error": _NOT_CONNECTED_ERROR}), 400
        _backup_executor.submit(_run_drive_backup_bg, user_id)
        return jsonify({"ok": True, "status": "running"})
    except Exception:
        logger.exception("Error triggering Drive backup")
        return jsonify({"ok": False, "error": "שגיאה בהפעלת גיבוי"}), 500


@drive_backup_bp.route("/api/drive/backup-status")
@_require_auth
def drive_backup_status():
    """סטטוס גיבוי Drive — של הוובאפ בלבד."""
    user_id = int(session["user_id"])
    db = _get_db()

    # get_drive_prefs אינו זורק: בכשל מסד הוא רושם אירוע ומחזיר None
    prefs = db.get_drive_prefs(user_id, owner=DRIVE_OWNER)
    if not isinstance(prefs, dict):
        prefs = {}
    return jsonify({
        "ok": True,
        "last_backup_at": prefs.get("last_backup_at"),
        "last_full_backup_at": prefs.get("last_full_backup_at"),
        "schedule_next_at": prefs.get("schedule_next_at"),
        "manual_backup_status": prefs.get("manual_backup_status"),
    })


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


@drive_backup_bp.route("/api/disk-backup/download/<filename>")
@_require_auth
def disk_backup_download(filename):
    """הורדת קובץ גיבוי דיסק ספציפי (רק של המשתמש המחובר)."""
    user_id = session["user_id"]

    # וידוא שם קובץ תקין
    if not _SAFE_BACKUP_NAME.match(filename):
        return jsonify({"ok": False, "error": "שם קובץ לא תקין"}), 400

    # וידוא שהקובץ שייך למשתמש הנוכחי
    expected_prefix = f"webapp_backup_{int(user_id)}_"
    if not filename.startswith(expected_prefix):
        return jsonify({"ok": False, "error": "אין הרשאה"}), 403

    # חיפוש הקובץ מתוך רשימת הגיבויים בפועל — ללא בניית נתיב מ-user input
    backup_dir = Path(DISK_BACKUP_DIR).resolve()
    safe_glob = f"webapp_backup_{int(user_id)}_*.zip"
    matched = [p for p in backup_dir.glob(safe_glob) if p.name == filename]

    if not matched:
        return jsonify({"ok": False, "error": "קובץ לא נמצא"}), 404

    return send_file(str(matched[0]), as_attachment=True, download_name=matched[0].name)
