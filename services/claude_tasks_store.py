"""
Claude Tasks Store
==================
שכבת גישה ל-Mongo עבור משימות שנשלחו ל‑Claude Code דרך הבוט.

עיקרון: כשל DB לא מפיל את הפקודה. אם ה‑DB לא זמין, המשתמש עדיין יוכל לפתוח
Issue — הוא פשוט לא יקבל ‎/claude_status‎ ו‑watchdog. לכן כל פונקציה כאן
בולעת חריגות ומחזירה ערך ברירת מחדל.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# מוגדר גם ב-database/claude_tasks_collection.py (מקור האמת לאינדקסים).
# לא מייבאים משם בטופ-לבל כדי שהמודול הזה ייטען גם בלי כל שרשרת ה-DB.
CLAUDE_TASKS_COLLECTION = "claude_tasks"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def new_request_id() -> str:
    """מזהה קצר למשימה — נכנס ל‑callback_data ולכן חייב להיות קצר."""
    return uuid.uuid4().hex[:8]


def _collection(db_manager: Any = None):
    """מחזיר את ה‑collection, או None אם ה‑DB לא זמין.

    אותו דפוס כמו ב‑services/job_tracker.py: ‎db.client[db.db_name][name]‎.
    """
    try:
        manager = db_manager
        if manager is None:
            # ייבוא עצל: שרשרת ה-DB כבדה ולא צריך אותה כדי לייבא את המודול
            from database import db

            manager = db
        return manager.client[manager.db_name][CLAUDE_TASKS_COLLECTION]
    except Exception:
        logger.debug("claude_tasks: DB unavailable", exc_info=True)
        return None


def create_task(
    *,
    request_id: str,
    user_id: int,
    chat_id: int,
    message_id: Optional[int],
    prompt: str,
    repo: str,
    status: str = "pending_confirm",
    db_manager: Any = None,
) -> bool:
    """יוצר רשומת משימה חדשה. מחזיר True אם נשמרה."""
    coll = _collection(db_manager)
    if coll is None:
        return False
    doc = {
        "request_id": request_id,
        "user_id": int(user_id),
        "chat_id": int(chat_id),
        "message_id": int(message_id) if message_id else None,
        "ack_message_id": None,
        "prompt": str(prompt or "")[:4000],
        "repo": repo,
        "issue_number": None,
        "issue_url": None,
        "run_id": None,
        "run_url": None,
        "pr_url": None,
        "status": status,
        "error": None,
        "created_at": _now(),
        "updated_at": _now(),
    }
    try:
        coll.update_one({"request_id": request_id}, {"$set": doc}, upsert=True)
        return True
    except Exception:
        logger.error("claude_tasks: create failed request_id=%s", request_id, exc_info=True)
        return False


def update_task(request_id: str, fields: Dict[str, Any], *, db_manager: Any = None) -> bool:
    """עדכון חלקי של משימה לפי request_id."""
    coll = _collection(db_manager)
    if coll is None:
        return False
    payload = dict(fields or {})
    payload["updated_at"] = _now()
    try:
        coll.update_one({"request_id": request_id}, {"$set": payload})
        return True
    except Exception:
        logger.error("claude_tasks: update failed request_id=%s", request_id, exc_info=True)
        return False


def get_by_request_id(request_id: str, *, db_manager: Any = None) -> Optional[Dict[str, Any]]:
    coll = _collection(db_manager)
    if coll is None:
        return None
    try:
        return coll.find_one({"request_id": request_id})
    except Exception:
        logger.error("claude_tasks: get_by_request_id failed", exc_info=True)
        return None


def get_by_issue_number(
    issue_number: int, *, user_id: Optional[int] = None, db_manager: Any = None
) -> Optional[Dict[str, Any]]:
    coll = _collection(db_manager)
    if coll is None:
        return None
    query: Dict[str, Any] = {"issue_number": int(issue_number)}
    if user_id is not None:
        query["user_id"] = int(user_id)
    try:
        return coll.find_one(query)
    except Exception:
        logger.error("claude_tasks: get_by_issue_number failed", exc_info=True)
        return None


def list_recent(user_id: int, limit: int = 10, *, db_manager: Any = None) -> List[Dict[str, Any]]:
    """המשימות האחרונות של המשתמש, החדשה ראשונה."""
    coll = _collection(db_manager)
    if coll is None:
        return []
    try:
        cursor = (
            coll.find({"user_id": int(user_id), "status": {"$ne": "pending_confirm"}})
            .sort("created_at", -1)
            .limit(int(limit))
        )
        return list(cursor)
    except Exception:
        logger.error("claude_tasks: list_recent failed", exc_info=True)
        return []


def get_last_for_user(user_id: int, *, db_manager: Any = None) -> Optional[Dict[str, Any]]:
    tasks = list_recent(user_id, limit=1, db_manager=db_manager)
    return tasks[0] if tasks else None


def count_today(user_id: int, *, db_manager: Any = None) -> int:
    """כמה משימות המשתמש שלח ב‑24 השעות האחרונות (למכסה היומית)."""
    coll = _collection(db_manager)
    if coll is None:
        return 0
    since = _now() - timedelta(days=1)
    try:
        return int(
            coll.count_documents(
                {
                    "user_id": int(user_id),
                    "created_at": {"$gte": since},
                    "status": {"$ne": "pending_confirm"},
                }
            )
        )
    except Exception:
        logger.error("claude_tasks: count_today failed", exc_info=True)
        return 0


def count_active(user_id: int, *, db_manager: Any = None) -> int:
    """משימות שעדיין בעבודה — כדי לא להעמיס כמה ריצות במקביל."""
    coll = _collection(db_manager)
    if coll is None:
        return 0
    try:
        return int(
            coll.count_documents(
                {"user_id": int(user_id), "status": {"$in": ["dispatched", "running"]}}
            )
        )
    except Exception:
        logger.error("claude_tasks: count_active failed", exc_info=True)
        return 0
