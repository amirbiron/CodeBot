# ספריית סניפטים

## 1. זמן יחסי בעברית (`TimeUtils.format_relative_time`)
עוזר להציג למשתמשים כמה זמן עבר בשפה טבעית בעברית, עם טיפול חכם ביחידות זמן שונות.

```python
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
```

## 2. אסקייפ ל-Markdown בטלגרם (`TextUtils.escape_markdown`)
מתאים כשצריך להציג טקסט גולמי בטלגרם בלי לשבור עיצוב Markdown V1/V2.

```python
class TextUtils:
    """כלים לעבודה עם טקסט"""
    
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
```

## 3. ניקוי שמות קבצים (`TextUtils.clean_filename`)
מסיר תווים אסורים ומקצר שמות לפני שמירה בדיסק או העלאה לענן.

```python
class TextUtils:
    """כלים לעבודה עם טקסט"""
    
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
```

## 4. מענה בטוח ל-CallbackQuery (`TelegramUtils.safe_answer`)
מבצע `query.answer` עם החרגה של שגיאות ידועות כדי לא להפיל את הזרימה.

```python
class TelegramUtils:
    """כלים לעבודה עם Telegram"""
    
    @staticmethod
    async def safe_answer(query, text: Optional[str] = None, show_alert: bool = False, cache_time: Optional[int] = None) -> None:
        """מענה בטוח ל-CallbackQuery: מתעלם משגיאות 'Query is too old'/'query_id_invalid'."""
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
```

## 5. פיצול הודעות ארוכות (`TelegramUtils.split_long_message`)
עוזר לפצל תשובה גדולה למקטעים בגבול 4096 תווים של טלגרם.

```python
class TelegramUtils:
    """כלים לעבודה עם Telegram"""
    
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
```

## 6. עריכת הודעה בטוחה (`TelegramUtils.safe_edit_message_text`)
מטפל גם במימושים סינכרוניים וגם אסינכרוניים ומדכא את שגיאת "message is not modified".

```python
class TelegramUtils:
    """כלים לעבודה עם Telegram"""
    
    @staticmethod
    async def safe_edit_message_text(query, text: str, reply_markup=None, parse_mode: Optional[str] = None) -> None:
        """עריכת טקסט הודעה בבטיחות: מתעלם משגיאת 'Message is not modified'.

        תומך גם במימושי בדיקות שבהם `edit_message_text` היא פונקציה סינכרונית
        שמחזירה `None` (לא awaitable), וגם במימושים אסינכרוניים רגילים.
        """
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
```

## 7. מניעת לחיצה כפולה (`CallbackQueryGuard.should_block_async`)
מונע הפעלה כפולה של אותו כפתור באמצעות נעילות פר-משתמש וחלון זמן קצר.

```python
class CallbackQueryGuard:
    """Guard גורף ללחיצות כפולות על כפתורי CallbackQuery.
    
    מבוסס על טביעת אצבע של המשתמש/הודעה/הנתון (callback_data) כדי לחסום
    את אותה פעולה בחלון זמן קצר, בלי לחסום פעולות שונות.
    """

    DEFAULT_WINDOW_SECONDS: float = 1.2
    _user_locks: Dict[int, asyncio.Lock] = {}
    
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
```

## 8. עיבוד פריטים בקבוצות (`AsyncUtils.batch_process`)
מאפשר להריץ פעולות אסינכרוניות בקבוצות קטנות עם השהיה בין גושים.

```python
class AsyncUtils:
    """כלים לעבודה אסינכרונית"""
    
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
```

## 9. מדידת זמן עם context manager (`PerformanceUtils.measure_time`)
נותן דרך קלה למדוד משך פעולה ולרשום אותו ללוג.

```python
class PerformanceUtils:
    """כלים למדידת ביצועים"""
    
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
```

## 10. בדיקת קוד מסוכן (`ValidationUtils.is_safe_code`)
מספק בדיקת בטיחות בסיסית לקוד לפי שפה ומחזיר התראות אפשריות.

```python
class ValidationUtils:
    """כלים לוולידציה"""
    
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
```

## 11. יצירת קובץ זמני (`FileUtils.create_temp_file`)
יוצר קובץ זמני עם תוכן מחרוזת/בייטים ומחזיר את הנתיב לשימוש מיידי.

```python
class FileUtils:
    """כלים לעבודה עם קבצים"""
    
    @staticmethod
    async def create_temp_file(content: Union[str, bytes], 
                              suffix: str = "") -> str:
        """יצירת קובץ זמני"""
        
        with tempfile.NamedTemporaryFile(mode='wb', suffix=suffix, delete=False) as temp_file:
            if isinstance(content, str):
                content = content.encode('utf-8')
            
            temp_file.write(content)
            return temp_file.name
```

## 12. טעינת קובץ JSON עם ברירת מחדל (`ConfigUtils.load_json_config`)
נוח לקריאת קבצי הגדרות עם טיפול בשגיאות ולוג אזהרה אם הקובץ חסר.

```python
class ConfigUtils:
    """כלים לקונפיגורציה"""
    
    @staticmethod
    def load_json_config(file_path: str, default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
```

## 13. קאש זיכרון עם TTL (`CacheUtils.set`/`CacheUtils.get`)
מאפשר לשמור ערכים בזיכרון לזמן קצוב ולהסירם אוטומטית כשהתוקף פג.

```python
class CacheUtils:
    """כלים לקאש זמני"""
    
    _cache: Dict[str, Any] = {}
    _cache_times: Dict[str, float] = {}
    
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
```

## 14. מסנן לוגים לרגישויות (`SensitiveDataFilter.filter`)
מטשטש טוקנים חשופים בלוגים לפני שהם נכתבים החוצה.

```python
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
```

## 15. נירמול ארגומנטים לפקודות (`_coerce_command_args`)
מתאים כשצריך לקבל ארגומנטים מפקודת טלגרם ולתמוך במספר טיפוסים שונים.

```python
def _coerce_command_args(raw_args) -> List[str]:
    """המרת args מסוגים שונים לרשימת מחרוזות נקייה."""
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
```

## 16. טוקן התחברות ל-WebApp (`_build_webapp_login_payload`)
מייצר טוקן התחברות חד-פעמי ל-WebApp ושומר אותו במסד, כולל פקיעת תוקף.

```python
def _build_webapp_login_payload(db_manager, user_id: int, username: Optional[str]) -> Optional[Dict[str, str]]:
    """יוצר טוקן וקישורי התחברות ל-Web App."""
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
```

## 17. קיצור טקסט באמצע (`_truncate_middle`)
נוח להצגת שמות קבצים או מזהים ארוכים תוך שמירה על ההתחלה והסוף.

```python
def _truncate_middle(text: str, max_len: int) -> str:
    """מקצר מחרוזת באמצע עם אליפסיס אם חורגת מאורך נתון."""
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
```

## 18. שורת עימוד לכפתורי אינליין (`build_pagination_row`)
יוצר כפתורי הקודם/הבא לאינליין-קיבורד תוך בדיקת מספר עמודים מינימלי.

```python
def build_pagination_row(
    page: int,
    total_items: int,
    page_size: int,
    callback_prefix: str,
) -> Optional[List[InlineKeyboardButton]]:
    r"""Return a row of pagination buttons [prev,next] or None if not needed.

    - page: current 1-based page index
    - total_items: total number of items
    - page_size: items per page
    - callback_prefix: for example ``files_page_`` → formats as ``{prefix}{page_num}``
    """
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
```

## 19. מעקב ביצועים עם Prometheus (`track_performance`)
מלביש context manager שמזין Histogram של Prometheus בלי להפיל את השירות במקרה של שגיאת לייבלים.

```python
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
```

## 20. הצעת השלמות לחיפוש גלובלי (`fetchSuggestions`)
שולח בקשה אסינכרונית בצד הלקוח ומנתב התחברות מאולצת במקרה של 401.

```javascript
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
```

## 21. הדגשת טווחים בתוצאות חיפוש (`highlightSnippet`)
מקבל טקסט גולמי ומדגיש טווחים רלוונטיים עם `<mark>` מבלי לשבור HTML.

```javascript
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
```

