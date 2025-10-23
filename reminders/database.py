from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

try:
    from pymongo import ASCENDING, DESCENDING, IndexModel  # type: ignore
    from pymongo.errors import DuplicateKeyError  # type: ignore
except Exception:  # pragma: no cover - fallback stubs for test envs without pymongo
    ASCENDING = 1  # type: ignore[assignment]
    DESCENDING = -1  # type: ignore[assignment]

    class IndexModel:  # type: ignore
        def __init__(self, *args, **kwargs) -> None:
            pass

    class DuplicateKeyError(Exception):  # type: ignore
        pass

from database import db as _dbm
from .models import Reminder, ReminderConfig, ReminderStatus, RecurrenceType

logger = logging.getLogger(__name__)


class RemindersDB:
    """מנהל DB לתזכורות"""

    def __init__(self, db_manager=None):
        self.dbm = db_manager or _dbm
        self.db = self.dbm.db
        self.reminders_collection = self.db.reminders
        self.reminders_stats = self.db.reminders_stats
        self._ensure_indexes()

    def _ensure_indexes(self) -> None:
        try:
            indexes = [
                IndexModel([("user_id", ASCENDING), ("title", ASCENDING), ("remind_at", ASCENDING)], name="unique_reminder", unique=True),
                IndexModel([("status", ASCENDING), ("remind_at", ASCENDING), ("is_sent", ASCENDING)], name="pending_reminders"),
                IndexModel([("user_id", ASCENDING), ("status", ASCENDING), ("created_at", DESCENDING)], name="user_reminders"),
                IndexModel([("user_id", ASCENDING), ("file_name", ASCENDING), ("status", ASCENDING)], name="file_reminders"),
                IndexModel([("completed_at", ASCENDING)], name="completed_ttl", expireAfterSeconds=30 * 24 * 60 * 60),
                IndexModel([("title", "text"), ("description", "text")], name="text_search"),
            ]
            self.reminders_collection.create_indexes(indexes)
        except Exception as e:
            logger.warning(f"Reminder indexes error: {e}")

    def create_reminder(self, reminder: Reminder) -> tuple[bool, str]:
        try:
            ok, err = reminder.validate()
            if not ok:
                return False, err
            count = self.get_user_reminders_count(reminder.user_id)
            if count >= ReminderConfig.max_reminders_per_user:
                return False, f"הגעת למגבלה של {ReminderConfig.max_reminders_per_user} תזכורות"
            res = self.reminders_collection.insert_one(reminder.to_dict())
            try:
                self._update_stats(reminder.user_id, "created")
            except Exception:
                pass
            return True, str(res.inserted_id)
        except DuplicateKeyError:
            return False, "תזכורת דומה כבר קיימת"
        except Exception as e:
            logger.error(f"שגיאה ביצירת תזכורת: {e}")
            return False, "שגיאה ביצירת תזכורת"

    def get_user_reminders_count(self, user_id: int, status: Optional[str] = None) -> int:
        q: Dict[str, Any] = {"user_id": int(user_id)}
        if status:
            q["status"] = status
        try:
            return int(self.reminders_collection.count_documents(q))
        except Exception:
            return 0

    def get_pending_reminders(self, batch_size: int = 100) -> List[Dict]:
        now = datetime.now(timezone.utc)
        items: List[Dict[str, Any]] = []
        try:
            cursor = self.reminders_collection.find({
                "status": ReminderStatus.PENDING.value,
                "is_sent": False,
                "remind_at": {"$lte": now},
                "retry_count": {"$lt": ReminderConfig.max_retries},
            }).limit(int(batch_size))
            for doc in cursor:
                # optimistic lock: mark as sent
                r = self.reminders_collection.update_one(
                    {"_id": doc["_id"], "is_sent": False},
                    {"$set": {"is_sent": True, "updated_at": now}},
                )
                if getattr(r, "modified_count", 0) > 0:
                    items.append(doc)
        except Exception:
            return []
        return items

    def mark_reminder_sent(self, reminder_id: str, success: bool = True, error: str | None = None) -> None:
        upd: Dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
        if success:
            upd.update({
                "status": ReminderStatus.COMPLETED.value,
                "completed_at": datetime.now(timezone.utc),
            })
            self.reminders_collection.update_one({"reminder_id": reminder_id}, {"$set": upd})
            try:
                self._update_stats(None, "completed")
            except Exception:
                pass
        else:
            self.reminders_collection.update_one(
                {"reminder_id": reminder_id},
                {"$set": {"last_error": str(error or ""), "is_sent": False}, "$inc": {"retry_count": 1}},
            )

    def complete_reminder(self, user_id: int, reminder_id: str) -> bool:
        r = self.reminders_collection.update_one(
            {"user_id": int(user_id), "reminder_id": reminder_id, "status": {"$ne": ReminderStatus.COMPLETED.value}},
            {"$set": {"status": ReminderStatus.COMPLETED.value, "completed_at": datetime.now(timezone.utc), "updated_at": datetime.now(timezone.utc)}},
        )
        if getattr(r, "modified_count", 0) > 0:
            try:
                self._update_stats(user_id, "completed")
            except Exception:
                pass
            return True
        return False

    def snooze_reminder(self, user_id: int, reminder_id: str, minutes: int = 60) -> bool:
        if minutes < 1 or minutes > 24 * 60:
            return False
        new_time = datetime.now(timezone.utc) + timedelta(minutes=int(minutes))
        r = self.reminders_collection.update_one(
            {"user_id": int(user_id), "reminder_id": reminder_id, "status": ReminderStatus.PENDING.value},
            {"$set": {"status": ReminderStatus.SNOOZED.value, "snooze_until": new_time, "remind_at": new_time, "is_sent": False, "updated_at": datetime.now(timezone.utc)}},
        )
        return bool(getattr(r, "modified_count", 0) > 0)

    def get_user_reminders(self, user_id: int, status: Optional[str] = None, limit: int = 50, skip: int = 0) -> List[Dict]:
        q: Dict[str, Any] = {"user_id": int(user_id)}
        if status:
            q["status"] = status
        try:
            return list(self.reminders_collection.find(q).sort("remind_at", ASCENDING).skip(int(skip)).limit(int(limit)))
        except Exception:
            return []

    def delete_reminder(self, user_id: int, reminder_id: str) -> bool:
        r = self.reminders_collection.delete_one({"user_id": int(user_id), "reminder_id": reminder_id})
        return bool(getattr(r, "deleted_count", 0) > 0)

    def _update_stats(self, user_id: int | None, action: str) -> None:
        try:
            self.reminders_stats.update_one(
                {"user_id": int(user_id) if user_id is not None else -1},
                {"$inc": {f"actions.{action}": 1}, "$set": {"last_action": datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception:
            pass

    def handle_recurring_reminders(self) -> None:
        now = datetime.now(timezone.utc)
        try:
            cursor = self.reminders_collection.find({
                "status": ReminderStatus.COMPLETED.value,
                "recurrence": {"$ne": RecurrenceType.NONE.value},
                "next_occurrence": {"$lte": now},
            })
        except Exception:
            cursor = []
        for rem in cursor:
            next_time = self._calculate_next_occurrence(rem.get("recurrence"), rem.get("recurrence_pattern"))
            if not next_time:
                continue
            new_doc = dict(rem)
            new_doc.pop("_id", None)
            new_doc["reminder_id"] = f"{rem.get('reminder_id')}_r_{int(now.timestamp())}"
            new_doc["status"] = ReminderStatus.PENDING.value
            new_doc["remind_at"] = next_time
            new_doc["next_occurrence"] = self._calculate_next_occurrence(rem.get("recurrence"), rem.get("recurrence_pattern"), base_time=next_time)
            new_doc["is_sent"] = False
            new_doc["created_at"] = now
            new_doc["updated_at"] = now
            try:
                self.reminders_collection.insert_one(new_doc)
            except Exception:
                pass

    def _calculate_next_occurrence(self, recurrence: str | None, pattern: Optional[str] = None, base_time: Optional[datetime] = None) -> Optional[datetime]:
        if not base_time:
            base_time = datetime.now(timezone.utc)
        if recurrence == RecurrenceType.DAILY.value:
            from datetime import timedelta
            return base_time + timedelta(days=1)
        if recurrence == RecurrenceType.WEEKLY.value:
            from datetime import timedelta
            return base_time + timedelta(weeks=1)
        if recurrence == RecurrenceType.MONTHLY.value:
            from datetime import timedelta
            return base_time + timedelta(days=30)
        # CUSTOM: intentionally skipped in MVP
        return None
