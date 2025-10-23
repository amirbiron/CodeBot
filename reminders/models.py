from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from enum import Enum
import re


class ReminderPriority(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class ReminderStatus(Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SNOOZED = "snoozed"
    FAILED = "failed"


class ReminderType(Enum):
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    REVIEW = "review"
    LEARNING = "learning"
    GENERAL = "general"


class RecurrenceType(Enum):
    NONE = "none"
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    CUSTOM = "custom"


@dataclass
class ReminderConfig:
    max_reminders_per_user: int = 50
    max_title_length: int = 200
    max_description_length: int = 1000
    min_reminder_interval_minutes: int = 5
    max_future_days: int = 365
    default_snooze_minutes: int = 60
    max_retries: int = 3
    retry_delay_seconds: int = 60


@dataclass
class Reminder:
    reminder_id: str
    user_id: int
    title: str
    description: str = ""
    file_name: Optional[str] = None
    project_name: Optional[str] = None
    priority: ReminderPriority = ReminderPriority.MEDIUM
    status: ReminderStatus = ReminderStatus.PENDING
    reminder_type: ReminderType = ReminderType.GENERAL
    remind_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    snooze_until: Optional[datetime] = None
    recurrence: RecurrenceType = RecurrenceType.NONE
    recurrence_pattern: Optional[str] = None
    next_occurrence: Optional[datetime] = None
    tags: List[str] = field(default_factory=list)
    line_number: Optional[int] = None
    is_sent: bool = False
    retry_count: int = 0
    last_error: Optional[str] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    user_timezone: str = "UTC"
    chat_id: Optional[int] = None

    def validate(self) -> tuple[bool, str]:
        if not self.title or not self.title.strip():
            return False, "כותרת חובה"
        if len(self.title) > ReminderConfig.max_title_length:
            return False, f"כותרת ארוכה מדי (מקסימום {ReminderConfig.max_title_length} תווים)"
        if len(self.description) > ReminderConfig.max_description_length:
            return False, f"תיאור ארוך מדי (מקסימום {ReminderConfig.max_description_length} תווים)"
        # Disallow potentially dangerous characters often problematic in UIs/markdown
        # Space must be allowed; do NOT include whitespace here.
        dangerous_pattern = r"[<>\{\}\[\]`]"
        if re.search(dangerous_pattern, self.title + self.description):
            return False, "תווים לא חוקיים בטקסט"
        now = datetime.now(timezone.utc)
        if self.remind_at < now:
            return False, "זמן התזכורת חייב להיות בעתיד"
        max_future = now + timedelta(days=ReminderConfig.max_future_days)
        if self.remind_at > max_future:
            return False, f"ניתן לתזמן עד {ReminderConfig.max_future_days} ימים קדימה"
        return True, ""

    def to_dict(self) -> dict:
        return {
            "reminder_id": self.reminder_id,
            "user_id": self.user_id,
            "title": self.title,
            "description": self.description,
            "file_name": self.file_name,
            "project_name": self.project_name,
            "priority": self.priority.value,
            "status": self.status.value,
            "reminder_type": self.reminder_type.value,
            "remind_at": self.remind_at,
            "snooze_until": self.snooze_until,
            "recurrence": self.recurrence.value,
            "recurrence_pattern": self.recurrence_pattern,
            "next_occurrence": self.next_occurrence,
            "tags": self.tags,
            "line_number": self.line_number,
            "is_sent": self.is_sent,
            "retry_count": self.retry_count,
            "last_error": self.last_error,
            "completed_at": self.completed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "user_timezone": self.user_timezone,
            "chat_id": self.chat_id,
        }
