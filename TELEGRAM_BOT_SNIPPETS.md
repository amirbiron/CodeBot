# 📚 ספריית Code Snippets לבוטי טלגרם

ספרייה של קטעי קוד שימושיים מהריפו הנוכחי למפתחים שבונים בוטים וזרימות טלגרם.

---

## Rate Limiting עם Shadow Mode ו-Admin Bypass

**למה זה שימושי:** מגביל קצב בקשות למשתמשים תוך מתן עקיפה לאדמינים. מצב Shadow מאפשר לבדוק את ההגבלות בלי לחסום באמת – מושלם לטסטים בפרודקשן.

```python
from limits import RateLimitItemPerMinute
from limits.storage import RedisStorage
from limits.strategies import MovingWindowRateLimiter
from functools import wraps
import os

# הגדרת מגבלות
LIMITS = {
    "default": RateLimitItemPerMinute(20),
    "sensitive": RateLimitItemPerMinute(5),
}

# Redis או fallback למצב ללא הגבלה
_storage = RedisStorage(os.getenv("REDIS_URL")) if os.getenv("REDIS_URL") else None
_limiter = MovingWindowRateLimiter(_storage) if _storage else None

def rate_limit(scope: str, limit_name: str = "default", bypass_admins: bool = True):
    def decorator(func):
        @wraps(func)
        async def wrapper(update, context, *args, **kwargs):
            user_id = update.effective_user.id if update.effective_user else 0

            # עקיפה לאדמינים
            if bypass_admins and user_id in {int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.isdigit()}:
                return await func(update, context, *args, **kwargs)

            # בדיקת הגבלה (fail-open אם Redis לא זמין)
            if _limiter is None:
                return await func(update, context, *args, **kwargs)

            key = f"tg:{scope}:{user_id}"
            shadow_mode = os.getenv("RATE_LIMIT_SHADOW_MODE", "false").lower() == "true"

            if not _limiter.hit(LIMITS[limit_name], key):
                if shadow_mode:
                    pass  # רק לוג, לא חוסם
                else:
                    await update.message.reply_text("⏰ שלחת יותר מדי בקשות. נסה שוב בעוד דקה.")
                    return

            return await func(update, context, *args, **kwargs)
        return wrapper
    return decorator

# שימוש:
@rate_limit("image_generation", "sensitive")
async def generate_image(update, context):
    ...
```

---

## TTL דינמי לפי סוג תוכן וקונטקסט

**למה זה שימושי:** במקום TTL קבוע לכל הCache, מתאים את זמן השמירה לפי סוג התוכן – תוכן שמשתנה הרבה (הגדרות) מקבל TTL קצר, תוכן יציב (קבצים) מקבל TTL ארוך.

```python
class DynamicTTL:
    """TTL דינמי לפי סוג תוכן"""

    BASE_TTL = {
        "user_stats": 600,        # 10 דקות
        "file_content": 3600,     # שעה
        "file_list": 300,         # 5 דקות
        "search_results": 180,    # 3 דקות
        "settings": 60,           # דקה
    }

    @classmethod
    def calculate_ttl(cls, content_type: str, context: dict = None) -> int:
        ctx = context or {}
        base_ttl = cls.BASE_TTL.get(content_type, 300)

        # מועדפים – TTL ארוך יותר
        if ctx.get("is_favorite"):
            base_ttl = int(base_ttl * 1.5)

        # תוכן שהשתנה לאחרונה – TTL קצר יותר
        if ctx.get("last_modified_hours_ago", 24) < 1:
            base_ttl = int(base_ttl * 0.5)

        # משתמשי פרימיום מעדיפים תוכן עדכני
        if ctx.get("user_tier") == "premium":
            base_ttl = int(base_ttl * 0.7)

        return max(60, min(base_ttl, 7200))  # בין דקה לשעתיים

# שימוש:
ttl = DynamicTTL.calculate_ttl("file_content", {"is_favorite": True})
cache.set(key, value, ex=ttl)
```

---

## TTL לפי שעות פעילות (Activity-Based)

**למה זה שימושי:** בשעות שיא (9-18) הCache מתרענן מהר יותר כי יש יותר משתמשים פעילים. בלילה – TTL ארוך כי פחות פעילות.

```python
import random
from datetime import datetime

class ActivityBasedTTL:
    """התאמת TTL לפי שעות פעילות"""

    @classmethod
    def get_activity_multiplier(cls) -> float:
        hour = datetime.now().hour
        if 9 <= hour < 18:      # שעות שיא – קצר יותר
            return 0.7
        if 18 <= hour < 23:     # ערב – בינוני
            return 1.0
        return 1.5              # לילה – ארוך יותר

    @classmethod
    def adjust_ttl(cls, base_ttl: int) -> int:
        ttl = int(base_ttl * cls.get_activity_multiplier())

        # הוסף jitter למניעת thundering herd
        jitter = max(1, ttl // 10)
        ttl += random.randint(-jitter, jitter)

        return max(60, min(ttl, 7200))

# שימוש:
base_ttl = 300  # 5 דקות
actual_ttl = ActivityBasedTTL.adjust_ttl(base_ttl)
```

---

## בניית מפתח Cache בטוח

**למה זה שימושי:** מונע מפתחות שבורים מתווים מיוחדים, מגביל אורך אוטומטית עם hash, ומסנן ערכים ריקים.

```python
from hashlib import sha256

def build_cache_key(*parts) -> str:
    """בניית מפתח cache יעיל ומובנה"""
    # סינון חלקים ריקים
    clean_parts = [str(p) for p in parts if p not in (None, "")]
    key = ":".join(clean_parts)

    # תווים בטוחים בלבד
    key = key.replace(" ", "_").replace("/", "-")

    # הגבלת אורך עם hash
    if len(key) > 200:
        key_hash = sha256(key.encode()).hexdigest()[:8]
        key = f"{key[:150]}:{key_hash}"

    return key

# שימוש:
key = build_cache_key("user", user_id, "files", "list")
# => "user:123:files:list"

key = build_cache_key("search", user_id, very_long_query)
# => "search:123:the_query_truncated...:a1b2c3d4"
```

---

## עבודת Batch עם מעקב התקדמות

**למה זה שימושי:** עיבוד מקבילי של מספר קבצים/פריטים עם מעקב אחר התקדמות, מצב (pending/running/completed), וטיפול בשגיאות לכל פריט בנפרד.

```python
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Any, Callable
import time

@dataclass
class BatchJob:
    job_id: str
    user_id: int
    files: List[str]
    status: str = "pending"  # pending, running, completed, failed
    progress: int = 0
    total: int = 0
    results: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.total = len(self.files)

async def process_batch(job: BatchJob, operation_func: Callable):
    """עיבוד batch עם ThreadPoolExecutor"""
    job.status = "running"

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_file = {
            executor.submit(operation_func, job.user_id, f): f
            for f in job.files
        }

        for future in as_completed(future_to_file):
            file_name = future_to_file[future]
            try:
                result = future.result()
                job.results[file_name] = {"success": True, "result": result}
            except Exception as e:
                job.results[file_name] = {"success": False, "error": str(e)}

            job.progress += 1

    failed = sum(1 for r in job.results.values() if not r.get("success"))
    job.status = "completed" if failed == 0 else "failed"
    return job

# שימוש:
job = BatchJob("batch_1", user_id=123, files=["a.py", "b.py", "c.py"])
result = await process_batch(job, validate_file)
print(f"הושלמו: {job.progress}/{job.total}")
```

---

## אימות חתימת GitHub Webhook

**למה זה שימושי:** מבטיח שהWebhook הגיע באמת מGitHub ולא ממקור זדוני. חובה לכל בוט שמקבל webhooks.

```python
import hmac
import hashlib
import os

def verify_github_signature(payload_body: bytes, signature: str) -> bool:
    """אימות חתימת GitHub Webhook"""
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")

    if not secret:
        return False

    if not signature or not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        secret.encode(),
        payload_body,
        hashlib.sha256
    ).hexdigest()

    received = signature[7:]  # הסר "sha256=" prefix

    return hmac.compare_digest(expected, received)

# שימוש בFlask:
@app.route("/webhook/github", methods=["POST"])
def handle_webhook():
    signature = request.headers.get("X-Hub-Signature-256", "")

    if not verify_github_signature(request.data, signature):
        return {"error": "Invalid signature"}, 401

    event_type = request.headers.get("X-GitHub-Event")
    # המשך טיפול...
```

---

## חיבור MongoDB Singleton עם ניקוי אוטומטי

**למה זה שימושי:** מונע יצירת חיבורים מרובים למסד הנתונים, מנהל סגירה נקייה ביציאה, ותומך בשימוש חוזר בחיבור קיים.

```python
import atexit
from datetime import timezone
from pymongo import MongoClient

_client = None
_owns_client = False

def get_mongo_client(mongodb_uri: str):
    """Singleton לחיבור MongoDB"""
    global _client, _owns_client

    if _client is not None:
        return _client

    # נסה למחזר חיבור קיים
    try:
        from database import db
        existing = getattr(db, "client", None)
        if existing:
            _client = existing
            _owns_client = False
            return _client
    except Exception:
        pass

    # יצירת חיבור חדש
    _client = MongoClient(mongodb_uri, tz_aware=True, tzinfo=timezone.utc)
    _owns_client = True
    return _client

def close_mongo_client():
    """סגירה בטוחה ביציאה"""
    global _client
    if _client and _owns_client:
        _client.close()
    _client = None

# רישום לסגירה אוטומטית
atexit.register(close_mongo_client)
```

---

## מעקב פעילות עם Dual-Path (DB + Metrics)

**למה זה שימושי:** גם אם מסד הנתונים לא זמין, הפעילות עדיין נרשמת במטריקות. מבטיח שלא תאבד מידע על פעילות משתמשים.

```python
from datetime import datetime, timezone

class ActivityReporter:
    def __init__(self, db, note_active_user_func=None):
        self.db = db
        self.note_active_user = note_active_user_func or (lambda x: None)

    def report_activity(self, user_id: int, service_id: str):
        """דיווח פעילות עם fallback למטריקות"""
        now = datetime.now(timezone.utc)

        # נסה DB קודם
        try:
            self.db.user_interactions.update_one(
                {"service_id": service_id, "user_id": user_id},
                {
                    "$set": {"last_interaction": now},
                    "$inc": {"interaction_count": 1},
                    "$setOnInsert": {"created_at": now}
                },
                upsert=True
            )
        except Exception:
            pass  # DB נכשל – נמשיך למטריקות

        # תמיד עדכן מטריקות (גם אם DB הצליח)
        try:
            self.note_active_user(user_id)
        except Exception:
            pass

# שימוש:
reporter = ActivityReporter(db, note_active_user=prometheus_gauge.set)
reporter.report_activity(user_id=123, service_id="my_bot")
```

---

## חיפוש Fuzzy עם Fallback

**למה זה שימושי:** חיפוש חכם שמוצא התאמות גם עם שגיאות כתיב. אם rapidfuzz לא מותקן – נופל לחיפוש פשוט יותר.

```python
from typing import List, Tuple

# נסה rapidfuzz (מהיר), אחרת fallback
try:
    from rapidfuzz import fuzz, process
    HAS_FUZZY = True
except ImportError:
    HAS_FUZZY = False

def fuzzy_search(query: str, choices: List[str], limit: int = 5, min_score: int = 60) -> List[Tuple[str, int]]:
    """חיפוש fuzzy עם fallback לחיפוש פשוט"""
    if not query or not choices:
        return []

    if HAS_FUZZY:
        results = process.extract(query, choices, scorer=fuzz.partial_ratio, limit=limit)
        return [(match, score) for match, score, _ in results if score >= min_score]

    # Fallback פשוט
    query_lower = query.lower()
    scored = []
    for choice in choices:
        choice_lower = choice.lower()
        if query_lower in choice_lower or choice_lower in query_lower:
            # ציון לפי אחוז חפיפה
            score = int(100 * min(len(query), len(choice)) / max(len(query), len(choice)))
            scored.append((choice, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [(c, s) for c, s in scored[:limit] if s >= min_score]

# שימוש:
files = ["main.py", "utils.py", "helpers.py", "test_main.py"]
matches = fuzzy_search("main", files)
# => [("main.py", 100), ("test_main.py", 80)]
```

---

## קידוד Callback Data עם טוקנים (מגבלת 64 בייט)

**למה זה שימושי:** טלגרם מגביל callback_data ל-64 בייטים. כששמות קבצים ארוכים, נשתמש בטוקנים קצרים במקום השם המלא.

```python
import secrets

def get_or_create_token(context, file_name: str) -> str:
    """יצירת טוקן קצר לשם קובץ ארוך"""
    tokens = context.user_data.setdefault('name_by_tok', {})
    reverse = context.user_data.setdefault('tok_by_name', {})

    # אם כבר יש טוקן – החזר אותו
    if file_name in reverse:
        return reverse[file_name]

    # צור טוקן חדש
    tok = secrets.token_hex(4)  # 8 תווים
    while tok in tokens:
        tok = secrets.token_hex(4)

    tokens[tok] = file_name
    reverse[file_name] = tok
    return tok

def resolve_token(context, callback_suffix: str) -> str:
    """פענוח טוקן חזרה לשם קובץ"""
    if callback_suffix.startswith('tok:'):
        token = callback_suffix.split(':', 1)[1]
        return context.user_data.get('name_by_tok', {}).get(token, callback_suffix)
    return callback_suffix

def make_safe_callback(context, action: str, file_name: str) -> str:
    """יצירת callback_data בטוח"""
    callback = f"{action}{file_name}"

    if len(callback.encode('utf-8')) <= 64:
        return callback

    token = get_or_create_token(context, file_name)
    return f"{action}tok:{token}"

# שימוש:
callback_data = make_safe_callback(context, "show_", very_long_filename)
# => "show_tok:a1b2c3d4" במקום "show_very_long_filename_that_exceeds_limit"

# בhandler:
file_name = resolve_token(context, query.data.replace("show_", ""))
```

---

## דקורטור למדידת ביצועי פעולות DB

**למה זה שימושי:** מודד אוטומטית את זמן כל פעולת מסד נתונים ומדווח למטריקות. מזהה פעולות איטיות בקלות.

```python
import time
from functools import wraps

def instrument_db(operation_name: str):
    """דקורטור למעקב ביצועי DB"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            start = time.perf_counter()
            status = "ok"

            try:
                result = func(self, *args, **kwargs)
                if isinstance(result, bool):
                    status = "ok" if result else "fail"
                return result
            except Exception:
                status = "error"
                raise
            finally:
                duration = time.perf_counter() - start
                try:
                    record_db_operation(operation_name, duration, status=status)
                except Exception:
                    pass

        return wrapper
    return decorator

# שימוש:
class Repository:
    @instrument_db("db.save_snippet")
    def save_snippet(self, user_id: int, content: str):
        return self.collection.insert_one({"user_id": user_id, "content": content})

    @instrument_db("db.get_user_files")
    def get_user_files(self, user_id: int):
        return list(self.collection.find({"user_id": user_id}))
```

---

## דקורטורים משורשרים להרשאות

**למה זה שימושי:** שילוב מספר בדיקות הרשאה בדקורטור אחד – רשימת צ'אטים מורשים, בדיקת אדמין, והגבלת קצב. קוד נקי וקריא.

```python
from functools import wraps

def admin_required(func):
    """בדיקה שהמשתמש אדמין"""
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        user_id = update.effective_user.id if update.effective_user else 0
        admin_ids = {int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.isdigit()}

        if user_id not in admin_ids:
            await update.message.reply_text("❌ פקודה זו זמינה למנהלים בלבד.")
            return

        return await func(update, context, *args, **kwargs)
    return wrapper

def chat_allowlist_required(func):
    """בדיקה שהצ'אט ברשימה המורשית"""
    @wraps(func)
    async def wrapper(update, context, *args, **kwargs):
        chat_id = update.effective_chat.id if update.effective_chat else 0
        allowed = {int(x) for x in os.getenv("ALLOWED_CHAT_IDS", "").split(",") if x.lstrip("-").isdigit()}

        if allowed and chat_id not in allowed:
            return  # התעלם בשקט

        return await func(update, context, *args, **kwargs)
    return wrapper

# שימוש – שרשרת דקורטורים:
@chat_allowlist_required
@admin_required
@rate_limit("admin_commands", "sensitive")
async def restart_service(update, context):
    """פקודת ניהול – רק לאדמינים, רק בצ'אטים מורשים"""
    ...
```

---

## תזמון תזכורות עם Job Queue

**למה זה שימושי:** שימוש ב-job_queue של python-telegram-bot לתזמון משימות עתידיות, עם טעינת תזכורות קיימות בהפעלה מחדש.

```python
from datetime import datetime, timezone
from telegram.ext import Application

class ReminderScheduler:
    def __init__(self, application: Application, db):
        self.app = application
        self.db = db
        self.job_queue = application.job_queue

    async def start(self):
        """טעינת תזכורות קיימות"""
        reminders = self.db.get_pending_reminders()
        for reminder in reminders:
            await self.schedule_reminder(reminder)

        # בדיקת תזכורות חוזרות כל שעה
        self.job_queue.run_repeating(
            self._check_recurring,
            interval=3600,
            first=10,
            name="recurring_check"
        )

    async def schedule_reminder(self, reminder: dict) -> bool:
        rid = reminder["reminder_id"]
        when = reminder["remind_at"]
        user_id = reminder["user_id"]
        name = f"reminder_{rid}"

        # בטל job קיים אם יש
        for job in self.job_queue.get_jobs_by_name(name):
            job.schedule_removal()

        if when <= datetime.now(timezone.utc):
            # שלח מיד
            await self._send_reminder(reminder)
        else:
            # תזמן לעתיד
            self.job_queue.run_once(
                self._send_job,
                when=when,
                name=name,
                data=reminder,
                chat_id=user_id
            )
        return True

    async def _send_job(self, context):
        await self._send_reminder(context.job.data)

    async def _send_reminder(self, reminder: dict):
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        kb = [[
            InlineKeyboardButton("✅ בוצע", callback_data=f"rem_done_{reminder['reminder_id']}"),
            InlineKeyboardButton("⏰ דחה", callback_data=f"rem_snooze_{reminder['reminder_id']}")
        ]]

        await self.app.bot.send_message(
            chat_id=reminder["user_id"],
            text=f"⏰ **תזכורת!**\n\n📌 {reminder['title']}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(kb)
        )

# שימוש:
def setup_reminders(application):
    scheduler = ReminderScheduler(application, db)
    application.job_queue.run_once(
        lambda ctx: ctx.application.create_task(scheduler.start()),
        when=1
    )
```

---

## ייבוא אופציונלי עם Fallback

**למה זה שימושי:** מאפשר לקוד לרוץ גם בלי תלויות אופציונליות. שימושי לטסטים ולסביבות מינימליות.

```python
# דפוס 1: ייבוא עם fallback לNone
try:
    import aiohttp
except ImportError:
    aiohttp = None

# שימוש בטוח
if aiohttp is not None:
    async with aiohttp.ClientSession() as session:
        ...

# דפוס 2: fallback לפונקציה ריקה
try:
    from metrics import record_event
except ImportError:
    def record_event(*args, **kwargs):
        pass  # לא עושה כלום

# דפוס 3: fallback לדקורטור ריק
try:
    from cache_manager import cached
except ImportError:
    def cached(expire_seconds=300, key_prefix="default"):
        def decorator(func):
            return func  # מחזיר את הפונקציה כמו שהיא
        return decorator

# דפוס 4: fallback למחלקה מינימלית
try:
    from cache_manager import cache
except ImportError:
    class cache:  # NullCache
        @staticmethod
        def get(key): return None
        @staticmethod
        def set(key, value, ex=None): pass
        @staticmethod
        def delete(key): pass
```

---

## ניקוי ספריית Temp בטוח

**למה זה שימושי:** מונע מחיקה בטעות של ספריות חשובות. מוודא שאנחנו מוחקים רק מתוך /tmp ומטפל בsharing violations.

```python
import os
import shutil

def safe_cleanup(path: str) -> bool:
    """ניקוי ספרייה עם בדיקות בטיחות"""
    try:
        # וידוא שהנתיב הוא בתוך /tmp
        real_path = os.path.realpath(path)
        if not real_path.startswith("/tmp/"):
            return False

        # לא מוחקים ספריות ראשיות
        forbidden = {"/tmp", "/tmp/", "/var", "/home"}
        if real_path.rstrip("/") in forbidden:
            return False

        # וידוא שהספרייה קיימת
        if not os.path.exists(real_path):
            return True  # כבר לא קיימת

        if os.path.isfile(real_path):
            os.remove(real_path)
        else:
            shutil.rmtree(real_path, ignore_errors=True)

        return True

    except PermissionError:
        return False  # קובץ בשימוש
    except Exception:
        return False

# שימוש:
temp_dir = "/tmp/bot_processing_123"
# ... עיבוד ...
safe_cleanup(temp_dir)
```

---

## רישום מטריקות Prometheus אידמפוטנטי

**למה זה שימושי:** מונע שגיאות כשהמודול נטען מחדש (reload). מחזיר מטריקה קיימת אם כבר רשומה.

```python
try:
    from prometheus_client import Counter, Histogram, REGISTRY
except ImportError:
    Counter = Histogram = REGISTRY = None

def ensure_metric(name: str, create_fn):
    """יצירת מטריקה או החזרת קיימת"""
    if REGISTRY is None:
        return None

    # בדוק אם כבר קיימת
    try:
        existing = REGISTRY._names_to_collectors.get(name)
        if existing:
            return existing
    except Exception:
        pass

    # נסה ליצור
    try:
        return create_fn()
    except ValueError:  # Duplicated timeseries
        return REGISTRY._names_to_collectors.get(name)

# שימוש:
cache_hits = ensure_metric(
    "cache_hits_total",
    lambda: Counter("cache_hits_total", "Total cache hits", ["backend"])
)

request_duration = ensure_metric(
    "request_duration_seconds",
    lambda: Histogram("request_duration_seconds", "Request duration", ["endpoint"])
)

# עכשיו אפשר לעשות reload למודול בלי שגיאות
```

---

## טעינת קונפיגורציה עם Fallback

**למה זה שימושי:** טעינת הגדרות מקובץ YAML בבטחה. אם הקובץ חסר או פגום – מחזיר ערכי ברירת מחדל במקום לקרוס.

```python
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

def load_config(config_path: str, default: dict = None) -> dict:
    """טעינת קונפיגורציה עם fallback"""
    if default is None:
        default = {}

    if yaml is None:
        return default

    try:
        path = Path(config_path)
        if not path.exists():
            return default

        content = path.read_text(encoding='utf-8')
        data = yaml.safe_load(content) or {}

        # מיזוג עם ברירות מחדל
        result = dict(default)
        result.update(data)
        return result

    except Exception:
        return default

# שימוש:
config = load_config(
    'config/settings.yaml',
    default={
        "max_file_size": 1024 * 1024,
        "allowed_extensions": [".py", ".js"],
        "cache_ttl": 300
    }
)
```
