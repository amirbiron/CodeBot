from dataclasses import dataclass, field
from typing import Optional, Dict, Any, ClassVar, List
from enum import Enum
import threading
import logging

logger = logging.getLogger(__name__)


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

    job_id: str  # מזהה ייחודי
    name: str  # שם תצוגה
    description: str  # תיאור
    category: JobCategory  # קטגוריה
    job_type: JobType  # סוג (חוזר/חד-פעמי/on-demand)
    interval_seconds: Optional[int] = None  # אינטרוול (ל-repeating)
    enabled: bool = True  # האם מופעל
    env_toggle: Optional[str] = None  # משתנה סביבה להפעלה/כיבוי
    callback_name: str = ""  # שם הפונקציה המופעלת
    source_file: str = ""  # קובץ מקור
    metadata: Dict[str, Any] = field(default_factory=dict)


class JobRegistry:
    """Singleton לרישום כל ה-Jobs במערכת"""

    _instance: ClassVar[Optional["JobRegistry"]] = None
    _lock: ClassVar[threading.Lock] = threading.Lock()
    _jobs: Dict[str, JobDefinition]

    def __new__(cls) -> "JobRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._jobs = {}
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


def register_job(
    job_id: str,
    name: str,
    description: str,
    category: JobCategory,
    job_type: JobType,
    **kwargs,
) -> JobDefinition:
    """רישום Job חדש במערכת"""
    job = JobDefinition(
        job_id=job_id,
        name=name,
        description=description,
        category=category,
        job_type=job_type,
        **kwargs,
    )
    JobRegistry().register(job)
    return job

