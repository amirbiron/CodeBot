# Background Jobs Monitor – מדריך מימוש

> **מתי להשתמש:** כאשר רוצים ליצור מסך ניהול מרכזי לכל ה-jobs הרצים ברקע  
> **קהל יעד:** מפתחים, DevOps, אדמינים  
> **מצב נוכחי:** מדריך מימוש (טרם מומש)

---

## תוכן עניינים

1. [סקירת Jobs קיימים](#סקירת-jobs-קיימים)
2. [ארכיטקטורה מוצעת](#ארכיטקטורה-מוצעת)
3. [מודל נתונים](#מודל-נתונים)
4. [Backend Implementation](#backend-implementation)
5. [Frontend – מסך Monitor](#frontend--מסך-monitor)
6. [API Endpoints](#api-endpoints)
7. [אינטגרציה עם המערכת הקיימת](#אינטגרציה-עם-המערכת-הקיימת)
8. [ChatOps Commands](#chatops-commands)
9. [Observability & Alerts](#observability--alerts)
10. [בדיקות](#בדיקות)
11. [שיקולי ביצועים](#שיקולי-ביצועים)

---

## סקירת Jobs קיימים

המערכת כוללת מספר Background Jobs שרצים באמצעות `telegram.ext.JobQueue` (מבוסס APScheduler):

### 1. גיבויים (Backups)

| Job | מיקום | תדירות | תיאור |
|-----|-------|--------|-------|
| `backups_cleanup` | `main.py` | כל 24 שעות | ניקוי גיבויים ישנים לפי retention |
| `BackupManager.cleanup_expired_backups()` | `file_manager.py` | - | לוגיקת הניקוי בפועל |

**משתני סביבה:**
```bash
BACKUPS_CLEANUP_ENABLED=true          # הפעלת Job הניקוי
BACKUPS_CLEANUP_INTERVAL_SECS=86400   # אינטרוול (ברירת מחדל: 24 שעות)
BACKUPS_CLEANUP_FIRST_SECS=180        # השהייה ראשונה אחרי startup
BACKUPS_RETENTION_DAYS=30             # ימי שמירת גיבויים
BACKUPS_MAX_PER_USER=10               # מקסימום גיבויים למשתמש
```

### 2. Cache Maintenance

| Job | מיקום | תדירות | תיאור |
|-----|-------|--------|-------|
| `cache_maintenance` | `main.py` | כל 10 דקות | ניקוי cache entries שפגו |
| `cache_warming` | `main.py` | כל 15 דקות | חימום קאש עם נתונים נפוצים |

**משתני סביבה:**
```bash
CACHE_MAINT_INTERVAL_SECS=600         # אינטרוול תחזוקה
CACHE_MAINT_FIRST_SECS=30             # השהייה ראשונה
CACHE_WARMING_INTERVAL_SECS=900       # אינטרוול חימום
CACHE_WARMING_FIRST_SECS=45           # השהייה ראשונה
CACHE_WARMING_BUDGET_SECS=5           # תקציב זמן לחימום
```

### 3. Google Drive Sync

| Job | מיקום | תדירות | תיאור |
|-----|-------|--------|-------|
| `drive_reschedule_bootstrap` | `main.py` | חד-פעמי | תזמון ראשוני של גיבויי Drive |
| `drive_keepalive` | `main.py` | כל 15 דקות | שמירה על תזמוני Drive |
| `drive_sync_{user_id}` | `handlers/drive/menu.py` | לפי הגדרת משתמש | גיבוי אוטומטי ל-Drive |

**משתני סביבה:**
```bash
DRIVE_RESCHEDULE_INTERVAL=900         # אינטרוול keepalive
DRIVE_RESCHEDULE_FIRST_DELAY=60       # השהייה ראשונה
```

### 4. תזכורות (Reminders)

| Job | מיקום | תדירות | תיאור |
|-----|-------|--------|-------|
| `recurring_reminders_check` | `reminders/scheduler.py` | כל שעה | בדיקת תזכורות חוזרות |
| `reminder_{id}` | `reminders/scheduler.py` | לפי תזכורת | שליחת תזכורת בודדת |

### 5. Batch Processing

| Job | מיקום | תדירות | תיאור |
|-----|-------|--------|-------|
| `batch_{user_id}_{counter}_{ts}` | `batch_processor.py` | on-demand | עיבוד batch של קבצים |

**סוגי פעולות:**
- `analyze` – ניתוח קבצים
- `validate` – בדיקת תקינות
- `export` – ייצוא קבצים

### 6. Monitoring & Reporting

| Job | מיקום | תדירות | תיאור |
|-----|-------|--------|-------|
| `sentry_poll` | `main.py` | כל 5 דקות | סקירת אירועי Sentry |
| `predictive_sampler` | `main.py` | כל דקה | דגימה חזויה לאנומליות |
| `weekly_admin_report` | `main.py` | כל שבוע | דו"ח שבועי לאדמין |

---

## ארכיטקטורה מוצעת

```
┌─────────────────────────────────────────────────────────────────┐
│                    Background Jobs Monitor                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │ JobRegistry  │───▶│ JobTracker   │───▶│  MongoDB     │       │
│  │  (Singleton) │    │  (Per-run)   │    │  (History)   │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│         │                   │                   │                │
│         ▼                   ▼                   ▼                │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐       │
│  │  WebServer   │    │   ChatOps    │    │   Telegram   │       │
│  │  (REST API)  │    │  (/jobs)     │    │   (Alerts)   │       │
│  └──────────────┘    └──────────────┘    └──────────────┘       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### רכיבים עיקריים

1. **JobRegistry** – רישום מרכזי של כל ה-jobs המוגדרים
2. **JobTracker** – מעקב אחרי הרצות (start/end/status/logs)
3. **MongoDB Collection** – שמירת היסטוריית הרצות
4. **REST API** – endpoints לצפייה וניהול
5. **WebUI** – מסך Monitor ב-Webapp
6. **ChatOps** – פקודות Telegram לניהול jobs

---

## מודל נתונים

### JobDefinition (רישום Job)

```python
# services/job_registry.py

from dataclasses import dataclass, field
from typing import Optional, Dict, Any, Callable
from datetime import datetime
from enum import Enum

class JobType(Enum):
    REPEATING = "repeating"
    ONCE = "once"
    ON_DEMAND = "on_demand"

class JobCategory(Enum):
    BACKUP = "backup"
    CACHE = "cache"
    SYNC = "sync"
    CLEANUP = "cleanup"
    MONITORING = "monitoring"
    BATCH = "batch"
    OTHER = "other"

@dataclass
class JobDefinition:
    """הגדרת Job במערכת"""
    job_id: str                              # מזהה ייחודי
    name: str                                # שם תצוגה
    description: str                         # תיאור
    category: JobCategory                    # קטגוריה
    job_type: JobType                        # סוג (חוזר/חד-פעמי/on-demand)
    interval_seconds: Optional[int] = None   # אינטרוול (ל-repeating)
    enabled: bool = True                     # האם מופעל
    env_toggle: Optional[str] = None         # משתנה סביבה להפעלה/כיבוי
    callback_name: str = ""                  # שם הפונקציה המופעלת
    source_file: str = ""                    # קובץ מקור
    metadata: Dict[str, Any] = field(default_factory=dict)
```

### JobRun (הרצה בודדת)

```python
# services/job_tracker.py

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum

class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"

@dataclass
class JobLogEntry:
    """רשומת לוג בודדת"""
    timestamp: datetime
    level: str              # info/warning/error
    message: str
    details: Optional[Dict[str, Any]] = None

@dataclass
class JobRun:
    """הרצה בודדת של Job"""
    run_id: str                              # מזהה הרצה ייחודי
    job_id: str                              # מזהה ה-Job
    started_at: datetime
    ended_at: Optional[datetime] = None
    status: JobStatus = JobStatus.PENDING
    progress: int = 0                        # 0-100
    total_items: int = 0                     # סה"כ פריטים לעיבוד
    processed_items: int = 0                 # פריטים שעובדו
    error_message: Optional[str] = None
    logs: List[JobLogEntry] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None  # תוצאה סופית
    trigger: str = "scheduled"               # scheduled/manual/api
    user_id: Optional[int] = None            # אם רלוונטי למשתמש
```

### MongoDB Schema

```python
# database/job_runs_collection.py

JOB_RUNS_COLLECTION = "job_runs"

# הרשימה המחייבת היא זו שבקוד: job_runs_indexes() באותו קובץ.
# DatabaseManager._create_indexes קורא לה בכל התחברות למסד.
# TTL על started_at, באינדקס חד-שדה נפרד, לפי JOB_RUNS_TTL_DAYS (ברירת מחדל 30).
```

---

## Backend Implementation

### 1. JobRegistry – רישום Jobs

```python
# services/job_registry.py

import threading
from typing import Dict, List, Optional
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class JobRegistry:
    """Singleton לרישום כל ה-Jobs במערכת"""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._jobs: Dict[str, JobDefinition] = {}
        return cls._instance
    
    def register(self, job: JobDefinition) -> None:
        """רישום Job חדש"""
        self._jobs[job.job_id] = job
        logger.info(f"Registered job: {job.job_id} ({job.name})")
    
    def get(self, job_id: str) -> Optional[JobDefinition]:
        """קבלת Job לפי ID"""
        return self._jobs.get(job_id)
    
    def list_all(self) -> List[JobDefinition]:
        """רשימת כל ה-Jobs"""
        return list(self._jobs.values())
    
    def list_by_category(self, category: JobCategory) -> List[JobDefinition]:
        """רשימת Jobs לפי קטגוריה"""
        return [j for j in self._jobs.values() if j.category == category]
    
    def is_enabled(self, job_id: str) -> bool:
        """בדיקה האם Job מופעל"""
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.env_toggle:
            import os
            return os.getenv(job.env_toggle, "").lower() in ("1", "true", "yes", "on")
        return job.enabled


# פונקציית עזר לרישום
def register_job(
    job_id: str,
    name: str,
    description: str,
    category: JobCategory,
    job_type: JobType,
    **kwargs
) -> JobDefinition:
    """רישום Job חדש במערכת"""
    job = JobDefinition(
        job_id=job_id,
        name=name,
        description=description,
        category=category,
        job_type=job_type,
        **kwargs
    )
    JobRegistry().register(job)
    return job
```

### 2. JobTracker – מעקב הרצות

```python
# services/job_tracker.py

import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class JobAlreadyRunningError(Exception):
    """נזרק כאשר מנסים להפעיל Job שכבר רץ"""
    pass


class JobTracker:
    """מעקב אחרי הרצות Jobs"""
    
    def __init__(self, db_manager=None):
        from database import db
        self.db = db_manager or db
        self._active_runs: Dict[str, JobRun] = {}
    
    def start_run(
        self,
        job_id: str,
        trigger: str = "scheduled",
        user_id: Optional[int] = None,
        total_items: int = 0,
        allow_concurrent: bool = False
    ) -> JobRun:
        """התחלת הרצה חדשה
        
        Args:
            job_id: מזהה ה-Job
            trigger: מה הפעיל את ההרצה (scheduled/manual/api)
            user_id: מזהה משתמש (אם רלוונטי)
            total_items: סה"כ פריטים לעיבוד
            allow_concurrent: האם לאפשר הרצות מקבילות של אותו Job
            
        Raises:
            JobAlreadyRunningError: אם Job כבר רץ ו-allow_concurrent=False
        """
        # 🔒 מניעת הרצות מקבילות (Singleton Jobs)
        if not allow_concurrent:
            existing = [r for r in self._active_runs.values() 
                       if r.job_id == job_id and r.status == JobStatus.RUNNING]
            if existing:
                raise JobAlreadyRunningError(
                    f"Job '{job_id}' is already running (run_id: {existing[0].run_id})"
                )
        
        run = JobRun(
            run_id=str(uuid.uuid4())[:12],
            job_id=job_id,
            started_at=datetime.now(timezone.utc),
            status=JobStatus.RUNNING,
            trigger=trigger,
            user_id=user_id,
            total_items=total_items
        )
        self._active_runs[run.run_id] = run
        self._persist_run(run)
        
        try:
            from observability import emit_event
            emit_event("job_started", severity="info", job_id=job_id, run_id=run.run_id)
        except Exception:
            pass

        return run

    def update_progress(
        self,
        run_id: str,
        processed: int,
        total: Optional[int] = None,
        message: Optional[str] = None
    ) -> None:
        """עדכון התקדמות"""
        run = self._active_runs.get(run_id)
        if not run:
            return
        
        run.processed_items = processed
        if total is not None:
            run.total_items = total
        
        if run.total_items > 0:
            run.progress = int((processed / run.total_items) * 100)
        
        if message:
            self.add_log(run_id, "info", message)
        
        self._persist_run(run)
    
    def add_log(
        self,
        run_id: str,
        level: str,
        message: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        """הוספת לוג להרצה"""
        run = self._active_runs.get(run_id)
        if not run:
            return
        
        entry = JobLogEntry(
            timestamp=datetime.now(timezone.utc),
            level=level,
            message=message,
            details=details
        )
        run.logs.append(entry)
        
        # שמירה ל-DB רק כל 10 לוגים או ב-error
        if level == "error" or len(run.logs) % 10 == 0:
            self._persist_run(run)
    
    def complete_run(
        self,
        run_id: str,
        result: Optional[Dict[str, Any]] = None
    ) -> None:
        """סיום הרצה בהצלחה"""
        run = self._active_runs.get(run_id)
        if not run:
            return
        
        run.status = JobStatus.COMPLETED
        run.ended_at = datetime.now(timezone.utc)
        run.progress = 100
        run.result = result
        
        self._persist_run(run)
        self._active_runs.pop(run_id, None)
        
        duration = (run.ended_at - run.started_at).total_seconds()
        try:
            from observability import emit_event
            emit_event(
                "job_completed",
                severity="info",
                job_id=run.job_id,
                run_id=run_id,
                duration_seconds=duration
            )
        except Exception:
            pass
    
    def fail_run(
        self,
        run_id: str,
        error_message: str
    ) -> None:
        """סיום הרצה בכישלון"""
        run = self._active_runs.get(run_id)
        if not run:
            return
        
        run.status = JobStatus.FAILED
        run.ended_at = datetime.now(timezone.utc)
        run.error_message = error_message
        self.add_log(run_id, "error", error_message)
        
        self._persist_run(run)
        self._active_runs.pop(run_id, None)
        
        try:
            from observability import emit_event
            emit_event(
                "job_failed",
                severity="error",
                job_id=run.job_id,
                run_id=run_id,
                error=error_message
            )
        except Exception:
            pass
    
    @contextmanager
    def track(
        self,
        job_id: str,
        trigger: str = "scheduled",
        user_id: Optional[int] = None
    ):
        """Context manager למעקב אחרי הרצה"""
        run = self.start_run(job_id, trigger, user_id)
        try:
            yield run
            self.complete_run(run.run_id)
        except Exception as e:
            self.fail_run(run.run_id, str(e))
            raise
    
    def _persist_run(self, run: JobRun) -> None:
        """שמירת הרצה ל-DB"""
        try:
            doc = {
                "run_id": run.run_id,
                "job_id": run.job_id,
                "started_at": run.started_at,
                "ended_at": run.ended_at,
                "status": run.status.value,
                "progress": run.progress,
                "total_items": run.total_items,
                "processed_items": run.processed_items,
                "error_message": run.error_message,
                "logs": [
                    {
                        "timestamp": log.timestamp,
                        "level": log.level,
                        "message": log.message,
                        "details": log.details
                    }
                    for log in run.logs[-50:]  # שמירת 50 לוגים אחרונים
                ],
                "result": run.result,
                "trigger": run.trigger,
                "user_id": run.user_id
            }
            self.db.client[self.db.db_name]["job_runs"].update_one(
                {"run_id": run.run_id},
                {"$set": doc},
                upsert=True
            )
        except Exception as e:
            logger.error(f"Failed to persist job run: {e}")
    
    def get_run(self, run_id: str) -> Optional[JobRun]:
        """קבלת הרצה לפי ID"""
        if run_id in self._active_runs:
            return self._active_runs[run_id]
        
        try:
            doc = self.db.client[self.db.db_name]["job_runs"].find_one(
                {"run_id": run_id}
            )
            if doc:
                return self._doc_to_run(doc)
        except Exception:
            pass
        return None
    
    def get_job_history(
        self,
        job_id: str,
        limit: int = 20
    ) -> List[JobRun]:
        """היסטוריית הרצות של Job"""
        try:
            cursor = self.db.client[self.db.db_name]["job_runs"].find(
                {"job_id": job_id}
            ).sort("started_at", -1).limit(limit)
            return [self._doc_to_run(doc) for doc in cursor]
        except Exception:
            return []
    
    def get_active_runs(self) -> List[JobRun]:
        """רשימת הרצות פעילות"""
        return list(self._active_runs.values())
    
    def _doc_to_run(self, doc: dict) -> JobRun:
        """המרת מסמך DB ל-JobRun"""
        logs = [
            JobLogEntry(
                timestamp=log["timestamp"],
                level=log["level"],
                message=log["message"],
                details=log.get("details")
            )
            for log in doc.get("logs", [])
        ]
        return JobRun(
            run_id=doc["run_id"],
            job_id=doc["job_id"],
            started_at=doc["started_at"],
            ended_at=doc.get("ended_at"),
            status=JobStatus(doc.get("status", "completed")),
            progress=doc.get("progress", 100),
            total_items=doc.get("total_items", 0),
            processed_items=doc.get("processed_items", 0),
            error_message=doc.get("error_message"),
            logs=logs,
            result=doc.get("result"),
            trigger=doc.get("trigger", "scheduled"),
            user_id=doc.get("user_id")
        )


# Singleton instance
_tracker: Optional[JobTracker] = None

def get_job_tracker() -> JobTracker:
    global _tracker
    if _tracker is None:
        _tracker = JobTracker()
    return _tracker
```

### 3. רישום ה-Jobs הקיימים

```python
# services/register_jobs.py

"""
רישום כל ה-Background Jobs במערכת.
יש לייבא קובץ זה ב-main.py לאחר אתחול ה-Application.
"""

from services.job_registry import (
    register_job,
    JobCategory,
    JobType,
    JobRegistry
)

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
        source_file="main.py"
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
        source_file="main.py"
    )
    
    register_job(
        job_id="cache_warming",
        name="חימום קאש",
        description="טעינה מראש של נתונים נפוצים לקאש",
        category=JobCategory.CACHE,
        job_type=JobType.REPEATING,
        interval_seconds=900,
        env_toggle="CACHE_WARMING_ENABLED",
        callback_name="_cache_warming_job",
        source_file="main.py"
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
        source_file="main.py"
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
        callback_name="_sentry_poll_job",
        source_file="main.py"
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
        source_file="main.py"
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
        source_file="main.py"
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
        source_file="reminders/scheduler.py"
    )
    
    # === Batch Processing ===
    register_job(
        job_id="batch_analyze",
        name="ניתוח קבצים",
        description="ניתוח batch של קבצים",
        category=JobCategory.BATCH,
        job_type=JobType.ON_DEMAND,
        callback_name="analyze_files_batch",
        source_file="batch_processor.py"
    )
    
    register_job(
        job_id="batch_validate",
        name="בדיקת תקינות",
        description="בדיקת תקינות batch של קבצים",
        category=JobCategory.BATCH,
        job_type=JobType.ON_DEMAND,
        callback_name="validate_files_batch",
        source_file="batch_processor.py"
    )
    
    register_job(
        job_id="batch_export",
        name="ייצוא קבצים",
        description="ייצוא batch של קבצים",
        category=JobCategory.BATCH,
        job_type=JobType.ON_DEMAND,
        callback_name="export_files_batch",
        source_file="batch_processor.py"
    )
```

---

## API Endpoints

### הוספה ל-webserver

```python
# services/webserver.py (additions)

from aiohttp import web
from services.job_registry import JobRegistry
from services.job_tracker import get_job_tracker

async def get_jobs_list(request: web.Request) -> web.Response:
    """GET /api/jobs - רשימת כל ה-jobs"""
    registry = JobRegistry()
    jobs = []
    
    for job in registry.list_all():
        jobs.append({
            "job_id": job.job_id,
            "name": job.name,
            "description": job.description,
            "category": job.category.value,
            "type": job.job_type.value,
            "interval_seconds": job.interval_seconds,
            "enabled": registry.is_enabled(job.job_id),
            "env_toggle": job.env_toggle,
        })
    
    return web.json_response({"jobs": jobs})


async def get_job_detail(request: web.Request) -> web.Response:
    """GET /api/jobs/{job_id} - פרטי job ספציפי"""
    job_id = request.match_info.get("job_id")
    registry = JobRegistry()
    tracker = get_job_tracker()
    
    job = registry.get(job_id)
    if not job:
        return web.json_response({"error": "Job not found"}, status=404)
    
    history = tracker.get_job_history(job_id, limit=20)
    active = [r for r in tracker.get_active_runs() if r.job_id == job_id]
    
    return web.json_response({
        "job": {
            "job_id": job.job_id,
            "name": job.name,
            "description": job.description,
            "category": job.category.value,
            "type": job.job_type.value,
            "interval_seconds": job.interval_seconds,
            "enabled": registry.is_enabled(job.job_id),
            "source_file": job.source_file,
        },
        "active_runs": [_run_to_dict(r) for r in active],
        "history": [_run_to_dict(r) for r in history],
    })


async def get_run_detail(request: web.Request) -> web.Response:
    """GET /api/jobs/runs/{run_id} - פרטי הרצה"""
    run_id = request.match_info.get("run_id")
    tracker = get_job_tracker()
    
    run = tracker.get_run(run_id)
    if not run:
        return web.json_response({"error": "Run not found"}, status=404)
    
    return web.json_response({"run": _run_to_dict(run, include_logs=True)})


async def get_active_runs(request: web.Request) -> web.Response:
    """GET /api/jobs/active - הרצות פעילות"""
    tracker = get_job_tracker()
    runs = tracker.get_active_runs()
    
    return web.json_response({
        "active_runs": [_run_to_dict(r) for r in runs]
    })


async def trigger_job(request: web.Request) -> web.Response:
    """POST /api/jobs/{job_id}/trigger - הפעלה ידנית"""
    job_id = request.match_info.get("job_id")
    registry = JobRegistry()
    
    job = registry.get(job_id)
    if not job:
        return web.json_response({"error": "Job not found"}, status=404)
    
    # TODO: implement actual trigger via job_queue
    return web.json_response({
        "message": f"Job {job_id} triggered",
        "job_id": job_id
    })


def _run_to_dict(run, include_logs: bool = False) -> dict:
    """המרת JobRun ל-dict"""
    d = {
        "run_id": run.run_id,
        "job_id": run.job_id,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "status": run.status.value,
        "progress": run.progress,
        "total_items": run.total_items,
        "processed_items": run.processed_items,
        "error_message": run.error_message,
        "trigger": run.trigger,
        "user_id": run.user_id,
        "duration_seconds": (
            (run.ended_at - run.started_at).total_seconds()
            if run.ended_at and run.started_at else None
        ),
    }
    if include_logs:
        d["logs"] = [
            {
                "timestamp": log.timestamp.isoformat(),
                "level": log.level,
                "message": log.message,
            }
            for log in run.logs
        ]
    return d


def register_jobs_routes(app: web.Application):
    """רישום routes של Jobs"""
    app.router.add_get("/api/jobs", get_jobs_list)
    app.router.add_get("/api/jobs/active", get_active_runs)
    app.router.add_get("/api/jobs/{job_id}", get_job_detail)
    app.router.add_get("/api/jobs/runs/{run_id}", get_run_detail)
    app.router.add_post("/api/jobs/{job_id}/trigger", trigger_job)
```

---

## Frontend – מסך Monitor

### HTML Template

```html
<!-- webapp/templates/jobs_monitor.html -->
{% extends "base.html" %}
{% block title %}Background Jobs Monitor{% endblock %}

{% block content %}
<div class="jobs-monitor">
    <header class="page-header">
        <h1>🔄 Background Jobs Monitor</h1>
        <div class="header-actions">
            <button id="refresh-btn" class="btn btn-secondary">
                <span class="icon">🔄</span> רענן
            </button>
        </div>
    </header>

    <!-- Active Runs Section -->
    <section class="active-runs-section">
        <h2>⚡ הרצות פעילות</h2>
        <div id="active-runs" class="runs-grid">
            <div class="loading-skeleton">טוען...</div>
        </div>
    </section>

    <!-- Jobs by Category -->
    <section class="jobs-section">
        <h2>📋 כל ה-Jobs</h2>
        
        <div class="category-tabs">
            <button class="tab active" data-category="all">הכל</button>
            <button class="tab" data-category="backup">גיבויים</button>
            <button class="tab" data-category="cache">קאש</button>
            <button class="tab" data-category="sync">סנכרון</button>
            <button class="tab" data-category="cleanup">ניקוי</button>
            <button class="tab" data-category="monitoring">ניטור</button>
            <button class="tab" data-category="batch">Batch</button>
        </div>

        <div id="jobs-list" class="jobs-grid">
            <div class="loading-skeleton">טוען...</div>
        </div>
    </section>

    <!-- Job Detail Modal -->
    <div id="job-modal" class="modal hidden">
        <div class="modal-content">
            <header class="modal-header">
                <h3 id="modal-job-name">שם Job</h3>
                <button class="close-btn">&times;</button>
            </header>
            <div id="modal-body" class="modal-body">
                <!-- Content loaded dynamically -->
            </div>
        </div>
    </div>
</div>

<style>
.jobs-monitor {
    padding: 20px;
    max-width: 1200px;
    margin: 0 auto;
}

.page-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
}

.runs-grid, .jobs-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
}

.job-card {
    background: var(--card-bg, #fff);
    border-radius: 8px;
    padding: 16px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    cursor: pointer;
    transition: transform 0.2s, box-shadow 0.2s;
}

.job-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.15);
}

.job-card .job-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 8px;
}

.job-card .job-actions {
    display: flex;
    align-items: center;
    gap: 8px;
}

.btn-trigger {
    background: transparent;
    border: 1px solid var(--border-color, #ddd);
    border-radius: 50%;
    width: 28px;
    height: 28px;
    cursor: pointer;
    transition: all 0.2s;
    font-size: 12px;
}

.btn-trigger:hover:not(:disabled) {
    background: var(--primary-color, #007bff);
    border-color: var(--primary-color, #007bff);
}

.btn-trigger:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}

.toast {
    position: fixed;
    bottom: 20px;
    left: 50%;
    transform: translateX(-50%);
    padding: 12px 24px;
    border-radius: 8px;
    color: #fff;
    z-index: 2000;
    animation: slideUp 0.3s ease;
}

.toast-success { background: #28a745; }
.toast-error { background: #dc3545; }
.toast-info { background: #17a2b8; }

@keyframes slideUp {
    from { transform: translateX(-50%) translateY(20px); opacity: 0; }
    to { transform: translateX(-50%) translateY(0); opacity: 1; }
}

.job-card .job-name {
    font-weight: 600;
    font-size: 1.1em;
}

.job-card .job-status {
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 0.85em;
}

.job-card .job-status.enabled { background: #d4edda; color: #155724; }
.job-card .job-status.disabled { background: #f8d7da; color: #721c24; }
.job-card .job-status.running { background: #cce5ff; color: #004085; }

.job-card .job-description {
    color: var(--text-muted, #666);
    font-size: 0.9em;
    margin-bottom: 12px;
}

.job-card .job-meta {
    display: flex;
    gap: 12px;
    font-size: 0.85em;
    color: var(--text-muted, #888);
}

.run-card {
    background: var(--card-bg, #fff);
    border-radius: 8px;
    padding: 16px;
    border-left: 4px solid;
}

.run-card.running { border-color: #007bff; }
.run-card.completed { border-color: #28a745; }
.run-card.failed { border-color: #dc3545; }

.progress-bar {
    height: 8px;
    background: #e9ecef;
    border-radius: 4px;
    overflow: hidden;
    margin-top: 8px;
}

.progress-bar .fill {
    height: 100%;
    background: #007bff;
    transition: width 0.3s ease;
}

.category-tabs {
    display: flex;
    gap: 8px;
    margin-bottom: 16px;
    flex-wrap: wrap;
}

.category-tabs .tab {
    padding: 8px 16px;
    border: 1px solid var(--border-color, #ddd);
    border-radius: 20px;
    background: transparent;
    cursor: pointer;
    transition: all 0.2s;
}

.category-tabs .tab.active {
    background: var(--primary-color, #007bff);
    color: #fff;
    border-color: var(--primary-color, #007bff);
}

.modal {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0,0,0,0.5);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
}

.modal.hidden { display: none; }

.modal-content {
    background: var(--card-bg, #fff);
    border-radius: 12px;
    width: 90%;
    max-width: 700px;
    max-height: 80vh;
    overflow: hidden;
    display: flex;
    flex-direction: column;
}

.modal-header {
    padding: 16px 20px;
    border-bottom: 1px solid var(--border-color, #eee);
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.modal-body {
    padding: 20px;
    overflow-y: auto;
}

.logs-list {
    font-family: monospace;
    font-size: 0.85em;
    max-height: 300px;
    overflow-y: auto;
    background: var(--code-bg, #f5f5f5);
    padding: 12px;
    border-radius: 8px;
}

.log-entry {
    padding: 4px 0;
    border-bottom: 1px solid var(--border-color, #eee);
}

.log-entry.error { color: #dc3545; }
.log-entry.warning { color: #ffc107; }
.log-entry .timestamp { color: var(--text-muted, #888); }

@media (max-width: 768px) {
    .runs-grid, .jobs-grid {
        grid-template-columns: 1fr;
    }
}
</style>

<script>
document.addEventListener('DOMContentLoaded', function() {
    const API_BASE = '/api/jobs';
    let currentCategory = 'all';
    let refreshInterval;
    
    // Load initial data
    loadJobs();
    loadActiveRuns();
    
    // Auto-refresh every 10 seconds
    refreshInterval = setInterval(() => {
        loadActiveRuns();
    }, 10000);
    
    // Event handlers
    document.getElementById('refresh-btn').addEventListener('click', () => {
        loadJobs();
        loadActiveRuns();
    });
    
    document.querySelectorAll('.category-tabs .tab').forEach(tab => {
        tab.addEventListener('click', () => {
            document.querySelectorAll('.category-tabs .tab').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentCategory = tab.dataset.category;
            filterJobs();
        });
    });
    
    document.querySelector('.modal .close-btn').addEventListener('click', closeModal);
    document.getElementById('job-modal').addEventListener('click', (e) => {
        if (e.target.id === 'job-modal') closeModal();
    });
    
    async function loadJobs() {
        try {
            const res = await fetch(API_BASE);
            const data = await res.json();
            window.allJobs = data.jobs;
            filterJobs();
        } catch (err) {
            console.error('Failed to load jobs:', err);
        }
    }
    
    async function loadActiveRuns() {
        try {
            const res = await fetch(`${API_BASE}/active`);
            const data = await res.json();
            renderActiveRuns(data.active_runs);
        } catch (err) {
            console.error('Failed to load active runs:', err);
        }
    }
    
    function filterJobs() {
        const jobs = window.allJobs || [];
        const filtered = currentCategory === 'all' 
            ? jobs 
            : jobs.filter(j => j.category === currentCategory);
        renderJobs(filtered);
    }
    
    function renderJobs(jobs) {
        const container = document.getElementById('jobs-list');
        if (!jobs.length) {
            container.innerHTML = '<div class="empty-state">אין jobs בקטגוריה זו</div>';
            return;
        }
        
        container.innerHTML = jobs.map(job => `
            <div class="job-card" data-job-id="${job.job_id}">
                <div class="job-header">
                    <span class="job-name">${getCategoryIcon(job.category)} ${job.name}</span>
                    <div class="job-actions">
                        <button class="btn-trigger" data-job-id="${job.job_id}" 
                                title="הרץ עכשיו" ${!job.enabled ? 'disabled' : ''}>
                            ▶️
                        </button>
                        <span class="job-status ${job.enabled ? 'enabled' : 'disabled'}">
                            ${job.enabled ? '✓ פעיל' : '✗ מושבת'}
                        </span>
                    </div>
                </div>
                <div class="job-description">${job.description}</div>
                <div class="job-meta">
                    <span>🏷️ ${job.category}</span>
                    ${job.interval_seconds ? `<span>⏱️ כל ${formatInterval(job.interval_seconds)}</span>` : ''}
                    <span>📦 ${job.type}</span>
                </div>
            </div>
        `).join('');
        
        // Add click handlers for cards
        container.querySelectorAll('.job-card').forEach(card => {
            card.addEventListener('click', (e) => {
                // Don't open modal if clicking trigger button
                if (e.target.classList.contains('btn-trigger')) return;
                openJobDetail(card.dataset.jobId);
            });
        });
        
        // Add click handlers for trigger buttons
        container.querySelectorAll('.btn-trigger').forEach(btn => {
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                triggerJob(btn.dataset.jobId);
            });
        });
    }
    
    async function triggerJob(jobId) {
        if (!confirm(`להריץ את ${jobId} עכשיו?`)) return;
        
        try {
            const res = await fetch(`${API_BASE}/${jobId}/trigger`, { method: 'POST' });
            const data = await res.json();
            
            if (res.ok) {
                showToast(`✅ Job ${jobId} הופעל בהצלחה`, 'success');
                // Refresh active runs after a short delay
                setTimeout(loadActiveRuns, 1000);
            } else {
                showToast(`❌ ${data.error || 'שגיאה בהפעלת Job'}`, 'error');
            }
        } catch (err) {
            showToast('❌ שגיאת רשת', 'error');
        }
    }
    
    function showToast(message, type = 'info') {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }
    
    function renderActiveRuns(runs) {
        const container = document.getElementById('active-runs');
        if (!runs.length) {
            container.innerHTML = '<div class="empty-state">אין הרצות פעילות כרגע</div>';
            return;
        }
        
        container.innerHTML = runs.map(run => `
            <div class="run-card ${run.status}">
                <div class="run-header">
                    <strong>${run.job_id}</strong>
                    <span class="run-status">${getStatusIcon(run.status)} ${run.status}</span>
                </div>
                <div class="run-progress">
                    ${run.processed_items}/${run.total_items} פריטים (${run.progress}%)
                    <div class="progress-bar">
                        <div class="fill" style="width: ${run.progress}%"></div>
                    </div>
                </div>
                <div class="run-meta">
                    התחיל: ${formatTime(run.started_at)}
                </div>
            </div>
        `).join('');
    }
    
    async function openJobDetail(jobId) {
        try {
            const res = await fetch(`${API_BASE}/${jobId}`);
            const data = await res.json();
            renderJobModal(data);
            document.getElementById('job-modal').classList.remove('hidden');
        } catch (err) {
            console.error('Failed to load job detail:', err);
        }
    }
    
    function renderJobModal(data) {
        const { job, active_runs, history } = data;
        document.getElementById('modal-job-name').textContent = `${getCategoryIcon(job.category)} ${job.name}`;
        
        document.getElementById('modal-body').innerHTML = `
            <div class="job-detail">
                <p><strong>תיאור:</strong> ${job.description}</p>
                <p><strong>קטגוריה:</strong> ${job.category}</p>
                <p><strong>סוג:</strong> ${job.type}</p>
                ${job.interval_seconds ? `<p><strong>אינטרוול:</strong> כל ${formatInterval(job.interval_seconds)}</p>` : ''}
                <p><strong>קובץ מקור:</strong> <code>${job.source_file}</code></p>
                <p><strong>סטטוס:</strong> ${job.enabled ? '✓ פעיל' : '✗ מושבת'}</p>
            </div>
            
            ${active_runs.length ? `
                <h4>⚡ הרצות פעילות</h4>
                <div class="active-list">
                    ${active_runs.map(r => renderRunItem(r)).join('')}
                </div>
            ` : ''}
            
            <h4>📜 היסטוריה אחרונה</h4>
            <div class="history-list">
                ${history.length ? history.map(r => renderRunItem(r)).join('') : '<p>אין היסטוריה</p>'}
            </div>
        `;
    }
    
    function renderRunItem(run) {
        return `
            <div class="run-item ${run.status}">
                <div class="run-summary">
                    <span>${getStatusIcon(run.status)} ${run.status}</span>
                    <span>${formatTime(run.started_at)}</span>
                    ${run.duration_seconds ? `<span>⏱️ ${run.duration_seconds.toFixed(1)}s</span>` : ''}
                </div>
                ${run.error_message ? `<div class="error-msg">❌ ${run.error_message}</div>` : ''}
            </div>
        `;
    }
    
    function closeModal() {
        document.getElementById('job-modal').classList.add('hidden');
    }
    
    function getCategoryIcon(category) {
        const icons = {
            backup: '💾', cache: '🗄️', sync: '☁️', cleanup: '🧹',
            monitoring: '📊', batch: '📦', other: '📋'
        };
        return icons[category] || '📋';
    }
    
    function getStatusIcon(status) {
        const icons = {
            running: '🔄', completed: '✅', failed: '❌',
            pending: '⏳', cancelled: '🚫', skipped: '⏭️'
        };
        return icons[status] || '❓';
    }
    
    function formatInterval(seconds) {
        if (seconds >= 86400) return `${Math.round(seconds / 86400)} ימים`;
        if (seconds >= 3600) return `${Math.round(seconds / 3600)} שעות`;
        if (seconds >= 60) return `${Math.round(seconds / 60)} דקות`;
        return `${seconds} שניות`;
    }
    
    function formatTime(isoString) {
        if (!isoString) return '-';
        const d = new Date(isoString);
        return d.toLocaleString('he-IL', { hour: '2-digit', minute: '2-digit', day: '2-digit', month: '2-digit' });
    }
});
</script>
{% endblock %}
```

---

## ChatOps Commands

### הוספת פקודות לבוט

```python
# chatops/jobs_commands.py

"""
פקודות ChatOps לניהול Background Jobs.
"""

from typing import Optional
from services.job_registry import JobRegistry, JobCategory
from services.job_tracker import get_job_tracker


def handle_jobs_command(args: str) -> str:
    """
    /jobs [category|status|<job_id>]
    
    דוגמאות:
    - /jobs               - רשימת כל ה-jobs
    - /jobs backup        - jobs בקטגוריית גיבויים
    - /jobs active        - הרצות פעילות
    - /jobs cache_warming - פרטי job ספציפי
    """
    args = args.strip().lower()
    registry = JobRegistry()
    tracker = get_job_tracker()
    
    # URL בסיס למוניטור (ניתן לקנפג דרך ENV)
    import os
    monitor_base_url = os.getenv("WEBAPP_URL", "https://your-app.onrender.com")
    
    # Active runs
    if args == "active":
        runs = tracker.get_active_runs()
        if not runs:
            return "✅ אין הרצות פעילות כרגע"
        
        lines = ["⚡ **הרצות פעילות:**\n"]
        for run in runs:
            status_icon = {"running": "🔄", "pending": "⏳"}.get(run.status.value, "❓")
            # 🔗 קישור ישיר ללוגים של ההרצה
            logs_link = f"{monitor_base_url}/jobs/monitor?run_id={run.run_id}"
            lines.append(
                f"{status_icon} `{run.job_id}` - {run.progress}% "
                f"({run.processed_items}/{run.total_items})\n"
                f"   [📋 לוגים]({logs_link})"
            )
        return "\n".join(lines)
    
    # By category
    try:
        category = JobCategory(args)
        jobs = registry.list_by_category(category)
        if not jobs:
            return f"אין jobs בקטגוריה `{args}`"
        
        lines = [f"📋 **Jobs בקטגוריית {args}:**\n"]
        for job in jobs:
            status = "✅" if registry.is_enabled(job.job_id) else "❌"
            lines.append(f"{status} `{job.job_id}` - {job.name}")
        return "\n".join(lines)
    except ValueError:
        pass
    
    # Specific job
    if args:
        job = registry.get(args)
        if not job:
            return f"❌ Job `{args}` לא נמצא"
        
        history = tracker.get_job_history(args, limit=5)
        status = "✅ פעיל" if registry.is_enabled(args) else "❌ מושבת"
        
        lines = [
            f"📋 **{job.name}**\n",
            f"• מזהה: `{job.job_id}`",
            f"• סטטוס: {status}",
            f"• קטגוריה: {job.category.value}",
            f"• סוג: {job.job_type.value}",
        ]
        
        if job.interval_seconds:
            lines.append(f"• אינטרוול: {_format_interval(job.interval_seconds)}")
        
        if history:
            lines.append("\n**5 הרצות אחרונות:**")
            for run in history[:5]:
                icon = {
                    "completed": "✅", "failed": "❌",
                    "running": "🔄", "skipped": "⏭️"
                }.get(run.status.value, "❓")
                dur = ""
                if run.ended_at and run.started_at:
                    dur = f" ({(run.ended_at - run.started_at).total_seconds():.1f}s)"
                
                line = f"  {icon} {run.started_at.strftime('%d/%m %H:%M')}{dur}"
                
                # 🔗 אם נכשל, הוסף קישור ללוגים
                if run.status.value == "failed":
                    logs_link = f"{monitor_base_url}/jobs/monitor?run_id={run.run_id}"
                    line += f"\n     └─ [📋 ראה לוגים]({logs_link})"
                
                lines.append(line)
        
        return "\n".join(lines)
    
    # All jobs summary
    jobs = registry.list_all()
    categories = {}
    for job in jobs:
        cat = job.category.value
        if cat not in categories:
            categories[cat] = []
        status = "✅" if registry.is_enabled(job.job_id) else "❌"
        categories[cat].append(f"{status} {job.name}")
    
    lines = ["🔄 **Background Jobs:**\n"]
    for cat, items in categories.items():
        icon = {
            "backup": "💾", "cache": "🗄️", "sync": "☁️", "cleanup": "🧹",
            "monitoring": "📊", "batch": "📦", "other": "📋"
        }.get(cat, "📋")
        lines.append(f"**{icon} {cat}:**")
        for item in items:
            lines.append(f"  {item}")
        lines.append("")
    
    lines.append("_השתמש ב-`/jobs active` לצפייה בהרצות פעילות_")
    return "\n".join(lines)


def _format_interval(seconds: int) -> str:
    if seconds >= 86400:
        return f"{seconds // 86400} ימים"
    if seconds >= 3600:
        return f"{seconds // 3600} שעות"
    if seconds >= 60:
        return f"{seconds // 60} דקות"
    return f"{seconds} שניות"
```

---

## אינטגרציה עם המערכת הקיימת

### שינויים נדרשים ב-main.py

```python
# main.py (additions)

# 1. ייבוא המודולים החדשים
from services.register_jobs import register_all_jobs
from services.job_tracker import get_job_tracker

# 2. רישום ה-jobs בתוך post_init או אחרי יצירת Application
async def post_init(application: Application):
    # ... existing code ...
    
    # רישום כל ה-Jobs
    register_all_jobs()

# 3. עטיפת ה-jobs הקיימים עם tracking
# דוגמה ל-backups_cleanup_job:

async def _backups_cleanup_job(context: ContextTypes.DEFAULT_TYPE):
    tracker = get_job_tracker()
    
    # ⚠️ חשוב: להשתמש ב-run.run_id שחוזר מה-context manager
    # ולא ב-get_active_runs()[0] שעלול להחזיר הרצה אחרת (Race Condition!)
    with tracker.track("backups_cleanup", trigger="scheduled") as run:
        try:
            # הלוגיקה הקיימת
            if str(os.getenv("DISABLE_BACKGROUND_CLEANUP", "")).lower() in {"1", "true", "yes"}:
                tracker.add_log(run.run_id, "info", "Skipped: disabled by env")
                return
            
            from file_manager import backup_manager
            summary = backup_manager.cleanup_expired_backups()
            
            # ✅ שימוש נכון ב-run.run_id שחוזר מה-with
            tracker.add_log(
                run.run_id,
                "info",
                f"Cleaned {summary.get('fs_deleted', 0)} files, "
                f"scanned {summary.get('fs_scanned', 0)}"
            )
            
        except Exception as e:
            raise  # ה-context manager יתפוס ויסמן כ-failed
```

> **⚠️ אזהרה חשובה:** לעולם אל תשתמש ב-`tracker.get_active_runs()[0]` בתוך Job!
> בסביבה אסינכרונית, כמה Jobs יכולים לרוץ במקביל, ו-`[0]` יחזיר הרצה אקראית.
> **תמיד** השתמש ב-`run.run_id` שחוזר מה-context manager.

### שינויים נדרשים ב-webserver

```python
# services/webserver.py (additions)

def create_app():
    # ... existing code ...
    
    # רישום routes של Jobs Monitor
    from services.webserver import register_jobs_routes
    register_jobs_routes(app)
    
    return app
```

---

## Observability & Alerts

### אירועים שנפלטים

| Event | Severity | תיאור |
|-------|----------|-------|
| `job_started` | info | התחלת הרצה |
| `job_completed` | info | סיום הרצה בהצלחה |
| `job_failed` | error | כישלון הרצה |
| `job_skipped` | warn | הרצה דולגה (disabled) |
| `job_stuck` | error | הרצה תקועה (timeout) |

### התראות מומלצות

```yaml
# config/alerts.yml (additions)

alerts:
  - name: job_failure_alert
    event_pattern: "job_failed"
    severity: error
    cooldown_seconds: 300
    message: "❌ Job {job_id} נכשל: {error}"
    
  - name: job_stuck_alert
    event_pattern: "job_stuck"
    severity: critical
    cooldown_seconds: 600
    message: "⚠️ Job {job_id} תקוע כבר {minutes} דקות"
```

---

## בדיקות

### Unit Tests

```python
# tests/test_job_tracker.py

import pytest
from datetime import datetime, timezone
from services.job_tracker import JobTracker, JobStatus
from services.job_registry import JobRegistry, register_job, JobCategory, JobType


@pytest.fixture
def tracker(monkeypatch):
    """Tracker עם mock DB"""
    class MockDB:
        def __init__(self):
            self.client = {"test": {"job_runs": MockCollection()}}
            self.db_name = "test"
    
    class MockCollection:
        def __init__(self):
            self.docs = {}
        def update_one(self, query, update, upsert=False):
            self.docs[query["run_id"]] = update["$set"]
        def find_one(self, query):
            return self.docs.get(query["run_id"])
        def find(self, query):
            return MockCursor([d for d in self.docs.values() if d.get("job_id") == query.get("job_id")])
    
    class MockCursor:
        def __init__(self, docs):
            self._docs = docs
        def sort(self, *args):
            return self
        def limit(self, n):
            self._docs = self._docs[:n]
            return self
        def __iter__(self):
            return iter(self._docs)
    
    return JobTracker(MockDB())


def test_start_and_complete_run(tracker):
    run = tracker.start_run("test_job")
    assert run.status == JobStatus.RUNNING
    assert run.run_id in [r.run_id for r in tracker.get_active_runs()]
    
    tracker.complete_run(run.run_id, result={"count": 5})
    
    assert run.run_id not in [r.run_id for r in tracker.get_active_runs()]


def test_fail_run(tracker):
    run = tracker.start_run("test_job")
    tracker.fail_run(run.run_id, "Test error")
    
    assert run.status == JobStatus.FAILED
    assert run.error_message == "Test error"


def test_track_context_manager(tracker):
    with tracker.track("test_job") as run:
        tracker.add_log(run.run_id, "info", "Processing...")
    
    assert run.status == JobStatus.COMPLETED


def test_track_context_manager_on_error(tracker):
    with pytest.raises(ValueError):
        with tracker.track("test_job") as run:
            raise ValueError("Oops")
    
    assert run.status == JobStatus.FAILED


def test_registry_singleton():
    reg1 = JobRegistry()
    reg2 = JobRegistry()
    assert reg1 is reg2


def test_register_and_list_jobs():
    JobRegistry()._jobs.clear()  # reset for test
    
    register_job(
        job_id="test_backup",
        name="Test Backup",
        description="A test job",
        category=JobCategory.BACKUP,
        job_type=JobType.REPEATING,
        interval_seconds=3600
    )
    
    jobs = JobRegistry().list_all()
    assert len(jobs) == 1
    assert jobs[0].job_id == "test_backup"
```

---

## שיקולי ביצועים

### 1. הגבלת היסטוריה

- TTL Index על `job_runs.started_at` – מחיקה אוטומטית בתום `JOB_RUNS_TTL_DAYS` (ברירת מחדל 30 יום)
- שמירת מקסימום 50 לוגים להרצה
- Pagination ב-API

### 2. Rate Limiting

- ריענון אוטומטי ב-UI כל 10 שניות (לא כל שנייה)
- דחיסת עדכוני progress – שמירה רק כל 10 לוגים

### 3. Memory

- `_active_runs` מוגבל להרצות פעילות בלבד
- לא שומרים את כל ה-logs בזיכרון

### 4. טעינה עצלה

- רישום Jobs מתבצע בעת startup
- טעינת היסטוריה רק לפי דרישה (API call)

---

## מנגנוני הגנה חשובים

### 🔒 מניעת Race Conditions

**הבעיה:** בסביבה אסינכרונית, כמה Jobs יכולים לרוץ במקביל. גישה ל-`get_active_runs()[0]` עלולה להחזיר הרצה שגויה.

**הפתרון:** תמיד להשתמש באובייקט `run` שחוזר מה-context manager:

```python
# ❌ לא נכון - Race Condition!
with tracker.track("my_job") as run:
    tracker.add_log(tracker.get_active_runs()[0].run_id, ...)

# ✅ נכון - שימוש ב-run.run_id
with tracker.track("my_job") as run:
    tracker.add_log(run.run_id, "info", "Processing...")
```

### 🚫 מניעת הרצות מקבילות (Singleton Jobs)

Jobs כמו גיבויים לא צריכים לרוץ במקביל. הפרמטר `allow_concurrent=False` (ברירת מחדל) מונע זאת:

```python
# אם Job כבר רץ, ייזרק JobAlreadyRunningError
try:
    with tracker.track("backup_job") as run:
        # ... לוגיקה ...
except JobAlreadyRunningError as e:
    logger.warning(f"Skipping: {e}")
```

### 🔗 Deep Links ללוגים

ב-ChatOps, כאשר Job נכשל, מוצג קישור ישיר לדף הלוגים:

```
❌ backups_cleanup נכשל
   └─ [📋 ראה לוגים](https://your-app.onrender.com/jobs/monitor?run_id=abc123)
```

---

## סיכום

מדריך זה מתאר ארכיטקטורה מלאה למימוש Background Jobs Monitor שמשתלב עם המערכת הקיימת:

1. **JobRegistry** – רישום מרכזי של כל ה-jobs
2. **JobTracker** – מעקב אחרי הרצות עם שמירה ל-MongoDB
3. **REST API** – endpoints לצפייה וניהול
4. **WebUI** – מסך Monitor עם עדכון אוטומטי
5. **ChatOps** – פקודת `/jobs` לניהול מהבוט

### שלבי מימוש מומלצים

1. **שלב 1:** מימוש `JobRegistry` ו-`JobTracker`
2. **שלב 2:** רישום ה-jobs הקיימים
3. **שלב 3:** הוספת API endpoints
4. **שלב 4:** פיתוח ה-WebUI
5. **שלב 5:** אינטגרציה עם ChatOps
6. **שלב 6:** התראות ו-observability

---

> **הערה:** מדריך זה מתאר את התכנון בלבד. המימוש בפועל דורש יצירת הקבצים והשינויים המתוארים.
