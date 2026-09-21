import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List
from enum import Enum
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


#: הסטטוסים שמהם אין דרך חזרה. אחרי שהרצה קיבלה אחד מהם, כתיבה שמחזירה
#: אותה ל-``running`` אינה עדכון אלא תחייה — והיא הייתה משאירה את הרשומה
#: פתוחה לנצח, כי הפיוס ב-``services/job_orphan_reconciler.py`` רץ פעם אחת
#: בעלייה ולא חוזר. ‏``CANCELLED`` נכלל אף שאיש עדיין אינו כותב אותו: קבוצה
#: שמונה רק את מה שכתוב היום מתיישנת ברגע שמישהו מוסיף ביטול.
TERMINAL_STATUSES = frozenset(
    {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.SKIPPED}
)

#: כמה רשומות לוג נשמרות על הרצה. הקורא השני הוא הפיוס, שדוחף רשומה
#: ב-``$push`` עם ``$slice`` — והמספר חייב להיות אותו מספר, אחרת שתי
#: הכתיבות חותכות את אותה רשימה לשני אורכים.
JOB_RUN_LOGS_KEPT = 50


@dataclass
class JobLogEntry:
    """רשומת לוג בודדת"""

    timestamp: datetime
    level: str  # info/warning/error
    message: str
    details: Optional[Dict[str, Any]] = None


@dataclass
class JobRun:
    """הרצה בודדת של Job"""

    run_id: str  # מזהה הרצה ייחודי
    job_id: str  # מזהה ה-Job
    started_at: datetime
    ended_at: Optional[datetime] = None
    status: JobStatus = JobStatus.PENDING
    progress: int = 0  # 0-100
    total_items: int = 0  # סה"כ פריטים לעיבוד
    processed_items: int = 0  # פריטים שעובדו
    error_message: Optional[str] = None
    logs: List[JobLogEntry] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None  # תוצאה סופית
    trigger: str = "scheduled"  # scheduled/manual/api
    user_id: Optional[int] = None  # אם רלוונטי למשתמש


class JobAlreadyRunningError(Exception):
    """נזרק כאשר מנסים להפעיל Job שכבר רץ"""

    pass


class JobTracker:
    """מעקב אחרי הרצות Jobs"""

    def __init__(self, db_manager=None):
        if db_manager is None:
            from database import db

            self.db = db
        else:
            self.db = db_manager
        self._active_runs: Dict[str, JobRun] = {}
        #: מי מריץ את ההרצות האלה — נכתב על כל רשומה לצורך אבחון, ומוצג
        #: בעמוד ההרצה. נקבע פעם אחת מ-``main.py`` אחרי שהמנעול נרכש; כאן
        #: אין ייבוא של מודול המנעול, כדי לא לשכפל את כלל גזירת המזהה.
        #: ‏``None`` הוא מצב לגיטימי (בדיקות, הרצה בלי מנעול).
        self.owner_id: Optional[str] = None

    def start_run(
        self,
        job_id: str,
        trigger: str = "scheduled",
        user_id: Optional[int] = None,
        total_items: int = 0,
        allow_concurrent: bool = False,
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
                r
                for r in self._active_runs.values()
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
            total_items=total_items,
        )
        self._active_runs[run.run_id] = run
        self._persist_run(run, allow_create=True)

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
        message: Optional[str] = None,
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
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """הוספת לוג להרצה"""
        run = self._active_runs.get(run_id)
        if not run:
            return

        entry = JobLogEntry(
            timestamp=datetime.now(timezone.utc),
            level=level,
            message=message,
            details=details,
        )
        run.logs.append(entry)

        # שמירה ל-DB רק כל 10 לוגים או ב-error
        if level == "error" or len(run.logs) % 10 == 0:
            self._persist_run(run)

    def complete_run(self, run_id: str, result: Optional[Dict[str, Any]] = None) -> None:
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
                duration_seconds=duration,
            )
        except Exception:
            pass

    def fail_run(self, run_id: str, error_message: str) -> None:
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
                error=error_message,
            )
        except Exception:
            pass

    def skip_run(self, run_id: str, reason: str = "") -> None:
        """סיום הרצה כדילוג (למשל disabled או already-running)."""
        run = self._active_runs.get(run_id)
        if not run:
            return

        run.status = JobStatus.SKIPPED
        run.ended_at = datetime.now(timezone.utc)
        if reason:
            run.error_message = str(reason)
            self.add_log(run_id, "warning", f"Skipped: {reason}")
        else:
            self.add_log(run_id, "warning", "Skipped")

        self._persist_run(run)
        self._active_runs.pop(run_id, None)

        try:
            from observability import emit_event

            emit_event(
                "job_skipped",
                severity="warning",
                job_id=run.job_id,
                run_id=run_id,
                reason=str(reason or ""),
            )
        except Exception:
            pass

    def record_skipped(
        self,
        *,
        job_id: str,
        trigger: str = "scheduled",
        user_id: Optional[int] = None,
        reason: str = "",
    ) -> JobRun:
        """רישום דילוג גם כשאין run פעיל (למשל already-running לפני start_run)."""
        now = datetime.now(timezone.utc)
        run = JobRun(
            run_id=str(uuid.uuid4())[:12],
            job_id=str(job_id),
            started_at=now,
            ended_at=now,
            status=JobStatus.SKIPPED,
            progress=0,
            error_message=str(reason or ""),
            trigger=str(trigger or "scheduled"),
            user_id=user_id,
        )
        try:
            run.logs.append(
                JobLogEntry(
                    timestamp=now,
                    level="warning",
                    message=f"Skipped: {reason or 'skipped'}",
                    details={"reason": str(reason or "")} if reason else None,
                )
            )
        except Exception:
            pass
        self._persist_run(run, allow_create=True)
        try:
            from observability import emit_event

            emit_event(
                "job_skipped",
                severity="warning",
                job_id=run.job_id,
                run_id=run.run_id,
                reason=str(reason or ""),
            )
        except Exception:
            pass
        return run

    @contextmanager
    def track(
        self,
        job_id: str,
        trigger: str = "scheduled",
        user_id: Optional[int] = None,
    ):
        """Context manager למעקב אחרי הרצה"""
        run = self.start_run(job_id, trigger, user_id)
        try:
            yield run
            self.complete_run(run.run_id)
        except Exception as e:
            self.fail_run(run.run_id, str(e))
            raise

    def _persist_run(self, run: JobRun, *, allow_create: bool = False) -> bool:
        """שמירת הרצה ל-DB.

        Args:
            allow_create: האם מותר ליצור מסמך שאינו קיים. רק שתי נקודות
                יוצרות הרצה — ``start_run`` ו-``record_skipped``. לשאר
                הכתיבות ``upsert`` היה מייצר מסמך חדש מתוך שם ההרצה
                כשהמסנן אינו תואם, ומתנגש באינדקס הייחודי.

        Returns:
            ‏``True`` אם הכתיבה נחתה. ‏``False`` בשני מקרים, ושניהם נרשמים
            בלוג: חריגה מהמסד, או כתיבה **לא סופית** שנדחתה כי ההרצה כבר
            הגיעה לסטטוס סופי. המקרה השני אינו תקלה — הוא בדיוק השומר.

        ⚠️ ערוץ הכשל הוא ערך ההחזרה, לא חריגה: ``except`` סביב הקריאה הזו
        לא ירוץ. מי שמדווח הצלחה אחריה חייב לבדוק את הערך.
        """
        is_terminal = run.status in TERMINAL_STATUSES
        if is_terminal:
            # תוצאה אמיתית לעולם אינה נחסמת. גם אם הפיוס הספיק לסמן את
            # ההרצה כיתומה, ההרצה עצמה רשאית לכתוב את הסוף שלה.
            flt: Dict[str, Any] = {"run_id": run.run_id}
            upsert = bool(allow_create)
        elif allow_create:
            flt = {"run_id": run.run_id}
            upsert = True
        else:
            # השומר: כתיבה שמחזירה הרצה סופית ל-``running`` היא תחייה.
            flt = {
                "run_id": run.run_id,
                "status": {"$nin": sorted(s.value for s in TERMINAL_STATUSES)},
            }
            upsert = False

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
                        "details": log.details,
                    }
                    for log in run.logs[-JOB_RUN_LOGS_KEPT:]
                ],
                "result": run.result,
                "trigger": run.trigger,
                "user_id": run.user_id,
                "owner_id": self.owner_id,
            }
            result = self.db.client[self.db.db_name]["job_runs"].update_one(
                flt,
                {
                    "$set": doc,
                    # ‏``failure_reason`` מתאר ייחוס חיצוני — מי שסגר את
                    # ההרצה במקומה. ברגע שההרצה מדווחת על עצמה, הייחוס
                    # הזה מתיישן, ו-status בלי ניקוי שלו היה משאיר זוג
                    # סותר: ``completed`` עם ``orphaned``.
                    "$unset": {"failure_reason": ""},
                },
                upsert=upsert,
            )
        except Exception as e:
            logger.error(f"Failed to persist job run: {e}")
            return False

        matched = int(getattr(result, "matched_count", 0) or 0)
        if matched or getattr(result, "upserted_id", None) is not None:
            return True

        # שני מצבים מגיעים לכאן, ושניהם ראויים לשורה: כתיבה לא סופית
        # שהשומר דחה כי ההרצה כבר סופית, וכתיבה על הרצה שאין לה מסמך כלל
        # (הכתיבה היוצרת נכשלה קודם). ההבחנה ביניהם היא ב-``guarded``.
        logger.warning(
            "job run persist did not match any document",
            extra={
                "event": "job_run_persist_rejected",
                "run_id": run.run_id,
                "job_id": run.job_id,
                "attempted_status": run.status.value,
                "guarded": not is_terminal and not allow_create,
            },
        )
        return False

    def get_run(self, run_id: str) -> Optional[JobRun]:
        """קבלת הרצה לפי ID"""
        if run_id in self._active_runs:
            return self._active_runs[run_id]

        try:
            doc = self.db.client[self.db.db_name]["job_runs"].find_one({"run_id": run_id})
            if doc:
                return self._doc_to_run(doc)
        except Exception:
            pass
        return None

    def get_job_history(self, job_id: str, limit: int = 20) -> List[JobRun]:
        """היסטוריית הרצות של Job"""
        try:
            cursor = (
                self.db.client[self.db.db_name]["job_runs"]
                .find({"job_id": job_id})
                .sort("started_at", -1)
                .limit(limit)
            )
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
                details=log.get("details"),
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
            user_id=doc.get("user_id"),
        )


_tracker: Optional[JobTracker] = None


def get_job_tracker() -> JobTracker:
    global _tracker
    if _tracker is None:
        _tracker = JobTracker()
    return _tracker

