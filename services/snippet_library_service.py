from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

try:
    from bson import ObjectId  # type: ignore
except Exception:  # pragma: no cover
    class ObjectId(str):  # minimal fallback for tests without bson
        pass

from database import db as _db

try:  # observability (fail-open)
    from observability import emit_event  # type: ignore
except Exception:  # pragma: no cover
    def emit_event(event: str, severity: str = "info", **fields):  # type: ignore
        return None


def _sanitize_text(s: Any, max_len: int) -> str:
    try:
        t = (s or "").strip()
    except Exception:
        t = ""
    if len(t) > max_len:
        t = t[:max_len]
    return t


def submit_snippet(
    *,
    title: str,
    description: str,
    code: str,
    language: str,
    user_id: int,
    username: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new pending snippet proposal with basic validation.

    Returns dict with ok/error and id when available.
    """
    title_s = _sanitize_text(title, 180)
    desc_s = _sanitize_text(description, 1000)
    lang_s = _sanitize_text(language, 40)
    if len(title_s) < 3:
        return {"ok": False, "error": "הכותרת חייבת להיות 3..180 תווים"}
    if len(desc_s) < 4:
        return {"ok": False, "error": "התיאור קצר מדי"}
    if not code or not str(code).strip():
        return {"ok": False, "error": "נדרש קוד עבור הסניפט"}
    if not lang_s:
        return {"ok": False, "error": "נדרשת שפה"}

    try:
        inserted_id = _db._get_repo().create_snippet_proposal(
            title=title_s,
            description=desc_s,
            code=code,
            language=lang_s,
            user_id=int(user_id),
            username=username,
        )
        if not inserted_id:
            emit_event("snippet_submit_error", severity="warn", error="persist_failed")
            return {"ok": False, "error": "persist_failed"}
        emit_event("snippet_submitted", severity="info", user_id=int(user_id))
        return {"ok": True, "id": str(inserted_id)}
    except Exception as e:
        emit_event("snippet_submit_error", severity="warn", error=str(e))
        return {"ok": False, "error": "persist_failed"}


def _normalize_language_tag(language: Optional[str]) -> str:
    try:
        return (language or "").strip().lower()
    except Exception:
        return ""


# --- Built-in snippets (curated examples) ---
# הערה: פריטים אלה נחשבים "מאושרים" כברירת מחדל ומסופקים In-App כך שיופיעו גם ללא זריעת DB.
# אם פריט זה יתווסף למסד בפועל – הלוגיקה בהמשך תמנע כפילות לפי כותרת.
BUILTIN_SNIPPETS: List[Dict[str, Any]] = [
    {
        "title": "זמן יחסי בעברית (TimeUtils.format_relative_time)",
        "description": "פורמט זמן יחסי בעברית (לפני X דקות/אתמול).",
        "language": "python",
        "username": "CodeBot",
        "code": """
class TimeUtils:
    '''כלים לעבודה עם זמן ותאריכים'''
    
    @staticmethod
    def format_relative_time(dt: datetime) -> str:
        '''פורמט זמן יחסי (לפני 5 דקות, אתמול וכו')'''
        
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
""",
    },
    {
        "title": "אסקייפ ל-Markdown בטלגרם (TextUtils.escape_markdown)",
        "description": "הגנה על תווים מיוחדים ב-Markdown V1/V2.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class TextUtils:
    '''כלים לעבודה עם טקסט'''
    
    @staticmethod
    def escape_markdown(text: str, version: int = 2) -> str:
        '''הגנה על תווים מיוחדים ב-Markdown'''
        
        if version == 2:
            # Markdown V2: כל התווים שיש לאסקייפ לפי Telegram MarkdownV2
            special_chars = set("_*[]()~`>#+-=|{}.!\\")
            return "".join(("\\" + ch) if ch in special_chars else ch for ch in text)
        else:
            # Markdown V1: נשתמש בקבוצה מצומצמת אך גם נסמן סוגריים כדי להימנע מתקלות כלליות
            special_chars = set("_*`[()\\")
            return "".join(("\\" + ch) if ch in special_chars else ch for ch in text)
""",
    },
    {
        "title": "ניקוי שמות קבצים (TextUtils.clean_filename)",
        "description": "ניקוי שם קובץ מתווים לא חוקיים, רווחים ונקודות מיותרות והגבלת אורך.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class TextUtils:
    '''כלים לעבודה עם טקסט'''
    
    @staticmethod
    def clean_filename(filename: str) -> str:
        '''ניקוי שם קובץ מתווים לא חוקיים'''
        
        # הסרת תווים לא חוקיים
        cleaned = re.sub(r'[<>:\"/\\|?*]', '_', filename)
        
        # הסרת רווחים מיותרים
        cleaned = re.sub(r'\s+', '_', cleaned)
        
        # הסרת נקודות מיותרות
        cleaned = re.sub(r'\.+', '.', cleaned)
        
        # הגבלת אורך
        if len(cleaned) > 100:
            name, ext = os.path.splitext(cleaned)
            cleaned = name[:100-len(ext)] + ext
        
        return cleaned.strip('._')
""",
    },
    {
        "title": "מענה בטוח ל-CallbackQuery (TelegramUtils.safe_answer)",
        "description": "answer בטוח עם התעלמות משגיאות ידועות.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class TelegramUtils:
    '''כלים לעבודה עם Telegram'''
    
    @staticmethod
    async def safe_answer(query, text: Optional[str] = None, show_alert: bool = False, cache_time: Optional[int] = None) -> None:
        '''מענה בטוח ל-CallbackQuery: מתעלם משגיאות 'Query is too old'/'query_id_invalid'.'''
        try:
            kwargs: Dict[str, Any] = {}
            if text is not None:
                kwargs["text"] = text
            if show_alert:
                kwargs["show_alert"] = True
            if cache_time is not None:
                kwargs["cache_time"] = int(cache_time)
            await query.answer(**kwargs)
        except Exception as e:
            msg = str(e).lower()
            if "query is too old" in msg or "query_id_invalid" in msg or "message to edit not found" in msg:
                return
            raise
""",
    },
    {
        "title": "פיצול הודעות ארוכות (TelegramUtils.split_long_message)",
        "description": "חלוקה לחלקים תחת מגבלת 4096 של טלגרם.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class TelegramUtils:
    '''כלים לעבודה עם Telegram'''
    
    @staticmethod
    def split_long_message(text: str, max_length: int = 4096) -> List[str]:
        '''חלוקת הודעה ארוכה לחלקים'''
        
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
""",
    },
    {
        "title": "עריכת הודעה בטוחה (TelegramUtils.safe_edit_message_text)",
        "description": "תומך בסינכרוני/אסינכרוני, מתעלם מ-'message is not modified'.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class TelegramUtils:
    '''כלים לעבודה עם Telegram'''
    
    @staticmethod
    async def safe_edit_message_text(query, text: str, reply_markup=None, parse_mode: Optional[str] = None) -> None:
        '''עריכת טקסט הודעה בבטיחות: מתעלם משגיאת 'Message is not modified'.

        תומך גם במימושי בדיקות שבהם `edit_message_text` היא פונקציה סינכרונית
        שמחזירה `None` (לא awaitable), וגם במימושים אסינכרוניים רגילים.
        '''
        try:
            edit_func = getattr(query, "edit_message_text", None)
            if not callable(edit_func):
                return

            kwargs = {"text": text, "reply_markup": reply_markup}
            if parse_mode is not None:
                kwargs["parse_mode"] = parse_mode

            result = edit_func(**kwargs)

            # אם חזר coroutine – צריך להמתין; אחרת זו פונקציה סינכרונית ואין מה להמתין
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            msg = str(e).lower()
            # התעלמות רק במקרה "not modified" (עמיד לשינויים קלים בטקסט)
            if "not modified" in msg or "message is not modified" in msg:
                return
            raise
""",
    },
    {
        "title": "מניעת לחיצה כפולה (CallbackQueryGuard.should_block_async)",
        "description": "Guard חלון זמן פר-משתמש נגד לחיצות כפולות.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class CallbackQueryGuard:
    '''Guard גורף ללחיצות כפולות על כפתורי CallbackQuery.
    
    מבוסס על טביעת אצבע של המשתמש/הודעה/הנתון (callback_data) כדי לחסום
    את אותה פעולה בחלון זמן קצר, בלי לחסום פעולות שונות.
    '''

    DEFAULT_WINDOW_SECONDS: float = 1.2
    _user_locks: Dict[int, asyncio.Lock] = {}

    @staticmethod
    def should_block(update: Update, context: ContextTypes.DEFAULT_TYPE, window_seconds: Optional[float] = None) -> bool:
        '''בודק בחסימה לא-אסינכרונית אם העדכון הגיע שוב בתוך חלון הזמן.'''
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

            if hasattr(context, "user_data"):
                context.user_data["_last_cb_fp"] = fp
                context.user_data["_cb_guard_until"] = now_ts + win
            return False
        except Exception:
            return False

    @staticmethod
    async def should_block_async(update: Update, context: ContextTypes.DEFAULT_TYPE, window_seconds: Optional[float] = None) -> bool:
        '''בודק בצורה אטומית (עם נעילה) אם לחסום לחיצה כפולה של אותו משתמש.

        חסימה מבוססת חלון זמן פר-משתמש, ללא תלות ב-message_id/data, כדי למנוע מרוץ.
        '''
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
""",
    },
    {
        "title": "עיבוד פריטים בקבוצות (AsyncUtils.batch_process)",
        "description": "הרצת פעולות אסינכרוניות בקבוצות קטנות עם השהיה.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class AsyncUtils:
    '''כלים לעבודה אסינכרונית'''
    
    @staticmethod
    async def batch_process(items: List[Any], process_func: Callable, 
                           batch_size: int = 10, delay: float = 0.1) -> List[Any]:
        '''עיבוד פריטים בקבוצות'''
        
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
""",
    },
    {
        "title": "מדידת זמן עם context manager (PerformanceUtils.measure_time)",
        "description": "מדידה ולוג משך פעולה.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class PerformanceUtils:
    """כלים למדידת ביצועים"""
    
    @staticmethod
    @contextmanager
    def measure_time(operation_name: str):
        '''מדידת זמן עם context manager'''
        
        start_time = time.time()
        try:
            yield
        finally:
            execution_time = time.time() - start_time
            logger.info(f"{operation_name}: {execution_time:.3f}s")
""",
    },
    {
        "title": "בדיקת קוד מסוכן (ValidationUtils.is_safe_code)",
        "description": "ולידציה בסיסית לדפוסים מסוכנים בשפות נפוצות.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class ValidationUtils:
    '''כלים לוולידציה'''
    
    @staticmethod
    def is_safe_code(code: str, programming_language: str) -> Tuple[bool, List[str]]:
        '''בדיקה בסיסית של בטיחות קוד'''
        
        warnings = []
        
        # דפוסים מסוכנים
        dangerous_patterns = {
            'python': [
                r'exec\\s*\\(',
                r'eval\\s*\\(',
                r'__import__\\s*\\(',
                r'open\\s*\\([^)]*["\\']w',  # כתיבה לקובץ
                r'subprocess\\.',
                r'os\\.system\\s*\\(',
                r'os\\.popen\\s*\\(',
            ],
            'javascript': [
                r'eval\\s*\\(',
                r'Function\\s*\\(',
                r'document\\.write\\s*\\(',
                r'innerHTML\\s*=',
                r'outerHTML\\s*=',
            ],
            'bash': [
                r'rm\\s+-rf',
                r'rm\\s+/',
                r'dd\\s+if=',
                r'mkfs\\.',
                r'fdisk\\s+',
            ]
        }
        
        if programming_language in dangerous_patterns:
            for pattern in dangerous_patterns[programming_language]:
                if re.search(pattern, code, re.IGNORECASE):
                    warnings.append(f"דפוס מסוכן אפשרי: {pattern}")
        
        # בדיקות כלליות
        if 'password' in code.lower() or 'secret' in code.lower():
            warnings.append("הקוד מכיל מילות סיסמה או סוד")
        
        if re.search(r'https?://\\S+', code):
            warnings.append("הקוד מכיל URLים")
        
        is_safe = len(warnings) == 0
        return is_safe, warnings
""",
    },
    {
        "title": "יצירת קובץ זמני (FileUtils.create_temp_file)",
        "description": "יצירת קובץ זמני עם תוכן מחרוזת/בייטים.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class FileUtils:
    '''כלים לעבודה עם קבצים'''
    
    @staticmethod
    async def create_temp_file(content: Union[str, bytes], 
                              suffix: str = "") -> str:
        '''יצירת קובץ זמני'''
        
        with tempfile.NamedTemporaryFile(mode='wb', suffix=suffix, delete=False) as temp_file:
            if isinstance(content, str):
                content = content.encode('utf-8')
            
            temp_file.write(content)
            return temp_file.name
""",
    },
    {
        "title": "טעינת קובץ JSON עם ברירת מחדל (ConfigUtils.load_json_config)",
        "description": "טעינת קונפיגורציה מקובץ JSON עם טיפול שגיאות.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class ConfigUtils:
    '''כלים לקונפיגורציה'''
    
    @staticmethod
    def load_json_config(file_path: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        '''טעינת קונפיגורציה מקובץ JSON'''
        
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
""",
    },
    {
        "title": "קאש זיכרון עם TTL (CacheUtils)",
        "description": "set/get/delete עם תפוגה אוטומטית.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class CacheUtils:
    '''כלים לקאש זמני'''
    
    _cache: Dict[str, Any] = {}
    _cache_times: Dict[str, float] = {}
    
    @classmethod
    def set(cls, key: str, value: Any, ttl: int = 300):
        '''שמירה בקאש עם TTL (שניות)'''
        cls._cache[key] = value
        cls._cache_times[key] = time.time() + ttl
    
    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        '''קבלה מהקאש'''
        
        if key not in cls._cache:
            return default
        
        # בדיקת תפוגה
        if time.time() > cls._cache_times.get(key, 0):
            cls.delete(key)
            return default
        
        return cls._cache[key]

    @classmethod
    def delete(cls, key: str):
        '''מחיקה מהקאש'''
        cls._cache.pop(key, None)
        cls._cache_times.pop(key, None)
""",
    },
    {
        "title": "מסנן לוגים לרגישויות (SensitiveDataFilter.filter)",
        "description": "טשטוש טוקנים/סודות בלוגים לפני כתיבה.",
        "language": "python",
        "username": "CodeBot",
        "code": """
class SensitiveDataFilter(logging.Filter):
    '''מסנן שמטשטש טוקנים ונתונים רגישים בלוגים.'''
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
""",
    },
    {
        "title": "נירמול ארגומנטים לפקודות (_coerce_command_args)",
        "description": "המרת args שונים לרשימת מחרוזות נקייה.",
        "language": "python",
        "username": "CodeBot",
        "code": """
def _coerce_command_args(raw_args) -> List[str]:
    '''המרת args מסוגים שונים לרשימת מחרוזות נקייה.'''
    normalized: List[str] = []
    if raw_args is None:
        return normalized
    try:
        if isinstance(raw_args, (list, tuple, set)):
            iterable = list(raw_args)
        elif isinstance(raw_args, str):
            iterable = [raw_args]
        else:
            try:
                iterable = list(raw_args)
            except TypeError:
                iterable = [raw_args]
    except Exception:
        iterable = []
    for arg in iterable:
        if arg is None:
            continue
        if isinstance(arg, bytes):
            try:
                normalized.append(arg.decode("utf-8"))
                continue
            except Exception:
                normalized.append(arg.decode("utf-8", "ignore"))
                continue
        normalized.append(str(arg))
    return normalized
""",
    },
    {
        "title": "טוקן התחברות ל-WebApp (_build_webapp_login_payload)",
        "description": "יצירת טוקן חד-פעמי ושמירתו במסד, עם פקיעה.",
        "language": "python",
        "username": "CodeBot",
        "code": """
def _build_webapp_login_payload(db_manager, user_id: int, username: Optional[str]) -> Optional[Dict[str, str]]:
    '''יוצר טוקן וקישורי התחברות ל-Web App.'''
    base_url = _resolve_webapp_base_url() or DEFAULT_WEBAPP_URL
    secret_candidates = [
        os.getenv("WEBAPP_LOGIN_SECRET"),
        getattr(config, "WEBAPP_LOGIN_SECRET", None),
        os.getenv("SECRET_KEY"),
        getattr(config, "SECRET_KEY", None),
        "dev-secret-key",
    ]
    secret = next((s for s in secret_candidates if s), "dev-secret-key")
    try:
        token_data = f"{user_id}:{int(time.time())}:{secret}"
        auth_token = hashlib.sha256(token_data.encode("utf-8")).hexdigest()[:32]
    except Exception:
        logger.exception("יצירת טוקן webapp נכשלה", exc_info=True)
        return None
    now_utc = datetime.now(timezone.utc)
    token_doc = {
        "token": auth_token,
        "user_id": user_id,
        "username": username,
        "created_at": now_utc,
        "expires_at": now_utc + timedelta(minutes=5),
    }
    _persist_webapp_login_token(db_manager, token_doc)
    login_url = f"{base_url}/auth/token?token={auth_token}&user_id={user_id}"
    return {
        "auth_token": auth_token,
        "login_url": login_url,
        "webapp_url": base_url,
    }
""",
    },
    {
        "title": "קיצור טקסט באמצע (_truncate_middle)",
        "description": "קיצור מחרוזת עם אליפסיס תוך שמירת התחלה וסוף.",
        "language": "python",
        "username": "CodeBot",
        "code": """
def _truncate_middle(text: str, max_len: int) -> str:
    '''מקצר מחרוזת באמצע עם אליפסיס אם חורגת מאורך נתון.'''
    if max_len <= 0:
        return ''
    if len(text) <= max_len:
        return text
    if max_len <= 1:
        return text[:max_len]
    keep = max_len - 1
    front = keep // 2
    back = keep - front
    return text[:front] + '…' + text[-back:]
""",
    },
    {
        "title": "שורת עימוד לכפתורי אינליין (build_pagination_row)",
        "description": "יצירת כפתורי [הקודם/הבא] לעימוד אינליין.",
        "language": "python",
        "username": "CodeBot",
        "code": """
def build_pagination_row(
    page: int,
    total_items: int,
    page_size: int,
    callback_prefix: str,
) -> Optional[List[InlineKeyboardButton]]:
    r'''Return a row of pagination buttons [prev,next] or None if not needed.

    - page: current 1-based page index
    - total_items: total number of items
    - page_size: items per page
    - callback_prefix: for example ``files_page_`` → formats as ``{prefix}{page_num}``
    '''
    if page_size <= 0:
        return None
    total_pages = (total_items + page_size - 1) // page_size if total_items > 0 else 1
    if total_pages <= 1:
        return None
    row: List[InlineKeyboardButton] = []
    if page > 1:
        row.append(InlineKeyboardButton("⬅️ הקודם", callback_data=f"{callback_prefix}{page-1}"))
    if page < total_pages:
        row.append(InlineKeyboardButton("➡️ הבא", callback_data=f"{callback_prefix}{page+1}"))
    return row or None
""",
    },
    {
        "title": "מעקב ביצועים עם Prometheus (track_performance)",
        "description": "Context manager שמזין Histogram בצורה עמידה לטעויות לייבלים.",
        "language": "python",
        "username": "CodeBot",
        "code": """
@contextmanager
def track_performance(operation: str, labels: Optional[Dict[str, str]] = None):
    start = time.time()
    try:
        yield
    finally:
        if operation_latency_seconds is not None:
            try:
                # בחר רק לייבלים שמוגדרים במטריקה ואל תאפשר דריסה של 'operation'
                allowed = set(getattr(operation_latency_seconds, "_labelnames", []) or [])
                target = {"operation": operation}
                if labels:
                    for k, v in labels.items():
                        if k in allowed and k != "operation":
                            target[k] = v
                # ספק ערכי ברירת מחדל לכל לייבל חסר (למשל repo="") כדי לשמור תאימות לאחור
                for name in allowed:
                    if name not in target:
                        if name == "operation":
                            # כבר סופק לעיל
                            continue
                        # ברירת מחדל: מיתר סמנטיקה, מונע ValueError על חוסר בלייבל
                        target[name] = ""
                operation_latency_seconds.labels(**target).observe(time.time() - start)
            except Exception:
                # avoid breaking app on label mistakes
                pass
""",
    },
    {
        "title": "הצעת השלמות לחיפוש גלובלי (fetchSuggestions)",
        "description": "בקשה אסינכרונית בצד לקוח עם ניתוב 401 ל־Login.",
        "language": "javascript",
        "username": "CodeBot",
        "code": """
async function fetchSuggestions(q){
  try{
    const res = await fetch('/api/search/suggestions?q=' + encodeURIComponent(q), {
      headers: { 'Accept': 'application/json' },
      credentials: 'same-origin'
    });

    if (res.status === 401 || res.redirected) {
      window.location.href = '/login?next=' + encodeURIComponent(location.pathname + location.search + location.hash);
      return;
    }

    const contentType = res.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) { hideSuggestions(); return; }

    const data = await res.json();
    if (data && data.suggestions && data.suggestions.length){
      showSuggestions(data.suggestions);
    } else hideSuggestions();
  } catch (e){ hideSuggestions(); }
}
""",
    },
    {
        "title": "הדגשת טווחים בתוצאות חיפוש (highlightSnippet)",
        "description": "הדגשת טווחים עם <mark> מבלי לשבור HTML.",
        "language": "javascript",
        "username": "CodeBot",
        "code": """
function highlightSnippet(text, ranges){
  text = String(text || '');
  if (!ranges || !ranges.length) return escapeHtml(text);
  const items = ranges.slice().sort((a,b)=> (a[0]-b[0]));
  let out = '', last = 0;
  for (const [s,e] of items){
    if (s < last) continue;
    out += escapeHtml(text.slice(last, s));
    out += '<mark class="bg-warning">' + escapeHtml(text.slice(s, e)) + '</mark>';
    last = e;
  }
  out += escapeHtml(text.slice(last));
  return out;
}
""",
    },
]


def _builtin_matches_filters(item: Dict[str, Any], q: Optional[str], language: Optional[str]) -> bool:
    try:
        lang_ok = True
        if language:
            lang_ok = _normalize_language_tag(item.get("language")) == _normalize_language_tag(language)
        if not lang_ok:
            return False
        if not q:
            return True
        needle = str(q or "").strip().lower()
        haystacks = [
            str(item.get("title") or "").lower(),
            str(item.get("description") or "").lower(),
            str(item.get("code") or "").lower(),
        ]
        return any(needle in h for h in haystacks)
    except Exception:
        return True


def _filtered_builtins(q: Optional[str], language: Optional[str]) -> List[Dict[str, Any]]:
    try:
        return [it for it in BUILTIN_SNIPPETS if _builtin_matches_filters(it, q, language)]
    except Exception:
        return BUILTIN_SNIPPETS[:]


def _merge_builtins_with_db(db_items: List[Dict[str, Any]], builtins: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """מניעת כפילות ע"י השוואת כותרות (case-insensitive). בונה רשימה עם builtins תחילה."""
    try:
        existing_titles = {str((it.get("title") or "")).strip().lower() for it in db_items}
        unique_builtins = [it for it in builtins if str((it.get("title") or "")).strip().lower() not in existing_titles]
        # שדה approved_at לצורך אחידות
        now = datetime.now(timezone.utc)
        for it in unique_builtins:
            it.setdefault("approved_at", now)
        return unique_builtins + db_items
    except Exception:
        return builtins + db_items


def approve_snippet(item_id: str, admin_id: int) -> bool:
    try:
        ok = _db._get_repo().approve_snippet(item_id, int(admin_id))
        if ok:
            emit_event("snippet_approved", severity="info", admin_id=int(admin_id))
        return ok
    except Exception as e:
        emit_event("snippet_approve_error", severity="warn", error=str(e))
        return False


def reject_snippet(item_id: str, admin_id: int, reason: str) -> bool:
    try:
        ok = _db._get_repo().reject_snippet(item_id, int(admin_id), _sanitize_text(reason, 300))
        if ok:
            emit_event("snippet_rejected", severity="info", admin_id=int(admin_id))
        return ok
    except Exception as e:
        emit_event("snippet_reject_error", severity="warn", error=str(e))
        return False


def list_pending_snippets(limit: int = 20, skip: int = 0) -> List[Dict[str, Any]]:
    try:
        return _db._get_repo().list_pending_snippets(limit=limit, skip=skip)
    except Exception:
        return []


def list_public_snippets(
    *,
    q: Optional[str] = None,
    language: Optional[str] = None,
    page: int = 1,
    per_page: int = 30,
) -> Tuple[List[Dict[str, Any]], int]:
    """החזרת סניפטים ציבוריים מאושרים, כולל פריטי Built‑in (ללא כפילות).

    לוגיקה:
    - שלוף מה-DB לפי page/per_page
    - חשב Built‑ins תואמים (q/language)
    - הימנע מכפילות לפי כותרת
    - בעמוד הראשון: קדימות ל-Built‑ins, חתוך ל-per_page
    - total כולל את כמות ה-Built‑ins התואמים (גם אם לא הוצגו בעמוד הנוכחי)
    """
    try:
        db_items, total = _db._get_repo().list_public_snippets(q=q, language=language, page=page, per_page=per_page)
    except Exception:
        db_items, total = [], 0

    try:
        builtins = _filtered_builtins(q, language)
        # סנן כפילויות מול ה-DB
        existing_titles = {str((it.get("title") or "")).strip().lower() for it in db_items}
        unique_builtins = [it for it in builtins if str((it.get("title") or "")).strip().lower() not in existing_titles]
        builtin_total_count = len(unique_builtins)
        # סדר והחזר
        if page <= 1:
            merged = _merge_builtins_with_db(db_items, unique_builtins)
            # חתוך ל-per_page כדי לשמור עקביות API
            try:
                per_page_int = max(1, int(per_page or 30))
            except Exception:
                per_page_int = 30
            return merged[:per_page_int], total + builtin_total_count
        # בעמודים נוספים – החזר את ה-DB בלבד, אך עדכן total כדי שהפאג'ינציה תדע על Built‑ins
        return db_items, total + builtin_total_count
    except Exception:
        return db_items, total
