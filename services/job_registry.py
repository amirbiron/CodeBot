# services/job_registry.py
"""
מודול לרישום מרכזי של כל ה-Background Jobs במערכת.

JobRegistry הוא Singleton שמנהל את הגדרות ה-Jobs הידועים במערכת.
"""

import threading
import os
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum

logger = logging.getLogger(__name__)


class JobType(Enum):
    """סוג ה-Job"""
    REPEATING = "repeating"      # חוזר לפי אינטרוול
    ONCE = "once"                # חד-פעמי
    ON_DEMAND = "on_demand"      # לפי דרישה (ידני/API)


class JobCategory(Enum):
    """קטגוריית ה-Job"""
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


class JobRegistry:
    """Singleton לרישום כל ה-Jobs במערכת"""

    _instance: Optional["JobRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "JobRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    # חשוב: מאתחלים את _jobs לפני שחושפים את ה-instance
                    # כדי למנוע race condition שבו thread אחר רואה instance
                    # אבל _jobs עדיין לא קיים
                    new_instance = super().__new__(cls)
                    new_instance._jobs = {}  # type annotation in __init__
                    cls._instance = new_instance
        return cls._instance

    def __init__(self) -> None:
        """Initialize the instance (only once)"""
        if not hasattr(self, '_jobs'):
            self._jobs: Dict[str, JobDefinition] = {}

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
            return os.getenv(job.env_toggle, "").lower() in ("1", "true", "yes", "on")
        return job.enabled

    def clear(self) -> None:
        """מחיקת כל ה-Jobs (לשימוש בטסטים)"""
        self._jobs.clear()


def register_job(
    job_id: str,
    name: str,
    description: str,
    category: JobCategory,
    job_type: JobType,
    **kwargs: Any
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
