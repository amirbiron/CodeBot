"""
פונקציות עזר כלליות לבוט שומר קבצי קוד
General Utility Functions for Code Keeper Bot
"""

import asyncio
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
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import aiofiles
import aiohttp
from telegram import Message, Update, User
from telegram.constants import ChatAction, ParseMode
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

class CodeErrorLogger:
    """מערכת לוגים ייעודית לשגיאות עיבוד קוד"""
    
    def __init__(self):
        self.logger = logging.getLogger('code_error_system')
        self._setup_logger()
    
    def _setup_logger(self):
        """הגדרת הלוגר עם קבצי יומן נפרדים"""
        if not self.logger.handlers:
            # לוגר לשגיאות כלליות
            error_handler = logging.FileHandler('code_errors.log', encoding='utf-8')
            error_handler.setLevel(logging.ERROR)
            error_formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            error_handler.setFormatter(error_formatter)
            
            # לוגר לסטטיסטיקות ופעילות
            activity_handler = logging.FileHandler('code_activity.log', encoding='utf-8')
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
            "timestamp": datetime.now().isoformat(),
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
            "timestamp": datetime.now().isoformat(),
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
        
        now = datetime.now()
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
            return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        
        elif date_str_lower in ['yesterday', 'אתמול']:
            return (datetime.now() - timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        
        elif date_str_lower in ['week', 'שבוע']:
            return datetime.now() - timedelta(weeks=1)
        
        elif date_str_lower in ['month', 'חודש']:
            return datetime.now() - timedelta(days=30)
        
        return None
    
    @staticmethod
    def get_time_ranges(period: str) -> Tuple[datetime, datetime]:
        """קבלת טווח זמנים לפי תקופה"""
        
        now = datetime.now()
        
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
            # Markdown V2
            escape_chars = r'_*[]()~`>#+-=|{}.!'
            return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)
        else:
            # Markdown V1
            escape_chars = r'_*`['
            return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)
    
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
