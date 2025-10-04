# 📊 שיפור Logging ו-Monitoring

## 🔍 ממצאים

### מצב נוכחי
- **502 logger calls** ברחבי הקוד ✅
- רוב בעברית (קשה ל-grep/analytics)
- אין structured logging
- אין correlation IDs
- אין performance metrics
- אין alerting על שגיאות קריטיות

---

## ⚠️ בעיות ספציפיות

### 1. Logging בעברית
```python
# דוגמה מ-database/manager.py:119
logger.info("התחברות למסד הנתונים הצליחה...")

# בעיה:
# - קשה לחפש: grep "connection success" לא עובד
# - Tools כמו Sentry/Datadog לא מזהים patterns
# - אין i18n אמיתי
```

### 2. חסרים Correlation IDs
```python
# בעיה: אי אפשר לעקוב אחרי request מלא
logger.info("שומר קובץ")  # איזה משתמש? איזה request?
# ... 50 שורות אחר כך ...
logger.error("שגיאה בשמירה")  # אותו request? משתמש אחר?
```

### 3. אין Performance Tracking
```python
# חסר:
# - כמה זמן לקח save?
# - כמה זמן לקח search?
# - bottlenecks איפה?
```

---

## ✅ פתרונות מומלצים

### 1. Structured Logging עם structlog

```python
# utils/logging_config.py
import structlog
import logging

def setup_logging():
    """הגדרת structured logging"""
    
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.dev.ConsoleRenderer() if DEBUG else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )

logger = structlog.get_logger()
```

**שימוש:**
```python
# ✅ טוב - structured + עברית בהודעה
logger.info(
    "file_saved",
    user_id=user_id,
    file_name=file_name,
    size_bytes=len(code),
    language=lang,
    msg_he="קובץ נשמר בהצלחה"
)

# במקום:
# ❌ רע
logger.info(f"קובץ {file_name} נשמר בהצלחה")
```

**יתרונות:**
- ניתן לחיפוש: `grep '"event":"file_saved"'`
- ניתן ל-parsing אוטומטי
- תמיכה ב-analytics tools
- עברית בשדה נפרד

---

### 2. Request Correlation

```python
# middleware/correlation.py
import uuid
from contextvars import ContextVar

request_id_var = ContextVar('request_id', default=None)

def generate_request_id() -> str:
    return str(uuid.uuid4())[:8]  # קצר ונוח

async def correlation_middleware(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """מוסיף request_id לכל פעולה"""
    req_id = generate_request_id()
    request_id_var.set(req_id)
    
    # הוסף ל-context לגישה בכל מקום
    context.user_data['request_id'] = req_id
    
    logger.bind(request_id=req_id)  # structlog
    
    return True  # continue to handlers

# שימוש:
logger.info("processing_start", request_id=request_id_var.get())
# ... 
logger.info("processing_end", request_id=request_id_var.get())
```

**תוצאה בלוגים:**
```json
{"event": "processing_start", "request_id": "a3f2c891", "timestamp": "..."}
{"event": "db_query", "request_id": "a3f2c891", "duration_ms": 45}
{"event": "processing_end", "request_id": "a3f2c891", "total_duration_ms": 120}
```

---

### 3. Performance Tracking

```python
# utils/metrics.py
import time
from contextlib import contextmanager
import structlog

logger = structlog.get_logger()

@contextmanager
def track_performance(operation: str, **extra):
    """Context manager למדידת ביצועים"""
    start = time.time()
    try:
        yield
    finally:
        duration_ms = (time.time() - start) * 1000
        logger.info(
            "performance",
            operation=operation,
            duration_ms=round(duration_ms, 2),
            **extra
        )

# שימוש:
async def save_file(user_id: int, file_name: str, code: str):
    with track_performance("save_file", user_id=user_id, file_size=len(code)):
        # ... save logic ...
        pass
```

**דוגמת פלט:**
```json
{
  "event": "performance",
  "operation": "save_file",
  "duration_ms": 45.23,
  "user_id": 12345,
  "file_size": 1520
}
```

---

### 4. Error Tracking עם Sentry

```python
# main.py
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    environment=os.getenv("ENVIRONMENT", "production"),
    traces_sample_rate=0.1,  # 10% של transactions
    profiles_sample_rate=0.1,
    integrations=[
        LoggingIntegration(level=logging.INFO, event_level=logging.ERROR)
    ],
    before_send=filter_sensitive_data,  # טשטוש נתונים רגישים
)

def filter_sensitive_data(event, hint):
    """מסנן credentials מלוגים"""
    # Remove BOT_TOKEN, passwords, etc.
    if 'extra' in event:
        for key in list(event['extra'].keys()):
            if any(sensitive in key.lower() for sensitive in ['token', 'password', 'secret']):
                event['extra'][key] = '[REDACTED]'
    return event
```

---

### 5. Business Metrics

```python
# utils/business_metrics.py
from dataclasses import dataclass
from datetime import datetime, timezone

@dataclass
class BusinessMetrics:
    """מדדי עסק חשובים"""
    
    @staticmethod
    async def track_file_saved(user_id: int, language: str, size: int):
        logger.info(
            "business_metric",
            metric="file_saved",
            user_id=user_id,
            language=language,
            size_bytes=size,
            timestamp=datetime.now(timezone.utc).isoformat()
        )
    
    @staticmethod
    async def track_search_performed(user_id: int, query: str, results_count: int):
        logger.info(
            "business_metric",
            metric="search",
            user_id=user_id,
            query_length=len(query),
            results_count=results_count
        )
    
    @staticmethod
    async def track_github_sync(user_id: int, files_count: int, success: bool):
        logger.info(
            "business_metric",
            metric="github_sync",
            user_id=user_id,
            files_count=files_count,
            success=success
        )
```

---

## 📈 Dashboard ו-Alerts

### Grafana Dashboard (example queries)

```promql
# קצב שמירות לדקה
rate(file_saved_total[1m])

# זמן תגובה ממוצע
histogram_quantile(0.95, rate(operation_duration_seconds_bucket[5m]))

# שיעור שגיאות
rate(errors_total[5m]) / rate(requests_total[5m])
```

### Alert Rules

```yaml
# alerts.yml
groups:
  - name: codebot_alerts
    rules:
      - alert: HighErrorRate
        expr: rate(errors_total[5m]) > 0.05
        for: 5m
        annotations:
          summary: "שיעור שגיאות גבוה: {{ $value }}"
      
      - alert: SlowOperations
        expr: histogram_quantile(0.95, rate(operation_duration_seconds_bucket[5m])) > 2
        for: 10m
        annotations:
          summary: "פעולות איטיות: 95p > 2s"
      
      - alert: MongoDBDown
        expr: up{job="mongodb"} == 0
        for: 1m
        annotations:
          summary: "MongoDB לא זמין!"
```

---

## 🔧 תוכנית יישום

### שבוע 1: Foundation
- [ ] התקנת structlog
- [ ] המרת 50 logger calls קריטיים
- [ ] הוספת request correlation
- [ ] Setup Sentry

### שבוע 2: Performance
- [ ] `track_performance` decorator
- [ ] מדידת כל הפעולות הקריטיות
- [ ] Dashboard ראשון

### שבוע 3: Business Metrics  
- [ ] track_file_saved
- [ ] track_search
- [ ] track_github_sync
- [ ] weekly reports

### שבוע 4: Alerts
- [ ] הגדרת alerts
- [ ] Integration עם Telegram/Slack
- [ ] On-call rotation

---

## 📊 דוגמת תוצאה

**לפני:**
```
2024-01-15 10:23:45 - INFO - שומר קובץ
2024-01-15 10:23:47 - ERROR - שגיאה בשמירה
```

**אחרי:**
```json
{
  "timestamp": "2024-01-15T10:23:45.123Z",
  "level": "info",
  "event": "file_save_start",
  "request_id": "a3f2c891",
  "user_id": 12345,
  "file_name": "test.py",
  "language": "python",
  "size_bytes": 1520,
  "msg_he": "מתחיל שמירת קובץ"
}
{
  "timestamp": "2024-01-15T10:23:47.456Z",
  "level": "error",
  "event": "file_save_error",
  "request_id": "a3f2c891",
  "user_id": 12345,
  "error": "DuplicateKeyError",
  "stack_trace": "...",
  "msg_he": "שגיאה בשמירת קובץ"
}
```

---

## 🎯 מדדי הצלחה

- [ ] כל request ניתן למעקב end-to-end
- [ ] P95 latency < 500ms
- [ ] Error rate < 1%
- [ ] MTTR (Mean Time To Recovery) < 15 דקות
- [ ] Dashboard ב-Grafana עם 10+ metrics
- [ ] Alerts עובדים ב-production

---

**Bottom line**: Logging טוב = Debug מהיר = שינה טובה 😴
