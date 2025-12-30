"""
רישום כל ה-Background Jobs במערכת.
יש לייבא קובץ זה ב-main.py לאחר אתחול ה-Application.
"""

import os

from services.job_registry import register_job, JobCategory, JobType


def register_all_jobs():
    """רישום כל ה-Jobs המוכרים"""

    # === Backup Jobs ===
    register_job(
        job_id="backups_cleanup",
        name="ניקוי גיבויים",
        description="מחיקת גיבויים ישנים לפי מדיניות retention",
        category=JobCategory.CLEANUP,
        job_type=JobType.REPEATING,
        interval_seconds=86400,
        env_toggle="BACKUPS_CLEANUP_ENABLED",
        callback_name="_backups_cleanup_job",
        source_file="main.py",
    )

    # === Cache Jobs ===
    register_job(
        job_id="cache_maintenance",
        name="תחזוקת קאש",
        description="ניקוי רשומות קאש שפגו תוקפן",
        category=JobCategory.CACHE,
        job_type=JobType.REPEATING,
        interval_seconds=600,
        enabled=True,
        callback_name="_cache_maintenance_job",
        source_file="main.py",
    )

    register_job(
        job_id="cache_warming",
        name="חימום קאש",
        description="טעינה מראש של נתונים נפוצים לקאש",
        category=JobCategory.CACHE,
        job_type=JobType.REPEATING,
        interval_seconds=900,
        env_toggle="CACHE_WARMING_ENABLED",
        # main.py מתייחס ל-CACHE_WARMING_ENABLED כברירת מחדל = true,
        # לכן ה-UI צריך להציג את הג'וב כפעיל גם אם ה-ENV לא מוגדר.
        env_toggle_default=True,
        callback_name="_cache_warming_job",
        source_file="main.py",
    )

    # === Drive Sync Jobs ===
    register_job(
        job_id="drive_reschedule",
        name="תזמון Drive",
        description="שמירה על תזמוני גיבוי אוטומטי ל-Google Drive",
        category=JobCategory.SYNC,
        job_type=JobType.REPEATING,
        interval_seconds=900,
        enabled=True,
        callback_name="_reschedule_drive_jobs",
        source_file="main.py",
    )

    # === Monitoring Jobs ===
    register_job(
        job_id="sentry_poll",
        name="סקירת Sentry",
        description="משיכת אירועים חדשים מ-Sentry",
        category=JobCategory.MONITORING,
        job_type=JobType.REPEATING,
        interval_seconds=300,
        env_toggle="SENTRY_POLL_ENABLED",
        # הערה: ברירת המחדל נקבעת לפי קיום SENTRY_DSN - אם מוגדר, הג'וב פעיל.
        # זה תואם את ההתנהגות ב-main.py שמפעיל את הג'וב אם יש DSN.
        env_toggle_default=bool(os.getenv("SENTRY_DSN")),
        callback_name="_sentry_poll_job",
        source_file="main.py",
    )

    register_job(
        job_id="predictive_sampler",
        name="דגימה חזויה",
        description="איסוף מדדים לזיהוי אנומליות",
        category=JobCategory.MONITORING,
        job_type=JobType.REPEATING,
        interval_seconds=60,
        enabled=True,
        callback_name="_predictive_sampler_job",
        source_file="main.py",
    )

    register_job(
        job_id="weekly_admin_report",
        name="דו\"ח שבועי",
        description="שליחת דו\"ח סיכום שבועי לאדמינים",
        category=JobCategory.MONITORING,
        job_type=JobType.REPEATING,
        interval_seconds=7 * 24 * 3600,
        enabled=True,
        callback_name="_weekly_admin_report",
        source_file="main.py",
    )

    # === Reminders ===
    register_job(
        job_id="recurring_reminders_check",
        name="בדיקת תזכורות",
        description="עיבוד תזכורות חוזרות",
        category=JobCategory.OTHER,
        job_type=JobType.REPEATING,
        interval_seconds=3600,
        enabled=True,
        callback_name="_check_recurring_reminders",
        source_file="reminders/scheduler.py",
    )

    # === Batch Processing ===
    register_job(
        job_id="batch_analyze",
        name="ניתוח קבצים",
        description="ניתוח batch של קבצים",
        category=JobCategory.BATCH,
        job_type=JobType.ON_DEMAND,
        callback_name="analyze_files_batch",
        source_file="batch_processor.py",
    )

    register_job(
        job_id="batch_validate",
        name="בדיקת תקינות",
        description="בדיקת תקינות batch של קבצים",
        category=JobCategory.BATCH,
        job_type=JobType.ON_DEMAND,
        callback_name="validate_files_batch",
        source_file="batch_processor.py",
    )

    register_job(
        job_id="batch_export",
        name="ייצוא קבצים",
        description="ייצוא batch של קבצים",
        category=JobCategory.BATCH,
        job_type=JobType.ON_DEMAND,
        callback_name="export_files_batch",
        source_file="batch_processor.py",
    )

