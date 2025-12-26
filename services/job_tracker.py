# services/job_tracker.py
"""
מודול למעקב אחרי הרצות של Background Jobs.

JobTracker מנהל את מחזור החיים של הרצות: התחלה, עדכון התקדמות, סיום/כישלון.
שומר היסטוריה ב-MongoDB עם TTL Index לניקוי אוטומטי.
"""

import uuid
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """סטטוס הרצה"""
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


class JobAlreadyRunningError(Exception):
    """נזרק כאשר מנסים להפעיל Job שכבר רץ"""
    pass


class JobTracker:
    """מעקב אחרי הרצות Jobs"""

    def __init__(self, db_manager: Any = None):
        self._db = db_manager
        self._active_runs: Dict[str, JobRun] = {}

    @property
    def db(self) -> Any:
        """Lazy loading של DB manager"""
        if self._db is None:
            try:
                from database import db
                self._db = db
            except Exception:
                self._db = None
        return self._db

    @property
    def db_name(self) -> str:
        """שם ה-database"""
        if self.db is None:
            return "test"
        # תמיכה ב-mock DB עם db_name כ-attribute
        if hasattr(self.db, "db_name"):
            return self.db.db_name
        # תמיכה ב-DatabaseManager אמיתי
        if hasattr(self.db, "db") and hasattr(self.db.db, "name"):
            return self.db.db.name
        return "code_keeper_bot"

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
            existing = [
                r for r in self._active_runs.values()
                if r.job_id == job_id and r.status == JobStatus.RUNNING
            ]
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

        # Emit observability event (best-effort)
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
        user_id: Optional[int] = None,
        allow_concurrent: bool = False
    ) -> Generator[JobRun, None, None]:
        """Context manager למעקב אחרי הרצה

        שימוש:
            with tracker.track("my_job") as run:
                # ... לוגיקה ...
                tracker.add_log(run.run_id, "info", "Processing...")

        ⚠️ חשוב: השתמש ב-run.run_id ולא ב-get_active_runs()[0]!
        """
        run = self.start_run(job_id, trigger, user_id, allow_concurrent=allow_concurrent)
        try:
            yield run
            self.complete_run(run.run_id)
        except Exception as e:
            self.fail_run(run.run_id, str(e))
            raise

    def _persist_run(self, run: JobRun) -> None:
        """שמירת הרצה ל-DB"""
        try:
            if self.db is None:
                return

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

            # תמיכה ב-mock DB
            if hasattr(self.db, "client"):
                self.db.client[self.db_name]["job_runs"].update_one(
                    {"run_id": run.run_id},
                    {"$set": doc},
                    upsert=True
                )
            elif hasattr(self.db, "db") and self.db.db is not None:
                self.db.db["job_runs"].update_one(
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
            if self.db is None:
                return None

            doc = None
            if hasattr(self.db, "client"):
                doc = self.db.client[self.db_name]["job_runs"].find_one(
                    {"run_id": run_id}
                )
            elif hasattr(self.db, "db") and self.db.db is not None:
                doc = self.db.db["job_runs"].find_one({"run_id": run_id})

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
            if self.db is None:
                return []

            cursor = None
            if hasattr(self.db, "client"):
                cursor = self.db.client[self.db_name]["job_runs"].find(
                    {"job_id": job_id}
                ).sort("started_at", -1).limit(limit)
            elif hasattr(self.db, "db") and self.db.db is not None:
                cursor = self.db.db["job_runs"].find(
                    {"job_id": job_id}
                ).sort("started_at", -1).limit(limit)

            if cursor:
                return [self._doc_to_run(doc) for doc in cursor]
        except Exception:
            pass
        return []

    def get_active_runs(self) -> List[JobRun]:
        """רשימת הרצות פעילות"""
        return list(self._active_runs.values())

    def get_failed_runs(self, limit: int = 10) -> List[JobRun]:
        """רשימת הרצות שנכשלו"""
        try:
            if self.db is None:
                return []

            cursor = None
            if hasattr(self.db, "client"):
                cursor = self.db.client[self.db_name]["job_runs"].find(
                    {"status": "failed"}
                ).sort("ended_at", -1).limit(limit)
            elif hasattr(self.db, "db") and self.db.db is not None:
                cursor = self.db.db["job_runs"].find(
                    {"status": "failed"}
                ).sort("ended_at", -1).limit(limit)

            if cursor:
                return [self._doc_to_run(doc) for doc in cursor]
        except Exception:
            pass
        return []

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


# Singleton instance with thread-safe initialization
_tracker: Optional[JobTracker] = None
_tracker_lock = threading.Lock()


def get_job_tracker() -> JobTracker:
    """קבלת Singleton instance של JobTracker (thread-safe)"""
    global _tracker
    # בדיקה ראשונה (לביצועים - כדי לא לנעול אם כבר קיים)
    if _tracker is None:
        with _tracker_lock:
            # בדיקה שנייה (בטיחות - לוודא שאף אחד לא יצר בזמן שחיכינו למנעול)
            if _tracker is None:
                _tracker = JobTracker()
    return _tracker


def reset_job_tracker() -> None:
    """איפוס ה-tracker (לשימוש בטסטים)"""
    global _tracker
    with _tracker_lock:
        _tracker = None
