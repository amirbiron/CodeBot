"""
פונקציות עזר כלליות לבוט שומר קבצי קוד
General Utility Functions for Code Keeper Bot
"""

import asyncio
import unicodedata
import hashlib
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
import telegram.error

try:
    import aiofiles  # type: ignore
except Exception:  # optional for tests
    aiofiles = None  # type: ignore[assignment]
try:
    import aiohttp  # type: ignore
except Exception:  # optional for tests
    aiohttp = None  # type: ignore[assignment]
try:
    from telegram import Message, Update, User  # type: ignore
    from telegram.constants import ChatAction, ParseMode  # type: ignore
    from telegram.ext import ContextTypes  # type: ignore
except Exception:  # lightweight stubs for test env
    class Message:  # type: ignore[no-redef]
        pass
    class Update:  # type: ignore[no-redef]
        pass
    class User:  # type: ignore[no-redef]
        pass
    ChatAction = None  # type: ignore[assignment]
    ParseMode = None  # type: ignore[assignment]
    class _ContextTypes:
        DEFAULT_TYPE = object
    ContextTypes = _ContextTypes  # type: ignore[assignment]

logger = logging.getLogger(__name__)

class CodeErrorLogger:
    """מערכת לוגים ייעודית לשגיאות עיבוד קוד"""
    
    def __init__(self):
        self.logger = logging.getLogger('code_error_system')
        self._setup_logger()
    
    def _setup_logger(self):
        """הגדרת הלוגר עם קבצי יומן נפרדים"""
        if not self.logger.handlers:
            # לוגר לשגיאות כלליות - שימוש ב-StreamHandler לסביבת פרודקשן
            error_handler = logging.StreamHandler()
            error_handler.setLevel(logging.ERROR)
            error_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            error_handler.setFormatter(error_formatter)
            
            # לוגר לסטטיסטיקות ופעילות - שימוש ב-StreamHandler לסביבת פרודקשן
            activity_handler = logging.StreamHandler()
            activity_handler.setLevel(logging.INFO)
            activity_formatter = logging.Formatter(
                '%(asctime)s - %(levelname)s - %(message)s'
            )
            activity_handler.setFormatter(activity_formatter)
            
            self.logger.addHandler(error_handler)
            self.logger.addHandler(activity_handler)
            self.logger.setLevel(logging.INFO)
    
    def log_code_processing_error(self, user_id: int, error_type: str, error_message: str, 
                                context: Dict[str, Any] = None):
        """רישום שגיאות עיבוד קוד"""
        context = context or {}
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "error_type": error_type,
            "message": error_message,
            "context": context
        }
        
        self.logger.error(f"CODE_ERROR: {json.dumps(log_entry, ensure_ascii=False)}")
    
    def log_code_activity(self, user_id: int, activity_type: str, details: Dict[str, Any] = None):
        """רישום פעילות עיבוד קוד"""
        details = details or {}
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "user_id": user_id,
            "activity": activity_type,
            "details": details
        }
        
        self.logger.info(f"CODE_ACTIVITY: {json.dumps(log_entry, ensure_ascii=False)}")
    
    def log_validation_failure(self, user_id: int, code_length: int, error_reason: str):
        """רישום כשל באימות קוד"""
        self.log_code_processing_error(
            user_id, 
            "validation_failure", 
            error_reason,
            {"code_length": code_length}
        )
    
    def log_sanitization_success(self, user_id: int, original_length: int, cleaned_length: int):
        """רישום הצלחה בסניטציה"""
        self.log_code_activity(
            user_id,
            "code_sanitized",
            {
                "original_length": original_length,
                "cleaned_length": cleaned_length,
                "reduction": original_length - cleaned_length
            }
        )

# יצירת אינסטנס גלובלי של הלוגר
code_error_logger = CodeErrorLogger()

class TimeUtils:
    """כלים לעבודה עם זמן ותאריכים"""
    
    @staticmethod
    def format_relative_time(dt: datetime) -> str:
        """פורמט זמן יחסי (לפני 5 דקות, אתמול וכו')"""
        
        now = datetime.now(timezone.utc) if dt.tzinfo else datetime.now()
        diff = now - dt
        
        if diff.days > 365:
            years = diff.days // 365
            return f"לפני {years} שנ{'ה' if years == 1 else 'ים'}"
        
        elif diff.days > 30:
            months = diff.days // 30
            return f"לפני {months} חוד{'ש' if months == 1 else 'שים'}"
        
        elif diff.days > 7:
            weeks = diff.days // 7
            return f"לפני {weeks} שבוע{'ות' if weeks > 1 else ''}"
        
        elif diff.days > 0:
            if diff.days == 1:
                return "אתמול"
            return f"לפני {diff.days} ימים"
        
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"לפני {hours} שע{'ה' if hours == 1 else 'ות'}"
        
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"לפני {minutes} דק{'ה' if minutes == 1 else 'ות'}"
        
        else:
            return "עכשיו"
    
    @staticmethod
    def parse_date_string(date_str: str) -> Optional[datetime]:
        """פרסור מחרוזת תאריך לאובייקט datetime"""
        
        formats = [
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d.%m.%Y",
            "%Y-%m-%d %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%Y-%m-%dT%H:%M:%S"
        ]
        
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue
        
        # ניסיון לפרסור יחסי
        date_str_lower = date_str.lower()
        
        if date_str_lower in ['today', 'היום']:
            return datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        
        elif date_str_lower in ['yesterday', 'אתמול']:
            return (datetime.now(timezone.utc) - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        elif date_str_lower in ['week', 'שבוע']:
            return datetime.now(timezone.utc) - timedelta(weeks=1)
        
        elif date_str_lower in ['month', 'חודש']:
            return datetime.now(timezone.utc) - timedelta(days=30)
        
        return None
    
    @staticmethod
    def get_time_ranges(period: str) -> Tuple[datetime, datetime]:
        """קבלת טווח זמנים לפי תקופה"""
        
        now = datetime.now(timezone.utc)
        
        if period == 'today':
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)
        
        elif period == 'week':
            start = now - timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(weeks=1)
        
        elif period == 'month':
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            if start.month == 12:
                end = start.replace(year=start.year + 1, month=1)
            else:
                end = start.replace(month=start.month + 1)
        
        elif period == 'year':
            start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            end = start.replace(year=start.year + 1)
        
        else:
            # ברירת מחדל - יום אחרון
            start = now - timedelta(days=1)
            end = now
        
        return start, end

class TextUtils:
    """כלים לעבודה עם טקסט"""
    
    @staticmethod
    def truncate_text(text: str, max_length: int = 100, suffix: str = "...") -> str:
        """קיצור טקסט עם סיומת"""
        
        if len(text) <= max_length:
            return text
        
        return text[:max_length - len(suffix)] + suffix
    
    @staticmethod
    def escape_markdown(text: str, version: int = 2) -> str:
        """הגנה על תווים מיוחדים ב-Markdown"""
        
        if version == 2:
            # Markdown V2: כל התווים שיש לאסקייפ לפי Telegram MarkdownV2
            special_chars = set("_*[]()~`>#+-=|{}.!\\")
            return "".join(("\\" + ch) if ch in special_chars else ch for ch in text)
        else:
            # Markdown V1: נשתמש בקבוצה מצומצמת אך גם נסמן סוגריים כדי להימנע מתקלות כלליות
            special_chars = set("_*`[()\\")
            return "".join(("\\" + ch) if ch in special_chars else ch for ch in text)
    
    @staticmethod
    def clean_filename(filename: str) -> str:
        """ניקוי שם קובץ מתווים לא חוקיים"""
        
        # הסרת תווים לא חוקיים
        cleaned = re.sub(r'[<>:"/\\|?*]', '_', filename)
        
        # הסרת רווחים מיותרים
        cleaned = re.sub(r'\s+', '_', cleaned)
        
        # הסרת נקודות מיותרות
        cleaned = re.sub(r'\.+', '.', cleaned)
        
        # הגבלת אורך
        if len(cleaned) > 100:
            name, ext = os.path.splitext(cleaned)
            cleaned = name[:100-len(ext)] + ext
        
        return cleaned.strip('._')
    
    @staticmethod
    def extract_hashtags(text: str) -> List[str]:
        """חילוץ תגיות מטקסט"""
        
        return re.findall(r'#(\w+)', text)
    
    @staticmethod
    def highlight_text(text: str, query: str, tag: str = "**") -> str:
        """הדגשת מילות חיפוש בטקסט"""
        
        if not query:
            return text
        
        # הדגשה בלי תלות ברישיות
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        return pattern.sub(f"{tag}\\g<0>{tag}", text)
    
    @staticmethod
    def format_file_size(size_bytes: int) -> str:
        """פורמט גודל קובץ (bytes -> KB/MB/GB)"""
        
        if size_bytes < 1024:
            return f"{size_bytes} B"
        
        elif size_bytes < 1024 ** 2:
            return f"{size_bytes / 1024:.1f} KB"
        
        elif size_bytes < 1024 ** 3:
            return f"{size_bytes / (1024 ** 2):.1f} MB"
        
        else:
            return f"{size_bytes / (1024 ** 3):.1f} GB"
    
    @staticmethod
    def pluralize_hebrew(count: int, singular: str, plural: str) -> str:
        """צורת רבים עבריות"""
        
        if count == 1:
            return f"{count} {singular}"
        elif count == 2:
            return f"2 {plural}"
        else:
            return f"{count} {plural}"

class SecurityUtils:
    """כלים אמינות ובטיחות"""
    
    @staticmethod
    def generate_secure_token(length: int = 32) -> str:
        """יצירת טוקן מאובטח"""
        return secrets.token_urlsafe(length)
    
    @staticmethod
    def hash_content(content: str, algorithm: str = 'sha256') -> str:
        """יצירת hash לתוכן"""
        
        if algorithm == 'md5':
            return hashlib.md5(content.encode()).hexdigest()
        elif algorithm == 'sha1':
            return hashlib.sha1(content.encode()).hexdigest()
        elif algorithm == 'sha256':
            return hashlib.sha256(content.encode()).hexdigest()
        else:
            raise ValueError(f"אלגוריתם לא נתמך: {algorithm}")
    
    @staticmethod
    def validate_user_input(text: str, max_length: int = 10000, 
                           forbidden_patterns: List[str] = None) -> bool:
        """בדיקת קלט משתמש"""
        
        if len(text) > max_length:
            return False
        
        if forbidden_patterns:
            for pattern in forbidden_patterns:
                if re.search(pattern, text, re.IGNORECASE):
                    return False
        
        return True
    
    @staticmethod
    def sanitize_code(code: str) -> str:
        """ניקוי קוד מתוכן מסוכן (בסיסי)"""
        
        # דפוסי קוד מסוכנים בסיסיים
        dangerous_patterns = [
            r'exec\s*\(',
            r'eval\s*\(',
            r'__import__\s*\(',
            r'open\s*\(',
            r'file\s*\(',
            r'input\s*\(',
            r'raw_input\s*\(',
        ]
        
        # החלפת דפוסים מסוכנים
        cleaned = code
        for pattern in dangerous_patterns:
            cleaned = re.sub(pattern, '[REMOVED]', cleaned, flags=re.IGNORECASE)
        
        return cleaned

class TelegramUtils:
    """כלים לעבודה עם Telegram"""
    
    @staticmethod
    async def send_typing_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """שליחת אקשן 'כותב...'"""
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.TYPING
        )
    
    @staticmethod
    async def send_document_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """שליחת אקשן 'שולח מסמך...'"""
        await context.bot.send_chat_action(
            chat_id=update.effective_chat.id,
            action=ChatAction.UPLOAD_DOCUMENT
        )

    @staticmethod
    async def safe_answer(query, text: Optional[str] = None, show_alert: bool = False, cache_time: Optional[int] = None) -> None:
        """מענה בטוח ל-CallbackQuery: מתעלם משגיאות 'Query is too old'/'query_id_invalid'."""
        try:
            kwargs = {}
            if text is not None:
                kwargs["text"] = text
            if show_alert:
                kwargs["show_alert"] = True
            if cache_time is not None:
                kwargs["cache_time"] = int(cache_time)
            await query.answer(**kwargs)
        except telegram.error.BadRequest as e:  # type: ignore[attr-defined]
            msg = str(e).lower()
            if "query is too old" in msg or "query_id_invalid" in msg or "message to edit not found" in msg:
                return
            raise
    
    @staticmethod
    def get_user_mention(user: User) -> str:
        """קבלת מנשן למשתמש"""
        
        if user.username:
            return f"@{user.username}"
        else:
            return f"[{user.first_name}](tg://user?id={user.id})"
    
    @staticmethod
    def split_long_message(text: str, max_length: int = 4096) -> List[str]:
        """חלוקת הודעה ארוכה לחלקים"""
        
        if len(text) <= max_length:
            return [text]
        
        parts = []
        current_part = ""
        
        for line in text.split('\n'):
            if len(current_part) + len(line) + 1 <= max_length:
                current_part += line + '\n'
            else:
                if current_part:
                    parts.append(current_part.rstrip())
                current_part = line + '\n'
        
        if current_part:
            parts.append(current_part.rstrip())
        
        return parts

    @staticmethod
    async def safe_edit_message_text(query, text: str, reply_markup=None, parse_mode: Optional[str] = None) -> None:
        """עריכת טקסט הודעה בבטיחות: מתעלם משגיאת 'Message is not modified'."""
        try:
            if parse_mode is None:
                await query.edit_message_text(text=text, reply_markup=reply_markup)
            else:
                await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except telegram.error.BadRequest as e:  # type: ignore[attr-defined]
            msg = str(e).lower()
            # התעלמות רק במקרה "not modified" (עמיד לשינויים קלים בטקסט)
            if "not modified" in msg:
                return
            raise
        except Exception as e:
            # רשת/ספריות שונות עלולות להשליך מחלקה אחרת אך עם אותו מסר
            msg = str(e).lower()
            if "not modified" in msg:
                return
            raise

    @staticmethod
    async def safe_edit_message_reply_markup(query, reply_markup=None) -> None:
        """עריכת מקלדת הודעה בבטיחות: מתעלם משגיאת 'Message is not modified'."""
        try:
            await query.edit_message_reply_markup(reply_markup=reply_markup)
        except telegram.error.BadRequest as e:  # type: ignore[attr-defined]
            msg = str(e).lower()
            if "not modified" in msg:
                return
            raise
        except Exception as e:
            msg = str(e).lower()
            if "not modified" in msg:
                return
            raise

    @staticmethod
    def extract_message_text_preserve_markdown(message: "Message", *, reconstruct_from_entities: bool = True) -> str:
        """
        שחזור טקסט ההודעה תוך ניסיון להחזיר את מה שהמשתמש התכוון מבחינת תווי Markdown.

        עקרונות:

        - ברירת מחדל: נשתמש ב-``text``/``caption`` (התוכן הגולמי כפי שנשלח לשרת לאחר עיבוד Markdown).
          זאת כדי לא לשמור מחרוזת "מרונדרת" (למשל ``*_name_*``), שאינה משקפת קלט משתמש.

        - במידה ו-``reconstruct_from_entities=True`` ויש ישויות עיצוב (``bold``/``italic``), ננסה לשחזר
          תווי Markdown שהיוו כנראה את מקור העיצוב ע"י הוספת תחיליות/סיומות סביב הטקסט שסומן.
          מיפוי פשוט: ``bold`` → ``"__"``, ``italic`` → ``"_"``. שאר ישויות נשמרות כפי שהן.

        - אם יש כיתוב (caption), נשתמש במקבילות ``caption_entities``.
        """
        # 1) תוכן בסיסי
        try:
            base = str(getattr(message, "text", "") or getattr(message, "caption", "") or "")
        except Exception:
            base = ""

        if not reconstruct_from_entities or not base:
            return base

        # 2) שחזור סימונים על בסיס entities (אם קיימים)
        try:
            entities = getattr(message, "entities", None)
            if base and not entities:
                entities = getattr(message, "caption_entities", None)
        except Exception:
            entities = None

        try:
            if not entities:
                return base

            length = len(base)
            opens = {i: [] for i in range(length + 1)}
            closes = {i: [] for i in range(length + 1)}

            for ent in entities or []:
                try:
                    etype = getattr(ent, "type", "") or ""
                    offset = int(getattr(ent, "offset", 0) or 0)
                    ent_len = int(getattr(ent, "length", 0) or 0)
                    start = max(0, min(length, offset))
                    end = max(0, min(length, offset + ent_len))
                except Exception:
                    continue

                # מיפוי לסימני Markdown מועדפים
                if etype == "bold":
                    opens[start].append("__")
                    closes[end].insert(0, "__")  # סגירה לפני פתיחות חדשות באותו אינדקס
                elif etype == "italic":
                    opens[start].append("_")
                    closes[end].insert(0, "_")
                else:
                    # עבור ישויות אחרות לא נוסיף תווים (inline code/links לא משוחזרים כסימנים)
                    continue

            out_parts = []
            for i, ch in enumerate(base):
                # הוסף סגירות שמסתיימות לפני התו
                if closes.get(i):
                    out_parts.extend(closes[i])
                # הוסף פתיחות שמתחילות לפני התו
                if opens.get(i):
                    out_parts.extend(opens[i])
                out_parts.append(ch)

            # סגירות בסוף הטקסט
            if closes.get(length):
                out_parts.extend(closes[length])

            return "".join(out_parts)
        except Exception:
            return base

class CallbackQueryGuard:
    """Guard גורף ללחיצות כפולות על כפתורי CallbackQuery.

    מבוסס על טביעת אצבע של המשתמש/הודעה/הנתון (callback_data) כדי לחסום
    את אותה פעולה בחלון זמן קצר, בלי לחסום פעולות שונות.
    """

    DEFAULT_WINDOW_SECONDS: float = 1.2
    # נעילות פר-משתמש כדי למנוע מרוץ בין לחיצות מקבילות של אותו משתמש
    _user_locks: Dict[int, asyncio.Lock] = {}

    @staticmethod
    def _fingerprint(update: Update) -> str:
        try:
            q = getattr(update, "callback_query", None)
            user_id = int(getattr(update.effective_user, "id", 0) or 0)
            chat_id = int(getattr(update.effective_chat, "id", 0) or 0)
            msg_id = int(getattr(getattr(q, "message", None), "message_id", 0) or 0)
            data = str(getattr(q, "data", "") or "")
            return f"{user_id}:{chat_id}:{msg_id}:{data}"
        except Exception:
            return "unknown"

    @staticmethod
    def should_block(update: Update, context: ContextTypes.DEFAULT_TYPE, window_seconds: Optional[float] = None) -> bool:
        """בודק האם יש לחסום את העדכון כלחיצה כפולה.

        אם זו אותה טביעת אצבע בתוך חלון הזמן – נחסום; אחרת נסמן ונאפשר.
        """
        try:
            win = float(window_seconds if window_seconds is not None else CallbackQueryGuard.DEFAULT_WINDOW_SECONDS)
        except Exception:
            win = CallbackQueryGuard.DEFAULT_WINDOW_SECONDS

        try:
            fp = CallbackQueryGuard._fingerprint(update)
            now_ts = time.time()
            last_fp = context.user_data.get("_last_cb_fp") if hasattr(context, "user_data") else None
            busy_until = float(context.user_data.get("_cb_guard_until", 0.0) or 0.0) if hasattr(context, "user_data") else 0.0

            if last_fp == fp and now_ts < busy_until:
                return True

            # סמנו את הפעולה הנוכחית לחלון קצר
            if hasattr(context, "user_data"):
                context.user_data["_last_cb_fp"] = fp
                context.user_data["_cb_guard_until"] = now_ts + win
            return False
        except Exception:
            # אל תחסום אם guard נכשל
            return False

    @staticmethod
    async def should_block_async(update: Update, context: ContextTypes.DEFAULT_TYPE, window_seconds: Optional[float] = None) -> bool:
        """בודק בצורה אטומית (עם נעילה) אם לחסום לחיצה כפולה של אותו משתמש.

        חסימה מבוססת חלון זמן פר-משתמש, ללא תלות ב-message_id/data, כדי למנוע מרוץ.
        """
        try:
            try:
                win = float(window_seconds if window_seconds is not None else CallbackQueryGuard.DEFAULT_WINDOW_SECONDS)
            except Exception:
                win = CallbackQueryGuard.DEFAULT_WINDOW_SECONDS

            user_id = int(getattr(getattr(update, 'effective_user', None), 'id', 0) or 0)

            # אם אין זיהוי משתמש, fallback להתנהגות הישנה ללא חסימה
            if user_id <= 0:
                return CallbackQueryGuard.should_block(update, context, window_seconds=win)

            # קבל/צור נעילה למשתמש
            lock = CallbackQueryGuard._user_locks.get(user_id)
            if lock is None:
                lock = asyncio.Lock()
                CallbackQueryGuard._user_locks[user_id] = lock

            async with lock:
                now_ts = time.time()
                # השתמש באותו שדה זמן גלובלי שהיה בשימוש, אך ללא טביעת אצבע
                busy_until = float(context.user_data.get("_cb_guard_until", 0.0) or 0.0) if hasattr(context, "user_data") else 0.0
                if now_ts < busy_until:
                    return True
                # סמנו חלון זמן חסימה חדש
                if hasattr(context, "user_data"):
                    context.user_data["_cb_guard_until"] = now_ts + win
                return False
        except Exception:
            # אל תחסום אם guard נכשל
            return False

class AsyncUtils:
    """כלים לעבודה אסינכרונית"""
    
    @staticmethod
    async def run_with_timeout(coro, timeout: float = 30.0):
        """הרצת פונקציה אסינכרונית עם timeout"""
        
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning(f"פעולה הופסקה עקב timeout ({timeout}s)")
            return None
    
    @staticmethod
    async def batch_process(items: List[Any], process_func: Callable, 
                           batch_size: int = 10, delay: float = 0.1) -> List[Any]:
        """עיבוד פריטים בקבוצות"""
        
        results = []
        
        for i in range(0, len(items), batch_size):
            batch = items[i:i + batch_size]
            
            # עיבוד הקבוצה
            batch_tasks = [process_func(item) for item in batch]
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            
            results.extend(batch_results)
            
            # המתנה בין קבוצות
            if delay > 0 and i + batch_size < len(items):
                await asyncio.sleep(delay)
        
        return results

class PerformanceUtils:
    """כלים למדידת ביצועים"""
    
    @staticmethod
    def timing_decorator(func):
        """דקורטור למדידת זמן ביצוע"""
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                execution_time = time.time() - start_time
                logger.info(f"{func.__name__} הסתיים תוך {execution_time:.3f}s")
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"{func.__name__} נכשל תוך {execution_time:.3f}s: {e}")
                raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                execution_time = time.time() - start_time
                logger.info(f"{func.__name__} הסתיים תוך {execution_time:.3f}s")
                return result
            except Exception as e:
                execution_time = time.time() - start_time
                logger.error(f"{func.__name__} נכשל תוך {execution_time:.3f}s: {e}")
                raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    @staticmethod
    @contextmanager
    def measure_time(operation_name: str):
        """מדידת זמן עם context manager"""
        
        start_time = time.time()
        try:
            yield
        finally:
            execution_time = time.time() - start_time
            logger.info(f"{operation_name}: {execution_time:.3f}s")

class ValidationUtils:
    """כלים לוולידציה"""
    
    @staticmethod
    def is_valid_filename(filename: str) -> bool:
        """בדיקת תקינות שם קובץ"""
        
        if not filename or len(filename) > 255:
            return False
        
        # תווים לא חוקיים
        invalid_chars = '<>:"/\\|?*'
        if any(char in filename for char in invalid_chars):
            return False
        
        # שמות שמורים ב-Windows
        reserved_names = [
            'CON', 'PRN', 'AUX', 'NUL',
            'COM1', 'COM2', 'COM3', 'COM4', 'COM5', 'COM6', 'COM7', 'COM8', 'COM9',
            'LPT1', 'LPT2', 'LPT3', 'LPT4', 'LPT5', 'LPT6', 'LPT7', 'LPT8', 'LPT9'
        ]
        
        name_without_ext = os.path.splitext(filename)[0].upper()
        if name_without_ext in reserved_names:
            return False
        
        return True
    
    @staticmethod
    def is_safe_code(code: str, programming_language: str) -> Tuple[bool, List[str]]:
        """בדיקה בסיסית של בטיחות קוד"""
        
        warnings = []
        
        # דפוסים מסוכנים
        dangerous_patterns = {
            'python': [
                r'exec\s*\(',
                r'eval\s*\(',
                r'__import__\s*\(',
                r'open\s*\([^)]*["\']w',  # כתיבה לקובץ
                r'subprocess\.',
                r'os\.system\s*\(',
                r'os\.popen\s*\(',
            ],
            'javascript': [
                r'eval\s*\(',
                r'Function\s*\(',
                r'document\.write\s*\(',
                r'innerHTML\s*=',
                r'outerHTML\s*=',
            ],
            'bash': [
                r'rm\s+-rf',
                r'rm\s+/',
                r'dd\s+if=',
                r'mkfs\.',
                r'fdisk\s+',
            ]
        }
        
        if programming_language in dangerous_patterns:
            for pattern in dangerous_patterns[programming_language]:
                if re.search(pattern, code, re.IGNORECASE):
                    warnings.append(f"דפוס מסוכן אפשרי: {pattern}")
        
        # בדיקות כלליות
        if 'password' in code.lower() or 'secret' in code.lower():
            warnings.append("הקוד מכיל מילות סיסמה או סוד")
        
        if re.search(r'https?://\S+', code):
            warnings.append("הקוד מכיל URLים")
        
        is_safe = len(warnings) == 0
        return is_safe, warnings

class FileUtils:
    """כלים לעבודה עם קבצים"""
    
    @staticmethod
    async def download_file(url: str, max_size: int = 10 * 1024 * 1024) -> Optional[bytes]:
        """הורדת קובץ מ-URL"""
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        logger.error(f"שגיאה בהורדת קובץ: {response.status}")
                        return None
                    
                    # בדיקת גודל
                    content_length = response.headers.get('content-length')
                    if content_length and int(content_length) > max_size:
                        logger.error(f"קובץ גדול מדי: {content_length} bytes")
                        return None
                    
                    # הורדת התוכן
                    content = b""
                    async for chunk in response.content.iter_chunked(8192):
                        content += chunk
                        if len(content) > max_size:
                            logger.error("קובץ גדול מדי")
                            return None
                    
                    return content
        
        except Exception as e:
            logger.error(f"שגיאה בהורדת קובץ: {e}")
            return None
    
    @staticmethod
    def get_file_extension(filename: str) -> str:
        """קבלת סיומת קובץ"""
        return os.path.splitext(filename)[1].lower()
    
    @staticmethod
    def get_mime_type(filename: str) -> str:
        """קבלת MIME type של קובץ"""
        mime_type, _ = mimetypes.guess_type(filename)
        return mime_type or 'application/octet-stream'
    
    @staticmethod
    async def create_temp_file(content: Union[str, bytes], 
                              suffix: str = "") -> str:
        """יצירת קובץ זמני"""
        
        with tempfile.NamedTemporaryFile(mode='wb', suffix=suffix, delete=False) as temp_file:
            if isinstance(content, str):
                content = content.encode('utf-8')
            
            temp_file.write(content)
            return temp_file.name

class ConfigUtils:
    """כלים לקונפיגורציה"""
    
    @staticmethod
    def load_json_config(file_path: str, default: Dict = None) -> Dict:
        """טעינת קונפיגורציה מקובץ JSON"""
        
        if default is None:
            default = {}
        
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            else:
                logger.warning(f"קובץ קונפיגורציה לא נמצא: {file_path}")
                return default
        
        except Exception as e:
            logger.error(f"שגיאה בטעינת קונפיגורציה: {e}")
            return default
    
    @staticmethod
    def save_json_config(file_path: str, config: Dict) -> bool:
        """שמירת קונפיגורציה לקובץ JSON"""
        
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            
            return True
        
        except Exception as e:
            logger.error(f"שגיאה בשמירת קונפיגורציה: {e}")
            return False

class CacheUtils:
    """כלים לקאש זמני"""
    
    _cache = {}
    _cache_times = {}
    
    @classmethod
    def set(cls, key: str, value: Any, ttl: int = 300):
        """שמירה בקאש עם TTL (שניות)"""
        cls._cache[key] = value
        cls._cache_times[key] = time.time() + ttl
    
    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """קבלה מהקאש"""
        
        if key not in cls._cache:
            return default
        
        # בדיקת תפוגה
        if time.time() > cls._cache_times.get(key, 0):
            cls.delete(key)
            return default
        
        return cls._cache[key]
    
    @classmethod
    def delete(cls, key: str):
        """מחיקה מהקאש"""
        cls._cache.pop(key, None)
        cls._cache_times.pop(key, None)
    
    @classmethod
    def clear(cls):
        """ניקוי כל הקאש"""
        cls._cache.clear()
        cls._cache_times.clear()

# פונקציות עזר גלובליות
def get_memory_usage() -> Dict[str, float]:
    """קבלת נתוני זיכרון"""
    try:
        import psutil
        process = psutil.Process()
        memory_info = process.memory_info()
        
        return {
            "rss_mb": memory_info.rss / 1024 / 1024,
            "vms_mb": memory_info.vms / 1024 / 1024,
            "percent": process.memory_percent()
        }
    except ImportError:
        return {"error": "psutil לא מותקן"}

def setup_logging(level: str = "INFO", log_file: str = None) -> logging.Logger:
    """הגדרת לוגים"""
    
    # הגדרת רמת לוג
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # הגדרת פורמט
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # הגדרת handlers
    handlers = [logging.StreamHandler(sys.stdout)]
    
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)
    
    # קונפיגורציה
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    
    return logging.getLogger(__name__)

def generate_summary_stats(files_data: List[Dict]) -> Dict[str, Any]:
    """יצירת סיכום סטטיסטיקות"""
    
    if not files_data:
        return {}
    
    total_files = len(files_data)
    total_size = sum(len(f.get('code', '')) for f in files_data)
    
    languages = [f.get('language', 'unknown') for f in files_data]
    language_counts = {lang: languages.count(lang) for lang in set(languages)}
    
    all_tags = []
    for f in files_data:
        all_tags.extend(f.get('tags', []))
    
    tag_counts = {tag: all_tags.count(tag) for tag in set(all_tags)}
    
    return {
        "total_files": total_files,
        "total_size": total_size,
        "total_size_formatted": TextUtils.format_file_size(total_size),
        "languages": language_counts,
        "most_used_language": max(language_counts, key=language_counts.get) if language_counts else None,
        "tags": tag_counts,
        "most_used_tag": max(tag_counts, key=tag_counts.get) if tag_counts else None,
        "average_file_size": total_size // total_files if total_files > 0 else 0
    }

def detect_language_from_filename(filename: str) -> str:
    """זיהוי שפת תכנות לפי סיומת הקובץ"""
    # מיפוי סיומות לשפות
    extensions_map = {
        # Python
        '.py': 'python',
        '.pyw': 'python',
        '.pyx': 'python',
        '.pyi': 'python',
        
        # JavaScript/TypeScript
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.mjs': 'javascript',
        
        # Web
        '.html': 'html',
        '.htm': 'html',
        '.css': 'css',
        '.scss': 'scss',
        '.sass': 'sass',
        '.less': 'less',
        
        # Java/Kotlin
        '.java': 'java',
        '.kt': 'kotlin',
        '.kts': 'kotlin',
        
        # C/C++
        '.c': 'c',
        '.h': 'c',
        '.cpp': 'cpp',
        '.cc': 'cpp',
        '.cxx': 'cpp',
        '.hpp': 'cpp',
        '.hxx': 'cpp',
        
        # C#
        '.cs': 'csharp',
        
        # Go
        '.go': 'go',
        
        # Rust
        '.rs': 'rust',
        
        # Ruby
        '.rb': 'ruby',
        '.rake': 'ruby',
        
        # PHP
        '.php': 'php',
        '.phtml': 'php',
        
        # Swift
        '.swift': 'swift',
        
        # Shell
        '.sh': 'bash',
        '.bash': 'bash',
        '.zsh': 'bash',
        '.fish': 'bash',
        
        # SQL
        '.sql': 'sql',
        
        # JSON/YAML/XML
        '.json': 'json',
        '.yaml': 'yaml',
        '.yml': 'yaml',
        '.xml': 'xml',
        
        # Markdown
        '.md': 'markdown',
        '.markdown': 'markdown',
        
        # Other
        '.r': 'r',
        '.lua': 'lua',
        '.vim': 'vim',
        '.dockerfile': 'dockerfile',
        'Dockerfile': 'dockerfile',
        '.makefile': 'makefile',
        'Makefile': 'makefile',
        '.cmake': 'cmake',
        '.gradle': 'gradle',
        '.properties': 'properties',
        '.ini': 'ini',
        '.toml': 'toml',
        '.env': 'env',
        '.gitignore': 'gitignore',
        '.dockerignore': 'dockerignore'
    }
    
    # בדיקת סיומת
    filename_lower = filename.lower()
    for ext, lang in extensions_map.items():
        if filename_lower.endswith(ext.lower()) or filename_lower == ext.lower():
            return lang
    
    # אם לא נמצאה התאמה, נחזיר 'text'
    return 'text'

def get_language_emoji(language: str) -> str:
    """מחזיר אימוג'י מתאים לשפת התכנות"""
    emoji_map = {
        'python': '🐍',
        'javascript': '🟨',
        'typescript': '🔷',
        'java': '☕',
        'kotlin': '🟣',
        'c': '🔵',
        'cpp': '🔷',
        'csharp': '🟦',
        'go': '🐹',
        'rust': '🦀',
        'ruby': '💎',
        'php': '🐘',
        'swift': '🦉',
        'bash': '🐚',
        'sql': '🗄️',
        'html': '🌐',
        'css': '🎨',
        'scss': '🎨',
        'sass': '🎨',
        'less': '🎨',
        'json': '📋',
        'yaml': '📄',
        'xml': '📰',
        'markdown': '📝',
        'r': '📊',
        'lua': '🌙',
        'vim': '📝',
        'dockerfile': '🐳',
        'makefile': '🔧',
        'cmake': '🔨',
        'gradle': '🐘',
        'properties': '⚙️',
        'ini': '⚙️',
        'toml': '⚙️',
        'env': '🔐',
        'gitignore': '🚫',
        'dockerignore': '🚫',
        'text': '📄'
    }
    
    return emoji_map.get(language.lower(), '📄')

class SensitiveDataFilter(logging.Filter):
    """מסנן שמטשטש טוקנים ונתונים רגישים בלוגים."""
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = str(record.getMessage())
            # זיהוי בסיסי של טוקנים: ghp_..., github_pat_..., Bearer ...
            patterns = [
                (r"ghp_[A-Za-z0-9]{20,}", "ghp_***REDACTED***"),
                (r"github_pat_[A-Za-z0-9_]{20,}", "github_pat_***REDACTED***"),
                (r"Bearer\s+[A-Za-z0-9\-_.=:/+]{10,}", "Bearer ***REDACTED***"),
            ]
            redacted = msg
            import re as _re
            for pat, repl in patterns:
                redacted = _re.sub(pat, repl, redacted)
            # עדכן רק את message הפורמטי
            record.msg = redacted
            # חשוב: נקה ארגומנטים כדי למנוע ניסיון פורמט חוזר (%s) שיוביל ל-TypeError
            record.args = ()
        except Exception:
            pass
        return True


def install_sensitive_filter():
    """התקנת המסנן על כל ה-handlers הקיימים."""
    root = logging.getLogger()
    f = SensitiveDataFilter()
    for h in root.handlers:
        h.addFilter(f)


# --- Code normalization ---
def normalize_code(text: str,
                   *,
                   strip_bom: bool = True,
                   normalize_newlines: bool = True,
                   replace_nbsp: bool = True,
                   replace_all_space_separators: bool = True,
                   remove_zero_width: bool = True,
                   remove_directional_marks: bool = True,
                   trim_trailing_whitespace: bool = True,
                   remove_other_format_chars: bool = True,
                   remove_escaped_format_escapes: bool = True,
                   remove_variation_selectors: bool = False) -> str:
    """נרמול קוד לפני שמירה.

    פעולות עיקריות:

    - הסרת BOM בתחילת הטקסט
    - המרת CRLF/CR ל-LF
    - החלפת רווחים לא-שוברים (NBSP/NNBSP) לרווח רגיל
    - הסרת תווי רוחב-אפס וסימוני כיוון (LRM/RLM/LRE/RLE/PDF/RLO/LRO/LRI/RLI/FSI/PDI)
    - הסרת תווי בקרה (Cc) פרט ל-\\t, \\n, \\r
    - הסרת רווחי סוף שורה
    """
    try:
        if not isinstance(text, str):
            return text if text is not None else ""

        out = text

        # Handle sequences like "\u200B" that represent hidden/format chars literally
        # We do NOT decode arbitrary escapes; only strip escapes that would decode to Cf/hidden sets
        if remove_escaped_format_escapes and ("\\u" in out or "\\U" in out):
            try:
                import re as _re
                # Known hidden/format codepoints we target explicitly
                known_hex4 = {
                    "200B", "200C", "200D", "2060", "FEFF",  # zero-width set
                    "200E", "200F", "202A", "202B", "202C", "202D", "202E",  # directional
                    "2066", "2067", "2068", "2069",  # directional isolates
                }

                def _strip_if_hidden(m: 're.Match[str]') -> str:
                    hexcode = m.group(1).upper()
                    # Quick allowlist: only remove if in known set or Unicode category Cf
                    if hexcode in known_hex4:
                        return ""
                    try:
                        ch = chr(int(hexcode, 16))
                        cat = unicodedata.category(ch)
                        if cat == 'Cf':
                            return ""
                        # Remove Unicode Variation Selectors (U+FE00..U+FE0F)
                        if remove_variation_selectors:
                            v = int(hexcode, 16)
                            if 0xFE00 <= v <= 0xFE0F:
                                return ""
                    except Exception:
                        pass
                    return m.group(0)  # keep original escape

                # Replace \uXXXX sequences
                out = _re.sub(r"\\u([0-9a-fA-F]{4})", _strip_if_hidden, out)

                # Replace \UXXXXXXXX sequences (rare for these marks, but safe)
                def _strip_if_hidden_u8(m: 're.Match[str]') -> str:
                    hexcode = m.group(1).upper()
                    try:
                        ch = chr(int(hexcode, 16))
                        if unicodedata.category(ch) == 'Cf':
                            return ""
                        # Remove Ideographic Variation Selectors (U+E0100..U+E01EF)
                        if remove_variation_selectors:
                            v = int(hexcode, 16)
                            if 0xE0100 <= v <= 0xE01EF:
                                return ""
                    except Exception:
                        pass
                    return m.group(0)

                out = _re.sub(r"\\U([0-9a-fA-F]{8})", _strip_if_hidden_u8, out)
            except Exception:
                # Best-effort: ignore on failure
                pass

        # Strip BOM at start
        if strip_bom and out.startswith("\ufeff"):
            out = out.lstrip("\ufeff")

        # Normalize newlines to LF
        if normalize_newlines:
            out = out.replace("\r\n", "\n").replace("\r", "\n")

        # Replace non-breaking spaces with regular space
        if replace_nbsp:
            out = out.replace("\u00A0", " ").replace("\u202F", " ")

        # Replace all Unicode space separators (Zs) with regular ASCII space
        if replace_all_space_separators:
            try:
                out = "".join(" " if unicodedata.category(ch) == "Zs" else ch for ch in out)
            except Exception:
                # If classification fails, skip Zs replacement and keep current text
                pass

        # Remove zero-width and directional formatting characters
        if remove_zero_width or remove_directional_marks:
            zero_width = {
                "\u200B",  # ZWSP
                "\u200C",  # ZWNJ
                "\u200D",  # ZWJ
                "\u2060",  # WJ
                "\uFEFF",  # ZWNBSP/BOM
            }
            directional = {
                "\u200E",  # LRM
                "\u200F",  # RLM
                "\u202A",  # LRE
                "\u202B",  # RLE
                "\u202C",  # PDF
                "\u202D",  # LRO
                "\u202E",  # RLO
                "\u2066",  # LRI
                "\u2067",  # RLI
                "\u2068",  # FSI
                "\u2069",  # PDI
            }

            def _should_keep(ch: str) -> bool:
                # Keep tabs/newlines/carriage returns
                if ch in ("\t", "\n", "\r"):
                    return True
                # Drop specific sets
                if remove_zero_width and ch in zero_width:
                    return False
                if remove_directional_marks and ch in directional:
                    return False
                # Remove Variation Selectors if requested
                if remove_variation_selectors:
                    cp = ord(ch)
                    # VS1..VS16 (U+FE00..U+FE0F) and Ideographic VS (U+E0100..U+E01EF)
                    if (0xFE00 <= cp <= 0xFE0F) or (0xE0100 <= cp <= 0xE01EF):
                        return False
                # Drop other control chars (Cc), keep others
                cat = unicodedata.category(ch)
                if cat == 'Cc' and ch not in ("\t", "\n", "\r"):
                    return False
                # Optionally remove other format chars (Cf) beyond explicit sets
                if cat == 'Cf' and remove_other_format_chars:
                    return False
                return True

            out = "".join(ch for ch in out if _should_keep(ch))

        # Trim trailing whitespace for each line
        if trim_trailing_whitespace:
            out = "\n".join(line.rstrip(" \t") for line in out.split("\n"))

        return out
    except Exception:
        # במקרה של שגיאה, החזר את הטקסט המקורי
        return text
