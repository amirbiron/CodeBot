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
    # ברירת מחדל עבור env_toggle כאשר המשתנה לא מוגדר.
    # None => התנהגות קיימת: אם יש env_toggle והוא חסר => מושבת.
    env_toggle_default: Optional[bool] = None
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

            # ברירת המחדל כשהמשתנה כלל אינו מוגדר. ``None`` פירושו
            # "יש דגל ואין ערך ⇐ מושבת", וזו ההתנהגות ההיסטורית.
            return env_toggle_enabled(
                os.getenv(job.env_toggle), bool(job.env_toggle_default)
            )
        return job.enabled


def env_toggle_enabled(raw: Optional[str], default: bool) -> bool:
    """האם דגל סביבה מפעיל את מה שהוא שולט בו.

    **הבעלים היחיד של הכלל.** ``JobRegistry.is_enabled`` קובע מה הדשבורד
    מציג, וכל קוד שמחליט בעצמו אם לתזמן חייב לענות בדיוק אותו דבר —
    אחרת הדשבורד יראה "מושבת" בזמן שהג'וב רץ, או להפך. רשימת הערכים
    חיה כאן, ולא בעותק שני אצל כל קורא.

    Args:
        raw: הערך כפי שהוא ב-``os.environ``, או ``None`` אם אינו מוגדר.
        default: מה נכון כשהמשתנה כלל אינו מוגדר.

    Returns:
        ‏``True`` רק לערך מוכר של הפעלה. ערך ריק או לא מוכר ⇐ ``False``.
    """
    if raw is None:
        return bool(default)
    return str(raw).lower() in ("1", "true", "yes", "on")


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

