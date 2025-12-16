# מדריך הגדרות Connection Pool (מעודכן ל-2025)

הקוד בריפו כולל מימושים אופטימליים לניהול חיבורים (Connection Pooling) עבור שירותי התשתית.
מסמך זה מרכז את **משתני הסביבה (ENV)** והגדרות הקונפיגורציה, כולל **ערכי ברירת המחדל (Defaults)** המוטמעים בקוד ("Hardcoded") במידה ולא הוגדר ערך ב-ENV.

---

## 1. MongoDB (PyMongo)
**קובץ:** `database/manager.py`

| משתנה סביבה | ברירת מחדל בקוד | תיאור |
|:---|:---:|:---|
| `MONGODB_MAX_POOL_SIZE` | `50` | מקסימום חיבורים פתוחים במקביל. |
| `MONGODB_MIN_POOL_SIZE` | `5` | מינימום חיבורים שישמרו פתוחים (Warm connections). |
| `MONGODB_WAIT_QUEUE_TIMEOUT_MS` | `5000` | (5 שניות) זמן המתנה לחיבור פנוי לפני זריקת שגיאה. |
| `MONGODB_MAX_IDLE_TIME_MS` | `30000` | (30 שניות) זמן לפני סגירת חיבור לא פעיל. |
| `MONGODB_CONNECT_TIMEOUT_MS` | `10000` | (10 שניות) Timeout ליצירת חיבור ראשוני (TCP/SSL). |
| `MONGODB_SOCKET_TIMEOUT_MS` | `20000` | (20 שניות) Timeout לפעולת קריאה/כתיבה (Socket). |
| `MONGODB_SERVER_SELECTION_TIMEOUT_MS`| `3000` | (3 שניות) זמן המתנה למציאת שרת זמין (בזמן Failover). |
| `MONGODB_HEARTBEAT_FREQUENCY_MS` | `10000` | (10 שניות) תדירות בדיקת דופק מול השרת. |

---

## 2. Redis (redis-py)
**קובץ:** `cache_manager.py`

| משתנה סביבה | ברירת מחדל בקוד | תיאור |
|:---|:---:|:---|
| `REDIS_MAX_CONNECTIONS` | `50` | מקסימום חיבורים ב-Pool של Redis. |
| `REDIS_CONNECT_TIMEOUT` | `5` | (בשניות) זמן המתנה לחיבור. במצב `SAFE_MODE=1` הערך יורד ל-`1`. |
| `REDIS_SOCKET_TIMEOUT` | `5` | (בשניות) זמן המתנה לפעולת רשת. במצב `SAFE_MODE=1` הערך יורד ל-`1`. |
| *(הגדרה פנימית)* | `30` | `health_check_interval` - בדיקת תקינות חיבור כל 30 שניות (קבוע בקוד). |

---

## 3. HTTP Client (Async - aiohttp)
**קובץ:** `http_async.py`

| משתנה סביבה | ברירת מחדל בקוד | תיאור |
|:---|:---:|:---|
| `AIOHTTP_POOL_LIMIT` | `50` | סה"כ חיבורים מקביליים מותרים (לכל הדומיינים יחד). |
| `AIOHTTP_LIMIT_PER_HOST` | `0` | (ללא הגבלה) מקסימום חיבורים לדומיין בודד. ב-Prod מומלץ להגדיר (למשל `20`). |
| `AIOHTTP_TIMEOUT_TOTAL` | `10` | (10 שניות) זמן מקסימלי לכל הבקשה (Connect + Read). |

---

## 4. HTTP Client (Sync - requests)
**קובץ:** `http_sync.py`

| משתנה סביבה | ברירת מחדל בקוד | תיאור |
|:---|:---:|:---|
| `REQUESTS_POOL_CONNECTIONS` | `20` | מספר ה-Pools הפנימיים (לרוב תואם למספר הוסטים ייחודיים). |
| `REQUESTS_POOL_MAXSIZE` | `100` | מקסימום חיבורים נשמרים בתוך כל Pool. |
| `REQUESTS_RETRIES` | `2` | מספר נסיונות חוזרים (Retries) על שגיאות חיבור/5xx. |
| `REQUESTS_TIMEOUT` | `8.0` | (8 שניות) ברירת מחדל ל-Timeout אם לא הוגדר ספציפית בקריאה. |
| `REQUESTS_RETRY_BACKOFF` | `0.2` | פקטור השהייה בין ניסיונות חוזרים (Exponential Backoff). |

---

## תבניות מומלצות לפי סביבה (Copy-Paste)

### 💻 Local Development / CI
הגדרות מינימליות למכונות קטנות ולמניעת תופסני משאבים.

```bash
# MongoDB
MONGODB_MAX_POOL_SIZE=10
MONGODB_MIN_POOL_SIZE=1

# Redis
REDIS_MAX_CONNECTIONS=10
REDIS_CONNECT_TIMEOUT=1

# HTTP
AIOHTTP_POOL_LIMIT=20
REQUESTS_POOL_CONNECTIONS=10
REQUESTS_POOL_MAXSIZE=10
```

### 🚀 Production (High Performance)
הגדרות המיועדות לעומס גבוה ומקביליות רבה.

```bash
# MongoDB
MONGODB_MAX_POOL_SIZE=200
MONGODB_MIN_POOL_SIZE=20
MONGODB_WAIT_QUEUE_TIMEOUT_MS=2000  # Fail fast if overloaded

# Redis
REDIS_MAX_CONNECTIONS=200
REDIS_CONNECT_TIMEOUT=2.0

# HTTP (Async is dominant)
AIOHTTP_POOL_LIMIT=200
AIOHTTP_LIMIT_PER_HOST=50
AIOHTTP_TIMEOUT_TOTAL=20

# HTTP (Sync fallback)
REQUESTS_POOL_CONNECTIONS=50
REQUESTS_POOL_MAXSIZE=100
```
