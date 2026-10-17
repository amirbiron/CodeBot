"""
Webapp Backup Scheduler — גיבויים אוטומטיים ל-Drive ולדיסק.

Thread daemon שרץ ברקע וסורק כל כמה דקות אם יש משתמשים
שצריכים גיבוי אוטומטי (לפי schedule_next_at).

גיבויי ה-Drive כאן הם של הוובאפ בלבד: הסריקה קוראת וכותבת רק את ההעדפות של הוובאפ, וההעלאה משתמשת בחיבור שלו (``drive_owner.WEBAPP``). את התזמון של הבוט מריץ הבוט — ראו drive_owner.py.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from pymongo.errors import PyMongoError

from drive_owner import WEBAPP as DRIVE_OWNER, drive_fields

logger = logging.getLogger(__name__)

try:
    from observability import emit_event
except Exception:
    # כמו בשאר מודולי הוובאפ: בלי מודול התצפית המתזמן ממשיך לרוץ, וכל כשל גיבוי עדיין נרשם בלוג של המודול
    def emit_event(event: str, severity: str = "info", **fields):
        return None

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

# מקסימום גיבויים לכל סוג בסריקה אחת — מונע הרעבה של disk כש-drive תקוע
MAX_BACKUPS_PER_SCAN = int(os.getenv("MAX_BACKUPS_PER_SCAN", "10"))

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


#: כמה כשלים רצופים מנוסים שוב לפני שמוותרים על המועד הנוכחי. ההמתנה לפני כל ניסיון גדלה (``_retry_delay_seconds``), ואחרי הניסיון האחרון הגיבוי עובר למועד הרגיל הבא של התזמון (``_compute_next_at``) והמונה מתאפס — מצב סופי לכשל שאינו חולף, במקום ניסיון כל ``SCAN_INTERVAL_SECONDS`` בלי סוף.
RETRY_MAX_ATTEMPTS = 6

#: מונה הכשלים הרצופים, בהעדפות של כל תזמון (``webapp_drive_prefs``, ``disk_backup_prefs``). מתאפס בהצלחה, בהשהיה (``_pause_drive_schedule``) ובוויתור.
_FAILURES_KEY = "consecutive_failures"


def _retry_delay_seconds(attempt: int) -> int:
    """ההמתנה לפני ניסיון חוזר מספר ``attempt`` (מ-1): ``SCAN_INTERVAL_SECONDS``, ומשם כפול 2 בכל ניסיון."""
    return SCAN_INTERVAL_SECONDS * (2 ** (attempt - 1))


def _stored_failures(prefs: Any) -> int:
    """מונה הכשלים כפי שנקרא מהמסמך שהתפיסה (``find_one_and_update``) החזירה — קריאה טרייה מהמסד, לא מקאש.

    ההעדפות יכולות להגיע גם מגיבוי אישי ששוחזר (``PersonalBackupService._restore_drive_prefs`` כותב אותן כמו שהן), ולכן ערך שאינו מספר שלם אי-שלילי — חסר, ``bool`` (שהוא ``int`` בפייתון), מחרוזת — נקרא כאפס.
    """
    value = prefs.get(_FAILURES_KEY) if isinstance(prefs, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _after_failure(schedule_key: str, previous_failures: int) -> Tuple[Dict[str, Any], bool]:
    """מצב התזמון אחרי כשל: ``schedule_next_at`` והמונה, ו-``True`` כשהניסיונות מוצו (``RETRY_MAX_ATTEMPTS``) והגיבוי עבר למועד הרגיל הבא."""
    attempt = previous_failures + 1
    if attempt > RETRY_MAX_ATTEMPTS:
        return {"schedule_next_at": _compute_next_at(schedule_key), _FAILURES_KEY: 0}, True
    next_at = (_now_utc() + timedelta(seconds=_retry_delay_seconds(attempt))).isoformat()
    return {"schedule_next_at": next_at, _FAILURES_KEY: attempt}, False


def _finish_claim(db, user_id: int, prefs_field: str, held_sentinel: str, values: Dict[str, Any]) -> bool:
    """כותב את מצב התזמון אחרי הגיבוי (``values``, מפתחות בתוך ``prefs_field``) — רק אם הסריקה עדיין מחזיקה בו, כלומר ``schedule_next_at`` הוא עדיין הסנטינל שהיא כתבה בתפיסה.

    המשתמש יכול לשנות תזמון בזמן שגיבוי רץ (``/api/drive/schedule``, ``/api/disk-backup/schedule``). כתיבה לפי ``user_id`` בלבד דרסה את הבחירה שלו במועד שהסריקה חישבה; כאן הבחירה שלו נשארת, והגיבוי ירוץ במועד שהוא קבע. מחזיר ``True`` כשהמצב נכתב; שגיאת מסד עולה כ-``PyMongoError``.
    """
    res = db.db.users.update_one(
        {"user_id": int(user_id), f"{prefs_field}.schedule_next_at": held_sentinel},
        {"$set": {f"{prefs_field}.{key}": value for key, value in values.items()}},
    )
    if not res.matched_count:
        logger.info("Backup schedule %s of user %s changed during the backup; left as the user set it", prefs_field, user_id)
    return bool(res.matched_count)


def _record_failed_attempt(db, user_id: int, prefs_field: str, held_sentinel: str, schedule_key: str, previous_failures: int, *, target: str) -> None:
    """כשל של גיבוי מתוזמן: קובע את הניסיון הבא אחרי המתנה שגדלה (``_after_failure``), ואחרי ``RETRY_MAX_ATTEMPTS`` עובר למועד הרגיל ושולח ``webapp_backup_retries_exhausted`` (``target``: ``drive`` או ``disk``). הכתיבה מותנית בסנטינל (``_finish_claim``)."""
    values, exhausted = _after_failure(schedule_key, previous_failures)
    if _finish_claim(db, user_id, prefs_field, held_sentinel, values) and exhausted:
        emit_event(
            "webapp_backup_retries_exhausted",
            severity="warn",
            user_id=int(user_id),
            target=target,
            attempts=RETRY_MAX_ATTEMPTS,
        )


#: סיבות הכישלון של ``_perform_drive_backup``. הן גם ה-``reason`` של ``webapp_drive_backup_failed``.
FAILURE_AUTH_REQUIRED = "auth_required"
FAILURE_CONNECTION = "connection_failed"
FAILURE_UPLOAD = "upload_failed"
FAILURE_EXCEPTION = "exception"


@dataclass(frozen=True)
class DriveBackupOutcome:
    """התוצאה של ``_perform_drive_backup``: ``failure`` הוא ``None`` בהצלחה, ואחרת אחד מ-``FAILURE_*`` — כדי שהקורא יבדיל בין חיבור שמת (``FAILURE_AUTH_REQUIRED``, שבו התזמון מושהה) לבין כשל שכדאי לנסות שוב."""

    ok: bool
    failure: Optional[str] = None


#: הסימון בהעדפות של הוובאפ שגוגל דחה את החיבור — זמן הדחייה הראשונה, או ``None``. הממשק קורא אותו כ-``needs_reconnect`` (``/api/drive/status``).
_AUTH_REQUIRED_KEY = "auth_required_at"


def _emit_drive_backup_failed(
    user_id: int,
    *,
    reason: str,
    error_type: Optional[str] = None,
    connection_status: Optional[str] = None,
    oauth_error: Optional[str] = None,
) -> None:
    """אירוע ``webapp_drive_backup_failed`` — גיבוי Drive של הוובאפ (מתוזמן או "גבה עכשיו") שלא הועלה.

    ``reason`` הוא אחד מ-``FAILURE_*``: ``FAILURE_AUTH_REQUIRED`` כשגוגל דחה את החיבור (``oauth_error``), ``FAILURE_CONNECTION`` כשבדיקת החיבור לא עברה מסיבה אחרת (``connection_status`` מ-``check_connection``, ו-``oauth_error`` כשיש), ``FAILURE_UPLOAD`` כשההעלאה החזירה ``None`` (הסיבה בשורת ``drive_call_failed`` של ``services/google_drive_service.py``), או ``FAILURE_EXCEPTION`` עם ``error_type``. רמת ``warn`` ולא ``error``: כשל מתוזמן שאינו חיבור שמת מנוסה שוב אחרי המתנה שגדלה (``_record_failed_attempt``).

    המטען נבנה כאן עם מפתחות קבועים — ``tests/test_event_alert_dispatch.py`` אוסר להעביר ל-``emit_event`` ב-``**`` מטען שאי אפשר לקרוא את המפתחות שלו בנקודת הקריאה. שדה בלי ערך לא נכנס לאירוע.
    """
    payload: Dict[str, Any] = {"user_id": int(user_id), "reason": reason}
    if error_type is not None:
        payload["error_type"] = error_type
    if connection_status is not None:
        payload["connection_status"] = connection_status
    if oauth_error is not None:
        payload["oauth_error"] = oauth_error
    emit_event("webapp_drive_backup_failed", severity="warn", **payload)


def _auth_required_field() -> str:
    return f"{drive_fields(DRIVE_OWNER).prefs}.{_AUTH_REQUIRED_KEY}"


def _record_drive_auth_required(db, user_id: int) -> None:
    """רושם בהעדפות של הוובאפ שגוגל דחה את החיבור (``_AUTH_REQUIRED_KEY``), כדי שהממשק יבקש להתחבר מחדש.

    נכתב רק כשאין כבר סימון — ``None`` בפילטר של מונגו תואם גם שדה חסר — ולכן הזמן הוא של הדחייה הראשונה. כשל מסד נרשם ולא עולה: הגיבוי כבר נכשל, ו"גבה עכשיו" אומר למשתמש להתחבר מחדש גם בלי הסימון. ההשהיה של גיבוי מתוזמן אינה נשענת על הכתיבה הזו: ``_pause_drive_schedule`` כותב את הסימון בעצמו, באותה כתיבה, כך שכשל כאן לא משאיר תזמון מושהה שהממשק מציג כ"מחובר".
    """
    field = _auth_required_field()
    try:
        db.db.users.update_one(
            {"user_id": int(user_id), field: None},
            {"$set": {field: _now_utc().isoformat()}},
        )
    except PyMongoError:
        logger.exception("Failed to record Drive auth_required for user %s", user_id)


def clear_drive_auth_required(db, user_id: int) -> None:
    """מוחק את הסימון ``_AUTH_REQUIRED_KEY`` כשהחיבור הוכח כחי: בדיקת חיבור שעברה (``_perform_drive_backup``), או חיבור מחדש (``resume_drive_schedule_after_reconnect``).

    הסימון מתאר את מה שגוגל ענה, ולכן הוא נמחק רק כשגוגל ענה אחרת, ולא בכל כתיבה של העדפות. כשל מסד נרשם ולא עולה: גיבוי שהחיבור שלו עבר אינו נכשל בגלל סימון תצוגה שלא נמחק.
    """
    field = _auth_required_field()
    try:
        db.db.users.update_one(
            {"user_id": int(user_id), field: {"$ne": None}},
            {"$set": {field: None}},
        )
    except PyMongoError:
        logger.exception("Failed to clear Drive auth_required for user %s", user_id)


def resume_drive_schedule_after_reconnect(db, user_id: int) -> None:
    """אחרי חיבור מחדש בוובאפ (``webapp/drive_auth.py``): מחזיר לפעולה תזמון שהושהה, ומוחק את הסימון.

    תזמון מושהה (``_pause_drive_schedule``) הוא ``schedule_key`` תקף עם ``schedule_next_at`` ריק — צירוף שרק ההשהיה כותבת: ``/api/drive/schedule`` כותב מועד לכל תזמון תקף, וניתוק וכיבוי כותבים ``off``. המועד החדש הוא עכשיו, כי הגיבוי שלא רץ כבר באיחור, והוא רץ בסריקה הבאה. תזמון שסריקה מחזיקה ברגע זה נושא סנטינל ולא ``None``, ולכן אינו נדרס. כשל מסד נרשם ולא עולה: החיבור עצמו כבר נשמר.
    """
    prefs_field = drive_fields(DRIVE_OWNER).prefs
    try:
        db.db.users.update_one(
            {
                "user_id": int(user_id),
                f"{prefs_field}.schedule_key": {"$in": list(SCHEDULE_INTERVALS.keys())},
                f"{prefs_field}.schedule_next_at": None,
            },
            {"$set": {f"{prefs_field}.schedule_next_at": _now_utc().isoformat()}},
        )
    except PyMongoError:
        logger.exception("Failed to resume Drive schedule after reconnect for user %s", user_id)
    clear_drive_auth_required(db, user_id)


def _pause_drive_schedule(db, user_id: int, held_sentinel: str) -> bool:
    """משהה את התזמון של משתמש שגוגל דחה את החיבור שלו: ``schedule_next_at`` ריק, ולכן מסנן התפיסה (``_drive_claim_filter``, ``$ne: None``) מדלג עליו עד ש-``resume_drive_schedule_after_reconnect`` מחזיר אותו.

    זה המצב הסופי שחסר עד כאן: גיבוי כזה נוסה שוב בכל סריקה, בלי סוף, וכל ניסיון בנה ZIP מלא. הכתיבה מותנית בסנטינל שהסריקה הזו כתבה בתפיסה (``held_sentinel``) — אם המשתמש שינה את התזמון בזמן שהבדיקה רצה, הערך שלו נשאר, והוא ייבדק במועד שלו בקריאה אחת לגוגל, בלי ZIP.

    **אין השהיה בלי סימון.** תזמון מושהה רץ שוב רק אחרי חיבור מחדש, והמשתמש יודע שצריך להתחבר מחדש רק מהסימון (``_AUTH_REQUIRED_KEY``, שהממשק קורא כ-``needs_reconnect``). לכן כל כתיבה של השהיה גם כותבת את הסימון, או דורשת בפילטר שהוא כבר שם — בלי להישען על ``_record_drive_auth_required``, שכשל בו רק נרשם. הכתיבה הראשונה משהה ומסמנת כשאין סימון; השנייה, כשיש, משהה ומשאירה את זמן הדחייה הראשונה. כל אחת מהן אטומית עם התנאי שלה, ולכן גם חיבור מחדש שמוחק את הסימון בין שתיהן לא משאיר השהיה בלי סימון: אז שתיהן לא תואמות, הסנטינל נשאר עד שהוא פג (``SENTINEL_TTL_SECONDS``), והבדיקה הבאה רואה חיבור חי.

    מחזיר ``True`` כשההשהיה נכתבה; שגיאת מסד עולה כ-``PyMongoError``.
    """
    prefs_field = drive_fields(DRIVE_OWNER).prefs
    next_at_field = f"{prefs_field}.schedule_next_at"
    marker_field = _auth_required_field()
    # המונה מתאפס: אחרי חיבור מחדש מתחילים לספור כשלים מאפס
    paused = {next_at_field: None, f"{prefs_field}.{_FAILURES_KEY}": 0}
    held = {"user_id": int(user_id), next_at_field: held_sentinel}
    unmarked = db.db.users.update_one(
        {**held, marker_field: None},
        {"$set": {**paused, marker_field: _now_utc().isoformat()}},
    )
    if unmarked.matched_count:
        return True
    marked = db.db.users.update_one(
        {**held, marker_field: {"$ne": None}},
        {"$set": paused},
    )
    return bool(marked.matched_count)


def _perform_drive_backup(user_id: int) -> DriveBackupOutcome:
    """מבצע גיבוי מלא אישי ל-Drive (קבצים, אוספים, סימניות, הגדרות). כל כשל נשלח גם כאירוע (``_emit_drive_backup_failed``).

    **קודם החיבור, אחר כך ה-ZIP.** ``check_connection`` מחדש את הטוקן מול גוגל לפני שנבנה משהו, כך שחיבור שמת עולה קריאה אחת לשרת הטוקנים ולא ייצוא מלא שנזרק אחרי שההעלאה נכשלה. כשגוגל דוחה את החיבור נכתב הסימון לממשק (``_record_drive_auth_required``) ומוחזר ``FAILURE_AUTH_REQUIRED``; כשהבדיקה עוברת, סימון ישן נמחק (``clear_drive_auth_required``).

    החריגה הכללית בסוף היא גבול של ג'וב: היא נרשמת עם traceback ומובילה ל-``FAILURE_EXCEPTION``, מצב משלה, ולא לאחד ממצבי החיבור.
    """
    try:
        from services.personal_backup_service import PersonalBackupService
        from services.google_drive_service import CONNECTION_AUTH_REQUIRED, CONNECTION_OK, check_connection, upload_bytes
        from database import db

        check = check_connection(int(user_id), owner=DRIVE_OWNER)
        if check.status == CONNECTION_AUTH_REQUIRED:
            _record_drive_auth_required(db, int(user_id))
            _emit_drive_backup_failed(user_id, reason=FAILURE_AUTH_REQUIRED, oauth_error=check.oauth_error)
            return DriveBackupOutcome(False, FAILURE_AUTH_REQUIRED)
        if check.status != CONNECTION_OK:
            _emit_drive_backup_failed(
                user_id,
                reason=FAILURE_CONNECTION,
                connection_status=check.status,
                oauth_error=check.oauth_error,
            )
            return DriveBackupOutcome(False, FAILURE_CONNECTION)
        clear_drive_auth_required(db, int(user_id))

        service = PersonalBackupService(db)
        buffer = service.export_user_data(int(user_id))
        zip_bytes = buffer.getvalue()

        ts = _now_utc().strftime("%Y%m%d_%H%M%S")
        filename = f"codebot_full_backup_{user_id}_{ts}.zip"

        file_id = upload_bytes(int(user_id), filename, zip_bytes, owner=DRIVE_OWNER)
        if file_id:
            logger.info("Drive full backup uploaded for user %s (%d bytes)", user_id, len(zip_bytes))
            # עדכון last_backup_at — best-effort, כשל DB לא אמור לגרום לretry ושכפול גיבוי
            try:
                db.db.users.update_one(
                    {"user_id": int(user_id)},
                    {"$set": {f"{drive_fields(DRIVE_OWNER).prefs}.last_backup_at": _now_utc().isoformat()}},
                )
            except Exception:
                logger.warning("Failed to update Drive last_backup_at for user %s", user_id, exc_info=True)
            return DriveBackupOutcome(True)
        else:
            logger.warning("Drive full backup upload failed for user %s", user_id)
            _emit_drive_backup_failed(user_id, reason=FAILURE_UPLOAD)
            return DriveBackupOutcome(False, FAILURE_UPLOAD)
    except Exception as e:
        logger.exception("Drive backup error for user %s", user_id)
        _emit_drive_backup_failed(user_id, reason=FAILURE_EXCEPTION, error_type=type(e).__name__)
        return DriveBackupOutcome(False, FAILURE_EXCEPTION)


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

        ts = _now_utc().strftime("%Y%m%d_%H%M%S_%f")
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
    """מנקה גיבויים ישנים לפי retention ו-max per user.

    לוגיקה: ה-N הכי חדשים (עד DISK_BACKUP_MAX_PER_USER) נשמרים תמיד.
    מעבר ל-max — נמחקים רק אם גם עברו את ה-retention.
    """
    try:
        pattern = f"webapp_backup_{user_id}_*.zip"
        user_backups = sorted(backup_dir.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)

        cutoff = _now_utc() - timedelta(days=DISK_BACKUP_RETENTION_DAYS)
        for i, bp in enumerate(user_backups):
            try:
                # ה-N הכי חדשים נשמרים תמיד
                if i < DISK_BACKUP_MAX_PER_USER:
                    continue
                # מעבר ל-max — מוחקים אם עברו retention
                mtime = datetime.fromtimestamp(bp.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    bp.unlink()
                    logger.info("Cleaned up old backup: %s", bp.name)
            except Exception:
                logger.exception("Error cleaning up backup: %s", bp)
    except Exception:
        logger.exception("Error in disk backup cleanup for user %s", user_id)


# TTL ל-sentinel — אחרי כמה זמן claim שלא הושלם פוקע טבעית
SENTINEL_TTL_SECONDS = int(os.getenv("BACKUP_SENTINEL_TTL", "1800"))  # 30 דקות


def _sentinel_value() -> str:
    """מחזיר sentinel שפוקע טבעית אחרי SENTINEL_TTL.

    במקום ערך קבוע "2099", משתמשים ב-now + TTL.
    אם ה-backup מסתיים — הערך מוחלף בזמן הבא האמיתי.
    אם ה-process קרס — אחרי TTL הערך הופך ל-$lte now ונתפס מחדש.
    """
    return (_now_utc() + timedelta(seconds=SENTINEL_TTL_SECONDS)).isoformat()


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


def _drive_claim_filter(now_iso: str) -> dict:
    """הפילטר שבו הסריקה תופסת משתמש שהגיע זמן גיבוי ה-Drive שלו: תזמון של הוובאפ (``schedule_key``) ש-``schedule_next_at`` שלו עבר.

    הסריקה רצה כל ``SCAN_INTERVAL_SECONDS`` על אוסף המשתמשים, ולכן יש לה אינדקס משלה ב-``DatabaseManager._create_indexes`` — על שני השדות האלה, בסדר הזה: ``schedule_key`` (שוויון, ``$in``) ואחריו ``schedule_next_at`` (טווח). ``tests/test_webapp_drive_scan_index.py`` משווה בין השניים.
    """
    prefs_field = drive_fields(DRIVE_OWNER).prefs
    return {
        f"{prefs_field}.schedule_key": {"$in": list(SCHEDULE_INTERVALS.keys())},
        f"{prefs_field}.schedule_next_at": {"$lte": now_iso, "$ne": None},
    }


def _scan_drive_backups(db, now_iso: str):
    """סורק ומריץ גיבויי Drive עם atomic claiming — רק תזמונים של הוובאפ.

    הוובאפ כותב את התזמון שלו כ-``schedule_key`` (``/api/drive/schedule``) ומחזיר אותו מאותו שדה (``/api/drive/status``), ולכן התפיסה מסננת עליו בלבד, כמו בגיבויי הדיסק. הצורות האחרות (``schedule``, ``schedule.key`` וכו') הן של הבוט — הבוט כותב ``schedule`` (``handlers/drive/menu.py``) ומריץ את התזמון שלו בעצמו — וסריקה שתפסה גם אותן היא שגרמה לשני המתזמנים להריץ את אותו תזמון. העדפות ששוחזרו מגיבוי אישי (``PersonalBackupService._restore_drive_prefs``) נכתבות כמו שהן; תזמון שנשמר שם בצורה של הבוט לא ירוץ כאן, וגם ``/api/drive/status`` לא יחזיר אותו.
    """
    prefs_field = drive_fields(DRIVE_OWNER).prefs
    next_at_field = f"{prefs_field}.schedule_next_at"
    processed = 0
    while processed < MAX_BACKUPS_PER_SCAN:
        # תפוס אטומית משתמש שהגיע זמנו — מזיז schedule_next_at קדימה
        # כך ש-worker אחר לא יתפוס אותו. הסנטינל נשמר: הכתיבה שבסוף (_finish_claim, _pause_drive_schedule) נכתבת רק אם הוא עדיין שם
        sentinel = _sentinel_value()
        claimed = db.db.users.find_one_and_update(
            _drive_claim_filter(now_iso),
            # מזיז את next_at קדימה כ-placeholder עד שנחשב את הזמן האמיתי
            {"$set": {next_at_field: sentinel}},
            projection={"user_id": 1, prefs_field: 1},
        )
        if not claimed:
            break  # אין עוד משתמשים שצריכים גיבוי Drive
        processed += 1

        uid = claimed.get("user_id")
        prefs = claimed.get(prefs_field) or {}
        schedule_key = prefs.get("schedule_key") if isinstance(prefs, dict) else None
        if not uid or not isinstance(schedule_key, str) or schedule_key not in SCHEDULE_INTERVALS:
            # החזרת sentinel — אחרת הגיבוי תקוע עד שה-sentinel פג
            _reset_drive_schedule(db, claimed)
            continue

        failures = _stored_failures(prefs)
        logger.info("Running scheduled Drive backup for user %s", uid)
        # הגבול של הגיבוי עצמו: _perform_drive_backup אינו זורק, וכל כשל בו חוזר כ-outcome.failure
        outcome = _perform_drive_backup(uid)
        try:
            if outcome.failure == FAILURE_AUTH_REQUIRED:
                # מצב סופי: לא מנסים שוב עם חיבור שגוגל דחה — ממתינים לחיבור מחדש
                if not _pause_drive_schedule(db, uid, sentinel):
                    logger.info("Drive schedule of user %s changed during the backup; left as the user set it", uid)
                continue
            if outcome.ok:
                _finish_claim(db, uid, prefs_field, sentinel, {"schedule_next_at": _compute_next_at(schedule_key), _FAILURES_KEY: 0})
            else:
                _record_failed_attempt(db, uid, prefs_field, sentinel, schedule_key, failures, target="drive")
        except PyMongoError:
            # כשל בכתיבת התזמון אינו כשל של הגיבוי: לא סופרים ניסיון ולא מתזמנים ניסיון חוזר (עוד בדיקת חיבור ועוד אירוע כשל),
            # והסנטינל נשאר עד שהוא פג (SENTINEL_TTL_SECONDS) — ואז הסריקה תופסת את המשתמש שוב
            logger.exception("Failed to write the Drive schedule of user %s after the backup; the claim expires and is taken again", uid)


def _scan_disk_backups(db, now_iso: str):
    """סורק ומריץ גיבויי דיסק עם atomic claiming."""
    valid_keys = list(SCHEDULE_INTERVALS.keys())
    processed = 0
    while processed < MAX_BACKUPS_PER_SCAN:
        # הסנטינל נשמר: הכתיבה שבסוף הגיבוי (_finish_claim) נכתבת רק אם הוא עדיין שם
        sentinel = _sentinel_value()
        claimed = db.db.users.find_one_and_update(
            {
                "disk_backup_prefs.schedule_key": {"$in": valid_keys},
                "disk_backup_prefs.schedule_next_at": {"$lte": now_iso, "$ne": None},
            },
            {"$set": {"disk_backup_prefs.schedule_next_at": sentinel}},
            projection={"user_id": 1, "disk_backup_prefs": 1},
        )
        if not claimed:
            break
        processed += 1

        uid = claimed.get("user_id")
        disk_prefs = claimed.get("disk_backup_prefs") or {}
        schedule_key = disk_prefs.get("schedule_key")
        if not uid or not schedule_key or schedule_key not in SCHEDULE_INTERVALS:
            # החזרת sentinel — אחרת הגיבוי תקוע לנצח ב-2099
            _reset_disk_schedule(db, claimed)
            continue

        failures = _stored_failures(disk_prefs)
        try:
            logger.info("Running scheduled Disk backup for user %s", uid)
            ok = _perform_disk_backup(uid)
            if ok:
                # last_backup_at מתאר את הגיבוי שנכתב לדיסק, ולכן הוא נכתב קודם ובנפרד מהתזמון: גם כשהמשתמש שינה את התזמון בינתיים, וגם כשכתיבת התזמון נכשלת
                try:
                    db.db.users.update_one({"user_id": uid}, {"$set": {"disk_backup_prefs.last_backup_at": _now_utc().isoformat()}})
                except PyMongoError:
                    logger.warning("Failed to update Disk last_backup_at for user %s", uid, exc_info=True)
                _finish_claim(db, uid, "disk_backup_prefs", sentinel, {"schedule_next_at": _compute_next_at(schedule_key), _FAILURES_KEY: 0})
            else:
                _record_failed_attempt(db, uid, "disk_backup_prefs", sentinel, schedule_key, failures, target="disk")
        except Exception:
            logger.exception("Error processing Disk schedule for user %s", uid)
            try:
                _record_failed_attempt(db, uid, "disk_backup_prefs", sentinel, schedule_key, failures, target="disk")
            except Exception:
                # בלי הכתיבה הסנטינל נשאר עד שהוא פג (SENTINEL_TTL_SECONDS), ואז הגיבוי נתפס שוב
                logger.exception("Failed to reschedule Disk backup for user %s", uid)


def _reset_drive_schedule(db, claimed: dict):
    """מחזיר schedule_next_at מ-sentinel ל-retry delay (Drive, התזמון של הוובאפ)."""
    try:
        uid = claimed.get("user_id")
        if uid:
            db.db.users.update_one(
                {"user_id": uid},
                {"$set": {f"{drive_fields(DRIVE_OWNER).prefs}.schedule_next_at": _retry_next_at()}},
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
    """מבצע גיבוי מיידי ל-Drive, ומחזיר ``{"ok": ..., "failure": ...}`` — ``failure`` הוא ``None`` או אחד מ-``FAILURE_*``, כדי ש"גבה עכשיו" יבקש להתחבר מחדש כשזו הסיבה.

    הערה: ``_perform_drive_backup`` כבר מעדכן את last_backup_at של הוובאפ אחרי העלאה מוצלחת,
    אז לא מעדכנים שוב כאן. גם כשהחיבור נדחה, התזמון אינו מושהה מכאן: אין כאן תפיסה של הסורק, והגיבוי המתוזמן הבא יגלה את הדחייה בעצמו, בקריאה אחת לגוגל, וישהה את עצמו.
    """
    outcome = _perform_drive_backup(user_id)
    return {"ok": outcome.ok, "failure": outcome.failure}


def trigger_disk_backup_now(user_id: int) -> dict:
    """מבצע גיבוי מיידי לדיסק."""
    ok = _perform_disk_backup(user_id)
    if ok:
        try:
            from database import db
            db.db.users.update_one(
                {"user_id": int(user_id)},
                {"$set": {"disk_backup_prefs.last_backup_at": _now_utc().isoformat()}},
            )
        except Exception:
            logger.warning("Failed to update Disk last_backup_at for user %s", user_id)
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
        for i, bp in enumerate(user_backups):
            try:
                stat = bp.stat()
                total_size += stat.st_size
                if i < 20:  # מחזירים רק 20 לתצוגה, אבל סוכמים את כולם
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
