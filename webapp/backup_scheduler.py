"""
Webapp Backup Scheduler — גיבויים אוטומטיים ל-Drive ולדיסק.

Thread daemon שרץ ברקע וסורק כל כמה דקות אם יש משתמשים
שצריכים גיבוי אוטומטי (לפי schedule_next_at).
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# תדירויות (בשניות)
SCHEDULE_INTERVALS: Dict[str, int] = {
    "daily": 86400,
    "every3": 259200,
    "weekly": 604800,
    "biweekly": 1209600,
    "monthly": 2592000,
}

# כל כמה שניות הסורק רץ
SCAN_INTERVAL_SECONDS = int(os.getenv("BACKUP_SCAN_INTERVAL", "300"))  # 5 דקות

# נתיב דיסק לגיבויים (Render persistent disk)
DISK_BACKUP_DIR = os.getenv("WEBAPP_BACKUPS_DIR", "/var/data/repos/backups")

# Retention
DISK_BACKUP_RETENTION_DAYS = int(os.getenv("DISK_BACKUP_RETENTION_DAYS", "30"))
DISK_BACKUP_MAX_PER_USER = int(os.getenv("DISK_BACKUP_MAX_PER_USER", "10"))

_scheduler_thread: Optional[threading.Thread] = None
_scheduler_lock = threading.Lock()


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _compute_next_at(schedule_key: str, from_dt: Optional[datetime] = None) -> str:
    """חישוב הזמן הבא לגיבוי."""
    interval = SCHEDULE_INTERVALS.get(schedule_key, 86400)
    base = from_dt or _now_utc()
    next_dt = base + timedelta(seconds=interval)
    return next_dt.isoformat()


def _perform_drive_backup(user_id: int) -> bool:
    """מבצע גיבוי ל-Drive עבור משתמש."""
    try:
        from services.google_drive_service import perform_scheduled_backup
        result = perform_scheduled_backup(user_id)
        if result.ok:
            logger.info("Drive backup completed for user %s (uploaded=%d)", user_id, result.uploaded)
        else:
            logger.warning("Drive backup failed for user %s", user_id)
        return result.ok
    except Exception:
        logger.exception("Drive backup error for user %s", user_id)
        return False


def _perform_disk_backup(user_id: int) -> bool:
    """מבצע גיבוי לדיסק עבור משתמש."""
    try:
        from services.personal_backup_service import PersonalBackupService
        from database import db

        service = PersonalBackupService(db)
        buffer = service.export_user_data(int(user_id))
        zip_bytes = buffer.getvalue()

        # שמירה לדיסק
        backup_dir = Path(DISK_BACKUP_DIR)
        backup_dir.mkdir(parents=True, exist_ok=True)

        ts = _now_utc().strftime("%Y%m%d_%H%M%S")
        filename = f"webapp_backup_{user_id}_{ts}.zip"
        filepath = backup_dir / filename
        filepath.write_bytes(zip_bytes)

        logger.info("Disk backup saved: %s (%d bytes)", filepath, len(zip_bytes))

        # ניקוי גיבויים ישנים
        _cleanup_disk_backups(user_id, backup_dir)
        return True

    except Exception:
        logger.exception("Disk backup error for user %s", user_id)
        return False


def _cleanup_disk_backups(user_id: int, backup_dir: Path):
    """מנקה גיבויים ישנים לפי retention ו-max per user."""
    try:
        pattern = f"webapp_backup_{user_id}_*.zip"
        user_backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

        cutoff = _now_utc() - timedelta(days=DISK_BACKUP_RETENTION_DAYS)
        for i, bp in enumerate(user_backups):
            try:
                should_delete = False
                # מחיקה לפי max per user
                if i >= DISK_BACKUP_MAX_PER_USER:
                    should_delete = True
                # מחיקה לפי retention
                mtime = datetime.fromtimestamp(bp.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    should_delete = True

                if should_delete:
                    bp.unlink()
                    logger.info("Cleaned up old backup: %s", bp.name)
            except Exception:
                logger.exception("Error cleaning up backup: %s", bp)
    except Exception:
        logger.exception("Error in disk backup cleanup for user %s", user_id)


def _scan_and_run():
    """סורק את כל המשתמשים ומריץ גיבויים לפי הצורך."""
    try:
        from database import db
    except Exception:
        logger.exception("Cannot import database for backup scheduler")
        return

    now = _now_utc()

    # --- Drive backups ---
    try:
        users_with_drive = db.get_users_with_active_drive_schedule()
        for user_doc in (users_with_drive or []):
            try:
                uid = user_doc.get("user_id")
                if not uid:
                    continue
                prefs = user_doc.get("drive_prefs") or {}
                next_at_str = prefs.get("schedule_next_at")
                schedule_key = _extract_schedule_key(prefs)

                if not schedule_key or schedule_key not in SCHEDULE_INTERVALS:
                    continue

                # בדוק אם הגיע הזמן
                if next_at_str:
                    try:
                        next_at = datetime.fromisoformat(next_at_str)
                        if next_at.tzinfo is None:
                            next_at = next_at.replace(tzinfo=timezone.utc)
                        if next_at > now:
                            continue
                    except Exception:
                        pass  # אם לא ניתן לפרסר, נריץ עכשיו

                logger.info("Running scheduled Drive backup for user %s", uid)
                ok = _perform_drive_backup(uid)
                if ok:
                    new_next = _compute_next_at(schedule_key)
                    try:
                        db.save_drive_prefs(uid, {"schedule_next_at": new_next})
                    except Exception:
                        logger.exception("Failed to update schedule_next_at for user %s", uid)
                # אם נכשל, לא מזיזים את schedule_next_at — יינסה שוב בסריקה הבאה
            except Exception:
                logger.exception("Error processing Drive schedule for user %s", user_doc.get("user_id"))
    except Exception:
        logger.exception("Error scanning Drive schedules")

    # --- Disk backups ---
    try:
        users_collection = db.db.users
        cursor = users_collection.find(
            {"disk_backup_prefs.schedule_key": {"$in": list(SCHEDULE_INTERVALS.keys())}},
            {"user_id": 1, "disk_backup_prefs": 1},
        )
        for user_doc in cursor:
            try:
                uid = user_doc.get("user_id")
                if not uid:
                    continue
                disk_prefs = user_doc.get("disk_backup_prefs") or {}
                schedule_key = disk_prefs.get("schedule_key")
                if not schedule_key or schedule_key not in SCHEDULE_INTERVALS:
                    continue

                next_at_str = disk_prefs.get("schedule_next_at")
                if next_at_str:
                    try:
                        next_at = datetime.fromisoformat(next_at_str)
                        if next_at.tzinfo is None:
                            next_at = next_at.replace(tzinfo=timezone.utc)
                        if next_at > now:
                            continue
                    except Exception:
                        pass

                logger.info("Running scheduled Disk backup for user %s", uid)
                ok = _perform_disk_backup(uid)
                now_iso = _now_utc().isoformat()
                update = {"disk_backup_prefs.last_backup_at": now_iso}
                if ok:
                    new_next = _compute_next_at(schedule_key)
                    update["disk_backup_prefs.schedule_next_at"] = new_next
                try:
                    users_collection.update_one({"user_id": uid}, {"$set": update})
                except Exception:
                    logger.exception("Failed to update disk backup prefs for user %s", uid)
            except Exception:
                logger.exception("Error processing Disk schedule for user %s", user_doc.get("user_id"))
    except Exception:
        logger.exception("Error scanning Disk schedules")


def _extract_schedule_key(drive_prefs: dict) -> Optional[str]:
    """מחלץ את ה-schedule key מתוך drive_prefs (תואם לפורמטים שונים)."""
    for field in ("schedule_key", "schedule"):
        val = drive_prefs.get(field)
        if isinstance(val, str) and val in SCHEDULE_INTERVALS:
            return val
        if isinstance(val, dict):
            inner = val.get("key") or val.get("value")
            if isinstance(inner, str) and inner in SCHEDULE_INTERVALS:
                return inner
    return None


def _scheduler_loop():
    """לולאת ה-scheduler הראשית."""
    logger.info("Backup scheduler started (scan every %ds)", SCAN_INTERVAL_SECONDS)
    # המתנה קצרה לתת לאפליקציה להתחיל
    time.sleep(30)
    while True:
        try:
            _scan_and_run()
        except Exception:
            logger.exception("Backup scheduler scan error")
        time.sleep(SCAN_INTERVAL_SECONDS)


def start_backup_scheduler():
    """מפעיל את ה-scheduler כ-daemon thread (קורא פעם אחת מ-app.py)."""
    global _scheduler_thread
    with _scheduler_lock:
        if _scheduler_thread is not None and _scheduler_thread.is_alive():
            return
        t = threading.Thread(target=_scheduler_loop, daemon=True, name="backup-scheduler")
        _scheduler_thread = t
        t.start()
        logger.info("Backup scheduler thread launched")


# --- פונקציות עזר לגיבוי מיידי (נקראות מה-API) ---

def trigger_drive_backup_now(user_id: int) -> dict:
    """מבצע גיבוי מיידי ל-Drive."""
    ok = _perform_drive_backup(user_id)
    return {"ok": ok}


def trigger_disk_backup_now(user_id: int) -> dict:
    """מבצע גיבוי מיידי לדיסק."""
    ok = _perform_disk_backup(user_id)
    return {"ok": ok}


def get_disk_backup_info(user_id: int) -> dict:
    """מחזיר מידע על גיבויי דיסק של המשתמש."""
    try:
        backup_dir = Path(DISK_BACKUP_DIR)
        if not backup_dir.exists():
            return {"count": 0, "total_size": 0, "backups": []}

        pattern = f"webapp_backup_{user_id}_*.zip"
        user_backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

        backups = []
        total_size = 0
        for bp in user_backups[:20]:
            try:
                stat = bp.stat()
                total_size += stat.st_size
                backups.append({
                    "name": bp.name,
                    "size": stat.st_size,
                    "created_at": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                })
            except Exception:
                pass

        return {"count": len(user_backups), "total_size": total_size, "backups": backups}
    except Exception:
        logger.exception("Error getting disk backup info for user %s", user_id)
        return {"count": 0, "total_size": 0, "backups": []}
