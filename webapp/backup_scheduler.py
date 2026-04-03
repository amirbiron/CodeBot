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


def _retry_next_at() -> str:
    """מחזיר timestamp של SCAN_INTERVAL קדימה — retry בסריקה הבאה, לא בלולאה הנוכחית."""
    return (_now_utc() + timedelta(seconds=SCAN_INTERVAL_SECONDS)).isoformat()


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
    """סורק וממריץ גיבויים עם atomic claiming (multi-worker safe).

    משתמש ב-find_one_and_update כדי "לתפוס" כל משתמש אטומית —
    רק scheduler אחד יכול להריץ גיבוי לכל משתמש, גם עם N workers.
    """
    try:
        from database import db
    except Exception:
        logger.exception("Cannot import database for backup scheduler")
        return

    now = _now_utc()
    now_iso = now.isoformat()

    # --- Drive backups (atomic claim) ---
    try:
        _scan_drive_backups(db, now_iso)
    except Exception:
        logger.exception("Error scanning Drive schedules")

    # --- Disk backups (atomic claim) ---
    try:
        _scan_disk_backups(db, now_iso)
    except Exception:
        logger.exception("Error scanning Disk schedules")


def _scan_drive_backups(db, now_iso: str):
    """סורק ומריץ גיבויי Drive עם atomic claiming."""
    valid_keys = list(SCHEDULE_INTERVALS.keys())
    while True:
        # תפוס אטומית משתמש שהגיע זמנו — מזיז schedule_next_at קדימה
        # כך ש-worker אחר לא יתפוס אותו
        claimed = db.db.users.find_one_and_update(
            {
                "drive_prefs.schedule_next_at": {"$lte": now_iso, "$ne": None},
                "drive_prefs.schedule_key": {"$ne": "off"},
                "$or": [
                    {"drive_prefs.schedule_key": {"$in": valid_keys}},
                    {"drive_prefs.schedule.key": {"$in": valid_keys}},
                    {"drive_prefs.schedule.value": {"$in": valid_keys}},
                    {"drive_prefs.schedule": {"$in": valid_keys}},
                ],
            },
            # מזיז את next_at רחוק קדימה (1 שעה) כ-placeholder עד שנחשב את הזמן האמיתי
            {"$set": {"drive_prefs.schedule_next_at": "2099-01-01T00:00:00+00:00"}},
            projection={"user_id": 1, "drive_prefs": 1},
        )
        if not claimed:
            break  # אין עוד משתמשים שצריכים גיבוי Drive

        uid = claimed.get("user_id")
        prefs = claimed.get("drive_prefs") or {}
        schedule_key = _extract_schedule_key(prefs)
        if not uid or not schedule_key:
            # החזרת sentinel — אחרת הגיבוי תקוע לנצח ב-2099
            _reset_drive_schedule(db, claimed)
            continue

        try:
            logger.info("Running scheduled Drive backup for user %s", uid)
            ok = _perform_drive_backup(uid)
            if ok:
                new_next = _compute_next_at(schedule_key)
            else:
                # דחייה קדימה — retry בסריקה הבאה, לא בלולאה הנוכחית
                new_next = _retry_next_at()
            db.db.users.update_one(
                {"user_id": uid},
                {"$set": {"drive_prefs.schedule_next_at": new_next}},
            )
        except Exception:
            logger.exception("Error processing Drive schedule for user %s", uid)
            try:
                db.db.users.update_one(
                    {"user_id": uid},
                    {"$set": {"drive_prefs.schedule_next_at": _retry_next_at()}},
                )
            except Exception:
                pass


def _scan_disk_backups(db, now_iso: str):
    """סורק ומריץ גיבויי דיסק עם atomic claiming."""
    valid_keys = list(SCHEDULE_INTERVALS.keys())
    while True:
        claimed = db.db.users.find_one_and_update(
            {
                "disk_backup_prefs.schedule_key": {"$in": valid_keys},
                "disk_backup_prefs.schedule_next_at": {"$lte": now_iso, "$ne": None},
            },
            {"$set": {"disk_backup_prefs.schedule_next_at": "2099-01-01T00:00:00+00:00"}},
            projection={"user_id": 1, "disk_backup_prefs": 1},
        )
        if not claimed:
            break

        uid = claimed.get("user_id")
        disk_prefs = claimed.get("disk_backup_prefs") or {}
        schedule_key = disk_prefs.get("schedule_key")
        if not uid or not schedule_key or schedule_key not in SCHEDULE_INTERVALS:
            # החזרת sentinel — אחרת הגיבוי תקוע לנצח ב-2099
            _reset_disk_schedule(db, claimed)
            continue

        try:
            logger.info("Running scheduled Disk backup for user %s", uid)
            ok = _perform_disk_backup(uid)
            if ok:
                update = {
                    "disk_backup_prefs.last_backup_at": _now_utc().isoformat(),
                    "disk_backup_prefs.schedule_next_at": _compute_next_at(schedule_key),
                }
            else:
                # דחייה קדימה — retry בסריקה הבאה, לא בלולאה הנוכחית
                update = {
                    "disk_backup_prefs.schedule_next_at": _retry_next_at(),
                }
            db.db.users.update_one({"user_id": uid}, {"$set": update})
        except Exception:
            logger.exception("Error processing Disk schedule for user %s", uid)
            try:
                db.db.users.update_one(
                    {"user_id": uid},
                    {"$set": {"disk_backup_prefs.schedule_next_at": _retry_next_at()}},
                )
            except Exception:
                pass


def _reset_drive_schedule(db, claimed: dict):
    """מחזיר schedule_next_at מ-sentinel ל-retry delay (Drive)."""
    try:
        uid = claimed.get("user_id")
        if uid:
            db.db.users.update_one(
                {"user_id": uid},
                {"$set": {"drive_prefs.schedule_next_at": _retry_next_at()}},
            )
    except Exception:
        logger.exception("Failed to reset Drive sentinel for user %s", claimed.get("user_id"))


def _reset_disk_schedule(db, claimed: dict):
    """מחזיר schedule_next_at מ-sentinel ל-retry delay (Disk)."""
    try:
        uid = claimed.get("user_id")
        if uid:
            db.db.users.update_one(
                {"user_id": uid},
                {"$set": {"disk_backup_prefs.schedule_next_at": _retry_next_at()}},
            )
    except Exception:
        logger.exception("Failed to reset Disk sentinel for user %s", claimed.get("user_id"))


def _extract_schedule_key(drive_prefs: dict) -> Optional[str]:
    """מחלץ את ה-schedule key מתוך drive_prefs (תואם לפורמטים שונים)."""
    # אם המשתמש כיבה מפורשות — לא ליפול לשדות legacy
    if drive_prefs.get("schedule_key") == "off":
        return None
    for field in ("schedule_key", "schedule"):
        val = drive_prefs.get(field)
        if isinstance(val, str) and val in SCHEDULE_INTERVALS:
            return val
        if isinstance(val, dict):
            for inner_field in ("key", "value"):
                inner = val.get(inner_field)
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
