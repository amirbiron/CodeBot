# 📅 פיצ'ר: Reminders - תזכורות ומשימות

## 📋 תיאור כללי

מערכת תזכורות חכמה המאפשרת לקשר משימות, תזכורות ו-TODOs לקבצי קוד. הפיצ'ר עוזר במעקב אחר תיקונים, שיפורים ומשימות פיתוח.

### 🎯 מטרות הפיצ'ר
- מעקב אחר משימות בקוד
- תזכורות לתיקונים ושיפורים
- ניהול TODO list משולב
- התראות אוטומטיות בזמן

### 👤 תרחישי שימוש
1. **Bug Tracking**: תזכורת לתקן bug ספציפי בקובץ
2. **Code Review**: תזכורת לעבור על קוד לפני release
3. **Learning**: תזכורת לחזור לנושא מסוים
4. **Refactoring**: תזכורת לשפר קוד ישן

---

## 🗄️ מבנה Database

### קולקציה חדשה: reminders

```python
# מבנה מסמך בקולקציה reminders

{
    "_id": ObjectId("..."),
    "reminder_id": "rem_abc123xyz",           # מזהה ייחודי
    "user_id": 123456789,                      # בעלים
    "file_name": "api.py",                     # קובץ קשור (אופציונלי)
    "project_name": "WebApp",                  # פרויקט קשור (אופציונלי)
    "title": "לתקן את ה-authentication bug", # כותרת
    "description": "הבעיה בשורה 45 - לא בודק session timeout",  # תיאור
    "priority": "high",                        # עדיפות: low/medium/high/urgent
    "status": "pending",                       # מצב: pending/completed/cancelled/snoozed
    "reminder_type": "bug_fix",                # סוג: bug_fix/feature/refactor/review/learning/general
    "remind_at": ISODate("2024-10-10T10:00:00Z"),  # מתי להזכיר
    "snooze_until": null,                      # דחייה עד זמן מסוים
    "recurrence": null,                        # חזרה: daily/weekly/monthly
    "tags": ["bug", "authentication"],        # תגיות
    "line_number": 45,                         # שורה בקוד (אופציונלי)
    "is_sent": false,                          # האם התזכורת נשלחה
    "completed_at": null,                      # מתי הושלם
    "created_at": ISODate("2024-10-09T10:00:00Z"),
    "updated_at": ISODate("2024-10-09T10:00:00Z")
}
```

### אינדקסים

```python
# ב-database/manager.py - __init__

# קולקציית תזכורות
self.reminders_collection = self.db.reminders

# אינדקס לתזכורות ממתינות
self.reminders_collection.create_index([
    ("user_id", 1),
    ("status", 1),
    ("remind_at", 1)
])

# אינדקס לתזכורות של קובץ
self.reminders_collection.create_index([
    ("user_id", 1),
    ("file_name", 1),
    ("status", 1)
])

# אינדקס לתזכורות שלא נשלחו
self.reminders_collection.create_index([
    ("is_sent", 1),
    ("remind_at", 1),
    ("status", 1)
])
```

---

## 💻 מימוש קוד

### 1. מודל Reminder (database/models.py)

```python
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List
from enum import Enum

class ReminderPriority(Enum):
    """עדיפות תזכורת"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"

class ReminderStatus(Enum):
    """מצב תזכורת"""
    PENDING = "pending"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    SNOOZED = "snoozed"

class ReminderType(Enum):
    """סוג תזכורת"""
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    REFACTOR = "refactor"
    REVIEW = "review"
    LEARNING = "learning"
    GENERAL = "general"

@dataclass
class Reminder:
    """מודל תזכורת"""
    reminder_id: str
    user_id: int
    title: str
    description: str = ""
    file_name: Optional[str] = None
    project_name: Optional[str] = None
    priority: str = "medium"
    status: str = "pending"
    reminder_type: str = "general"
    remind_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    snooze_until: Optional[datetime] = None
    recurrence: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    line_number: Optional[int] = None
    is_sent: bool = False
    completed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    def to_dict(self) -> dict:
        """המרה למילון"""
        return {
            "reminder_id": self.reminder_id,
            "user_id": self.user_id,
            "title": self.title,
            "description": self.description,
            "file_name": self.file_name,
            "project_name": self.project_name,
            "priority": self.priority,
            "status": self.status,
            "reminder_type": self.reminder_type,
            "remind_at": self.remind_at,
            "snooze_until": self.snooze_until,
            "recurrence": self.recurrence,
            "tags": self.tags,
            "line_number": self.line_number,
            "is_sent": self.is_sent,
            "completed_at": self.completed_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
```

---

### 2. פונקציות Database (database/manager.py)

```python
import secrets
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

def create_reminder(
    self,
    user_id: int,
    title: str,
    remind_at: datetime,
    description: str = "",
    file_name: str = None,
    project_name: str = None,
    priority: str = "medium",
    reminder_type: str = "general",
    tags: List[str] = None,
    line_number: int = None
) -> Optional[str]:
    """
    יצירת תזכורת חדשה
    
    Returns:
        reminder_id אם הצליח, None אם נכשל
    """
    try:
        reminder_id = f"rem_{secrets.token_urlsafe(16)}"
        
        reminder_data = {
            "reminder_id": reminder_id,
            "user_id": user_id,
            "title": title,
            "description": description,
            "file_name": file_name,
            "project_name": project_name,
            "priority": priority,
            "status": "pending",
            "reminder_type": reminder_type,
            "remind_at": remind_at,
            "snooze_until": None,
            "recurrence": None,
            "tags": tags or [],
            "line_number": line_number,
            "is_sent": False,
            "completed_at": None,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        
        self.reminders_collection.insert_one(reminder_data)
        logger.info(f"תזכורת {reminder_id} נוצרה")
        return reminder_id
        
    except Exception as e:
        logger.error(f"שגיאה ביצירת תזכורת: {e}")
        return None


def get_user_reminders(
    self,
    user_id: int,
    status: str = None,
    file_name: str = None,
    limit: int = 50
) -> List[Dict]:
    """קבלת תזכורות של משתמש"""
    try:
        query = {"user_id": user_id}
        
        if status:
            query["status"] = status
        
        if file_name:
            query["file_name"] = file_name
        
        reminders = list(
            self.reminders_collection.find(query)
            .sort("remind_at", 1)  # מוקדם ביותר ראשון
            .limit(limit)
        )
        
        for r in reminders:
            r["_id"] = str(r["_id"])
        
        return reminders
        
    except Exception as e:
        logger.error(f"שגיאה בקבלת תזכורות: {e}")
        return []


def get_pending_reminders(self, user_id: int = None) -> List[Dict]:
    """
    קבלת תזכורות שצריך לשלוח
    
    Args:
        user_id: אם None, מחזיר לכל המשתמשים (לתהליך רקע)
    """
    try:
        now = datetime.now(timezone.utc)
        
        query = {
            "status": "pending",
            "is_sent": False,
            "remind_at": {"$lte": now}
        }
        
        if user_id:
            query["user_id"] = user_id
        
        reminders = list(
            self.reminders_collection.find(query)
            .sort("remind_at", 1)
        )
        
        for r in reminders:
            r["_id"] = str(r["_id"])
        
        return reminders
        
    except Exception as e:
        logger.error(f"שגיאה בקבלת תזכורות ממתינות: {e}")
        return []


def complete_reminder(self, user_id: int, reminder_id: str) -> bool:
    """סימון תזכורת כהושלמה"""
    try:
        result = self.reminders_collection.update_one(
            {
                "user_id": user_id,
                "reminder_id": reminder_id
            },
            {
                "$set": {
                    "status": "completed",
                    "completed_at": datetime.now(timezone.utc),
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        
        return result.modified_count > 0
        
    except Exception as e:
        logger.error(f"שגיאה בסימון תזכורת: {e}")
        return False


def snooze_reminder(
    self,
    user_id: int,
    reminder_id: str,
    snooze_minutes: int = 60
) -> bool:
    """דחיית תזכורת"""
    try:
        new_time = datetime.now(timezone.utc) + timedelta(minutes=snooze_minutes)
        
        result = self.reminders_collection.update_one(
            {
                "user_id": user_id,
                "reminder_id": reminder_id
            },
            {
                "$set": {
                    "status": "snoozed",
                    "snooze_until": new_time,
                    "remind_at": new_time,
                    "is_sent": False,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        
        return result.modified_count > 0
        
    except Exception as e:
        logger.error(f"שגיאה בדחיית תזכורת: {e}")
        return False


def mark_reminder_sent(self, reminder_id: str) -> bool:
    """סימון תזכורת כנשלחה"""
    try:
        self.reminders_collection.update_one(
            {"reminder_id": reminder_id},
            {"$set": {"is_sent": True}}
        )
        return True
    except Exception as e:
        logger.error(f"שגיאה בסימון תזכורת כנשלחה: {e}")
        return False


def delete_reminder(self, user_id: int, reminder_id: str) -> bool:
    """מחיקת תזכורת"""
    try:
        result = self.reminders_collection.delete_one({
            "user_id": user_id,
            "reminder_id": reminder_id
        })
        
        return result.deleted_count > 0
        
    except Exception as e:
        logger.error(f"שגיאה במחיקת תזכורת: {e}")
        return False


def get_reminders_stats(self, user_id: int) -> Dict:
    """סטטיסטיקות תזכורות"""
    try:
        total = self.reminders_collection.count_documents({"user_id": user_id})
        pending = self.reminders_collection.count_documents({
            "user_id": user_id,
            "status": "pending"
        })
        completed = self.reminders_collection.count_documents({
            "user_id": user_id,
            "status": "completed"
        })
        overdue = self.reminders_collection.count_documents({
            "user_id": user_id,
            "status": "pending",
            "remind_at": {"$lt": datetime.now(timezone.utc)}
        })
        
        return {
            "total": total,
            "pending": pending,
            "completed": completed,
            "overdue": overdue
        }
        
    except Exception as e:
        logger.error(f"שגיאה בסטטיסטיקות: {e}")
        return {}
```

---

### 3. Handler (reminders_handler.py)

```python
"""
מטפל בתזכורות - Reminders Handler
"""

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import (
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

from database import db
from activity_reporter import create_reporter

logger = logging.getLogger(__name__)

# שלבי שיחה
REMINDER_TITLE, REMINDER_TIME = range(2)

reporter = create_reporter(
    mongodb_uri="mongodb+srv://mumin:M43M2TFgLfGvhBwY@muminai.tm6x81b.mongodb.net/?retryWrites=true&w=majority&appName=muminAI",
    service_id="srv-d3ilh4vfte5s7392s000",
    service_name="CodeBot3"
)

# אייקונים לסוגי תזכורות
REMINDER_ICONS = {
    "bug_fix": "🐛",
    "feature": "✨",
    "refactor": "♻️",
    "review": "👀",
    "learning": "📚",
    "general": "📌"
}

PRIORITY_ICONS = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🟠",
    "urgent": "🔴"
}


def parse_time_string(time_str: str) -> Optional[datetime]:
    """
    המרת מחרוזת זמן לdatetime
    
    תומך ב:
    - tomorrow 10:00
    - in 2 hours
    - next week
    - 2024-10-15 14:30
    """
    try:
        time_str = time_str.lower().strip()
        now = datetime.now(timezone.utc)
        
        # מחר
        if time_str.startswith("tomorrow") or time_str.startswith("מחר"):
            # מחר בשעה מסוימת
            time_match = re.search(r'(\d{1,2}):(\d{2})', time_str)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2))
                target = now + timedelta(days=1)
                return target.replace(hour=hour, minute=minute, second=0, microsecond=0)
            else:
                # מחר ב-9:00
                target = now + timedelta(days=1)
                return target.replace(hour=9, minute=0, second=0, microsecond=0)
        
        # בעוד X שעות/ימים
        if "in " in time_str or "בעוד" in time_str:
            # in 2 hours
            hours_match = re.search(r'(\d+)\s*hour', time_str)
            if hours_match:
                hours = int(hours_match.group(1))
                return now + timedelta(hours=hours)
            
            # in 3 days
            days_match = re.search(r'(\d+)\s*day', time_str)
            if days_match:
                days = int(days_match.group(1))
                return now + timedelta(days=days)
        
        # שבוע הבא
        if "next week" in time_str or "שבוע הבא" in time_str:
            return now + timedelta(days=7)
        
        # תאריך מלא
        # 2024-10-15 14:30
        datetime_match = re.match(r'(\d{4})-(\d{2})-(\d{2})\s+(\d{1,2}):(\d{2})', time_str)
        if datetime_match:
            year = int(datetime_match.group(1))
            month = int(datetime_match.group(2))
            day = int(datetime_match.group(3))
            hour = int(datetime_match.group(4))
            minute = int(datetime_match.group(5))
            return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
        
        return None
        
    except Exception as e:
        logger.error(f"שגיאה בפענוח זמן: {e}")
        return None


async def remind_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    פקודה: /remind [file_name] "title" time
    התחלת תזכורת
    """
    reporter.report_activity(update.effective_user.id)
    user_id = update.effective_user.id
    
    if not context.args:
        await update.message.reply_text(
            "⏰ <b>יצירת תזכורת</b>\n\n"
            "שימוש:\n"
            "<code>/remind \"כותרת\" זמן</code>\n"
            "או\n"
            "<code>/remind file.py \"כותרת\" זמן</code>\n\n"
            "דוגמאות זמן:\n"
            "• <code>tomorrow 10:00</code> - מחר ב-10:00\n"
            "• <code>in 2 hours</code> - בעוד שעתיים\n"
            "• <code>next week</code> - שבוע הבא\n"
            "• <code>2024-10-15 14:30</code> - תאריך ושעה מדויקים\n\n"
            "דוגמה:\n"
            "<code>/remind api.py \"לתקן bug בשורה 45\" tomorrow 10:00</code>",
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END
    
    # פענוח ארגומנטים
    args_text = " ".join(context.args)
    
    # חיפוש כותרת בגרשיים
    title_match = re.search(r'"([^"]+)"', args_text)
    if not title_match:
        await update.message.reply_text(
            "❌ נא לכלול את הכותרת בגרשיים כפולות:\n"
            '<code>/remind "כותרת התזכורת" tomorrow 10:00</code>',
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END
    
    title = title_match.group(1)
    
    # הסרת הכותרת כדי לקבל את שאר הטקסט
    remaining = args_text.replace(f'"{title}"', "").strip()
    
    # בדיקה אם יש שם קובץ
    file_name = None
    time_str = remaining
    
    parts = remaining.split(maxsplit=1)
    if len(parts) >= 2:
        # אולי החלק הראשון הוא שם קובץ
        possible_file = parts[0]
        if "." in possible_file:  # יש סיומת קובץ
            snippet = db.get_code_snippet(user_id, possible_file)
            if snippet:
                file_name = possible_file
                time_str = parts[1]
    
    # פענוח זמן
    remind_at = parse_time_string(time_str)
    if not remind_at:
        await update.message.reply_text(
            f"❌ לא הצלחתי להבין את הזמן: <code>{time_str}</code>\n\n"
            "נסה:\n"
            "• <code>tomorrow 10:00</code>\n"
            "• <code>in 2 hours</code>\n"
            "• <code>2024-10-15 14:30</code>",
            parse_mode=ParseMode.HTML
        )
        return ConversationHandler.END
    
    # יצירת תזכורת
    reminder_id = db.create_reminder(
        user_id=user_id,
        title=title,
        remind_at=remind_at,
        file_name=file_name
    )
    
    if not reminder_id:
        await update.message.reply_text("❌ שגיאה ביצירת תזכורת")
        return ConversationHandler.END
    
    # הודעת אישור
    message = (
        "✅ <b>תזכורת נוצרה!</b>\n\n"
        f"📌 {title}\n"
    )
    
    if file_name:
        message += f"📄 קובץ: <code>{file_name}</code>\n"
    
    # זמן יחסי
    time_diff = remind_at - datetime.now(timezone.utc)
    if time_diff.days > 0:
        time_str = f"בעוד {time_diff.days} ימים"
    else:
        hours = int(time_diff.total_seconds() / 3600)
        if hours > 0:
            time_str = f"בעוד {hours} שעות"
        else:
            minutes = int(time_diff.total_seconds() / 60)
            time_str = f"בעוד {minutes} דקות"
    
    message += f"⏰ {time_str}\n"
    message += f"\n💡 <code>/reminders</code> לראות את כל התזכורות"
    
    keyboard = [[
        InlineKeyboardButton("📋 כל התזכורות", callback_data="reminders_list"),
        InlineKeyboardButton("🗑️ מחק", callback_data=f"rem_del_{reminder_id}")
    ]]
    
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    
    return ConversationHandler.END


async def reminders_list_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    פקודה: /reminders
    רשימת תזכורות
    """
    reporter.report_activity(update.effective_user.id)
    user_id = update.effective_user.id
    
    # סטטיסטיקות
    stats = db.get_reminders_stats(user_id)
    
    if stats.get("total", 0) == 0:
        await update.message.reply_text(
            "💭 <b>אין לך תזכורות עדיין</b>\n\n"
            "💡 צור תזכורת:\n"
            '<code>/remind "כותרת" tomorrow 10:00</code>',
            parse_mode=ParseMode.HTML
        )
        return
    
    # קבלת תזכורות ממתינות
    reminders = db.get_user_reminders(user_id, status="pending", limit=20)
    
    # בניית הודעה
    message_lines = [
        "📋 <b>התזכורות שלך</b>\n",
        f"📊 סטטיסטיקה:",
        f"   • ממתינות: {stats.get('pending', 0)}",
        f"   • הושלמו: {stats.get('completed', 0)}",
        f"   • באיחור: {stats.get('overdue', 0)}\n"
    ]
    
    if reminders:
        message_lines.append("⏰ <b>תזכורות קרובות:</b>\n")
        
        now = datetime.now(timezone.utc)
        
        for idx, rem in enumerate(reminders[:10], 1):
            title = rem["title"]
            remind_at = rem["remind_at"]
            file_name = rem.get("file_name")
            priority = rem.get("priority", "medium")
            
            # זמן יחסי
            time_diff = remind_at - now
            if time_diff.total_seconds() < 0:
                time_str = "⚠️ באיחור!"
            elif time_diff.days > 0:
                time_str = f"בעוד {time_diff.days}ד׳"
            else:
                hours = int(time_diff.total_seconds() / 3600)
                if hours > 0:
                    time_str = f"בעוד {hours}ש׳"
                else:
                    minutes = int(time_diff.total_seconds() / 60)
                    time_str = f"בעוד {minutes}ד׳"
            
            priority_icon = PRIORITY_ICONS.get(priority, "⚪")
            
            line = f"{idx}. {priority_icon} <b>{title}</b>"
            if file_name:
                line += f"\n   📄 <code>{file_name}</code>"
            line += f"\n   ⏰ {time_str}"
            
            message_lines.append(line)
        
        if len(reminders) > 10:
            message_lines.append(f"\n➕ ועוד {len(reminders) - 10} תזכורות...")
    
    message = "\n".join(message_lines)
    
    # כפתורים
    keyboard = [
        [
            InlineKeyboardButton("✅ הושלמו", callback_data="reminders_completed"),
            InlineKeyboardButton("📊 סטטיסטיקה", callback_data="reminders_stats")
        ]
    ]
    
    # כפתורים לתזכורות (עד 4)
    rem_buttons = []
    for rem in reminders[:4]:
        rem_id = rem["reminder_id"]
        title_short = rem["title"][:20]
        rem_buttons.append(
            InlineKeyboardButton(
                f"📌 {title_short}",
                callback_data=f"show_rem_{rem_id}"
            )
        )
    
    for i in range(0, len(rem_buttons), 2):
        keyboard.append(rem_buttons[i:i+2])
    
    await update.message.reply_text(
        message,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def reminder_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מטפל בלחיצות על כפתורים"""
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data.startswith("show_rem_"):
        # הצגת תזכורת
        reminder_id = data.replace("show_rem_", "")
        reminders = db.get_user_reminders(user_id)
        
        reminder = next((r for r in reminders if r["reminder_id"] == reminder_id), None)
        if not reminder:
            await query.edit_message_text("❌ תזכורת לא נמצאה")
            return
        
        title = reminder["title"]
        description = reminder.get("description", "")
        file_name = reminder.get("file_name")
        remind_at = reminder["remind_at"]
        priority = reminder.get("priority", "medium")
        
        priority_icon = PRIORITY_ICONS.get(priority, "⚪")
        
        message = (
            f"{priority_icon} <b>{title}</b>\n\n"
        )
        
        if description:
            message += f"📝 {description}\n\n"
        
        if file_name:
            message += f"📄 קובץ: <code>{file_name}</code>\n"
        
        message += f"⏰ תזכורת: {remind_at.strftime('%d/%m/%Y %H:%M')}\n"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ סיימתי", callback_data=f"rem_complete_{reminder_id}"),
                InlineKeyboardButton("⏰ דחה שעה", callback_data=f"rem_snooze_{reminder_id}")
            ],
            [
                InlineKeyboardButton("🗑️ מחק", callback_data=f"rem_del_{reminder_id}"),
                InlineKeyboardButton("🔙 חזור", callback_data="reminders_list")
            ]
        ]
        
        await query.edit_message_text(
            message,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data.startswith("rem_complete_"):
        reminder_id = data.replace("rem_complete_", "")
        
        if db.complete_reminder(user_id, reminder_id):
            await query.answer("✅ סומן כהושלם!", show_alert=True)
            await query.edit_message_text(
                "✅ <b>תזכורת הושלמה!</b>\n\n"
                "כל הכבוד! 🎉",
                parse_mode=ParseMode.HTML
            )
        else:
            await query.answer("❌ שגיאה", show_alert=True)
    
    elif data.startswith("rem_snooze_"):
        reminder_id = data.replace("rem_snooze_", "")
        
        # דחייה לשעה
        if db.snooze_reminder(user_id, reminder_id, snooze_minutes=60):
            await query.answer("⏰ נדחה לעוד שעה", show_alert=False)
            await query.edit_message_text(
                "⏰ <b>תזכורת נדחתה</b>\n\n"
                "אזכיר לך שוב בעוד שעה.",
                parse_mode=ParseMode.HTML
            )
        else:
            await query.answer("❌ שגיאה", show_alert=True)
    
    elif data.startswith("rem_del_"):
        reminder_id = data.replace("rem_del_", "")
        
        if db.delete_reminder(user_id, reminder_id):
            await query.answer("🗑️ נמחק", show_alert=False)
            await query.edit_message_text("🗑️ התזכורת נמחקה")
        else:
            await query.answer("❌ שגיאה", show_alert=True)
    
    elif data == "reminders_list":
        # חזרה לרשימה
        reminders = db.get_user_reminders(user_id, status="pending")
        
        if not reminders:
            await query.edit_message_text("💭 אין תזכורות ממתינות")
            return
        
        message_lines = ["📋 <b>תזכורות ממתינות</b>\n"]
        
        for rem in reminders[:10]:
            title = rem["title"]
            message_lines.append(f"📌 {title}")
        
        message = "\n".join(message_lines)
        
        await query.edit_message_text(message, parse_mode=ParseMode.HTML)


def setup_reminders_handlers(application):
    """רישום handlers"""
    application.add_handler(CommandHandler("remind", remind_start))
    application.add_handler(CommandHandler("reminders", reminders_list_command))
    application.add_handler(CallbackQueryHandler(
        reminder_callback_handler,
        pattern="^(show_rem_|rem_complete_|rem_snooze_|rem_del_|reminders_)"
    ))
```

---

### 4. תהליך רקע לשליחת תזכורות (reminder_scheduler.py)

```python
"""
תהליך רקע לשליחת תזכורות
"""

import asyncio
import logging
from datetime import datetime, timezone

from telegram import Bot
from telegram.error import TelegramError

from database import db
from config import config

logger = logging.getLogger(__name__)


async def send_reminder_notification(bot: Bot, reminder: dict):
    """שליחת הודעת תזכורת למשתמש"""
    try:
        user_id = reminder["user_id"]
        title = reminder["title"]
        description = reminder.get("description", "")
        file_name = reminder.get("file_name")
        reminder_id = reminder["reminder_id"]
        
        message = (
            "⏰ <b>תזכורת!</b>\n\n"
            f"📌 {title}\n"
        )
        
        if description:
            message += f"\n{description}\n"
        
        if file_name:
            message += f"\n📄 קובץ: <code>{file_name}</code>"
        
        # כפתורים
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        keyboard = [[
            InlineKeyboardButton("✅ סיימתי", callback_data=f"rem_complete_{reminder_id}"),
            InlineKeyboardButton("⏰ +1 שעה", callback_data=f"rem_snooze_{reminder_id}")
        ]]
        
        await bot.send_message(
            chat_id=user_id,
            text=message,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
        # סימון כנשלח
        db.mark_reminder_sent(reminder_id)
        
        logger.info(f"תזכורת {reminder_id} נשלחה למשתמש {user_id}")
        
    except TelegramError as e:
        logger.error(f"שגיאת Telegram בשליחת תזכורת: {e}")
    except Exception as e:
        logger.error(f"שגיאה בשליחת תזכורת: {e}")


async def reminder_scheduler_loop(bot: Bot):
    """לולאת תהליך הרקע"""
    logger.info("תהליך תזכורות התחיל")
    
    while True:
        try:
            # קבלת תזכורות שצריך לשלוח
            pending_reminders = db.get_pending_reminders()
            
            if pending_reminders:
                logger.info(f"נמצאו {len(pending_reminders)} תזכורות לשליחה")
                
                for reminder in pending_reminders:
                    await send_reminder_notification(bot, reminder)
                    # המתנה קצרה בין תזכורות
                    await asyncio.sleep(1)
            
            # בדיקה כל דקה
            await asyncio.sleep(60)
            
        except Exception as e:
            logger.error(f"שגיאה בלולאת תזכורות: {e}")
            await asyncio.sleep(60)


def start_reminder_scheduler(application):
    """הפעלת תהליך התזכורות"""
    bot = application.bot
    
    # הרצה בbackground
    asyncio.create_task(reminder_scheduler_loop(bot))
    logger.info("תהליך תזכורות הופעל")
```

---

### 5. שילוב ב-main.py

```python
from reminders_handler import setup_reminders_handlers
from reminder_scheduler import start_reminder_scheduler

# רישום handlers
setup_reminders_handlers(application)

# הפעלת תהליך רקע
application.job_queue.run_once(
    lambda context: start_reminder_scheduler(application),
    when=1
)
```

---

## 🎨 עיצוב UI/UX

```
משתמש: /remind api.py "לתקן bug בשורה 45" tomorrow 10:00

בוט:
✅ תזכורת נוצרה!

📌 לתקן bug בשורה 45
📄 קובץ: api.py
⏰ בעוד 1 יום

💡 /reminders לראות את כל התזכורות

[📋 כל התזכורות] [🗑️ מחק]

--- למחרת ב-10:00 ---

בוט:
⏰ תזכורת!

📌 לתקן bug בשורה 45

📄 קובץ: api.py

[✅ סיימתי] [⏰ +1 שעה]
```

---

## ✅ רשימת משימות

- [ ] מודל Reminder
- [ ] פונקציות DB
- [ ] Handler ליצירה
- [ ] Handler לרשימה
- [ ] תהליך רקע לשליחה
- [ ] פענוח זמנים
- [ ] דחיית תזכורות
- [ ] השלמת תזכורות
- [ ] סטטיסטיקות
- [ ] שילוב עם קבצים

---

**סיום מדריך Reminders** 📅
