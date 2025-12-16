# מדריך הגדרות Connection Pool (מעודכן ל-2025)

הקוד בריפו כולל מימושים אופטימליים לניהול חיבורים (Connection Pooling) עבור שירותי התשתית.
מסמך זה מרכז את **משתני הסביבה (ENV)** והגדרות הקונפיגורציה, כולל **ערכי ברירת המחדל (Defaults)** המוטמעים בקוד במידה ולא הוגדר ערך ב-ENV.

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
| *(Internal definition)* | `30` | `health_check_interval` - בדיקת תקינות חיבור כל 30 שניות (קבוע בקוד). |

---

## 3. HTTP Client (Async - aiohttp)
**קובץ:** `http_async.py`

| משתנה סביבה | ברירת מחדל בקוד | תיאור |
|:---|:---:|:---|
| `AIOHTTP_POOL_LIMIT` | `50` | סה"כ חיבורים מקביליים מותרים (לכל הדומיינים יחד). |
| `AIOHTTP_LIMIT_PER_HOST` | `0` | (ללא הגבלה) מקסימום חיבורים לדומיין בודד. |
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

## 5. מדריך פתרון תקלות (Troubleshooting Guide)

זיהוי שגיאות נפוצות והתאמת ערכי הקונפיגורציה לטיפול בהן.

| סימפטום / שגיאה | רכיב | סיבה אפשרית | פעולה מומלצת (ENV) |
|:---|:---|:---|:---|
| **ServerSelectionTimeoutError**<br>או *"Timed out waiting for connection"* | MongoDB | עומס כבד, כל החיבורים ב-Pool תפוסים לאורך זמן. | 1. הגדל `MONGODB_MAX_POOL_SIZE`.<br>2. הגדל `MONGODB_WAIT_QUEUE_TIMEOUT_MS`. |
| **ConnectionFailure / NetworkTimeout** | MongoDB | איטיות ברשת או עומס על ה-DB עצמו. | הגדל `MONGODB_CONNECT_TIMEOUT_MS` ו-`MONGODB_SOCKET_TIMEOUT_MS`. |
| **Redis ConnectionError**<br>*"Maximum number of connections exceeded"* | Redis | ה-Client מנסה לפתוח יותר חיבורים מהמותר. | הגדל `REDIS_MAX_CONNECTIONS`. |
| **Redis TimeoutError** | Redis | השרת עמוס או שיש Latency גבוה. | הגדל `REDIS_SOCKET_TIMEOUT` ו-`REDIS_CONNECT_TIMEOUT`. |
| **aiohttp.ClientConnectionError**<br>או *TimeoutError* | HTTP (Async) | הבקשה לוקחת יותר מדי זמן או שהיעד לא מגיב. | הגדל `AIOHTTP_TIMEOUT_TOTAL`. |
| **Connection pool is full**<br>(Log warning/Error) | HTTP (Async) | יותר מדי בקשות במקביל ליעדים שונים או לאותו יעד. | הגדל `AIOHTTP_POOL_LIMIT` ו-`AIOHTTP_LIMIT_PER_HOST`. |
| **requests.exceptions.ConnectionError**<br>*"Pool is full"* | HTTP (Sync) | עומס בקשות סינכרוניות. | הגדל `REQUESTS_POOL_MAXSIZE` ו-`REQUESTS_POOL_CONNECTIONS`. |
| **ReadTimeout** | HTTP (Sync) | השרת המרוחק מגיב לאט. | הגדל `REQUESTS_TIMEOUT`. |

> **טיפ לניטור:** חפשו בלוגים הודעות `slow_mongo`, `slow_http` או `slow_http_async` – אלו אינדיקטורים לכך שהמערכת ממתינה זמן רב לתשובה, מה שעלול לגרום לרוויה ב-Pools.

---

## תבניות מומלצות מלאות (Full Copy-Paste)

להלן תבניות `.env` הכוללות את **כל** המשתנים האפשריים, מותאמים לסוג הסביבה.

### 💻 Local Development / CI
הגדרות "רזות" ומהירות – חסכון במשאבים וכישלון מהיר (Fail Fast) כשיש בעיות רשת.

```bash
# --- MongoDB (Lightweight) ---
MONGODB_MAX_POOL_SIZE=10
MONGODB_MIN_POOL_SIZE=1
MONGODB_WAIT_QUEUE_TIMEOUT_MS=2000
MONGODB_MAX_IDLE_TIME_MS=10000
MONGODB_CONNECT_TIMEOUT_MS=2000
MONGODB_SOCKET_TIMEOUT_MS=5000
MONGODB_SERVER_SELECTION_TIMEOUT_MS=2000
MONGODB_HEARTBEAT_FREQUENCY_MS=5000

# --- Redis (Lightweight) ---
REDIS_MAX_CONNECTIONS=10
REDIS_CONNECT_TIMEOUT=1
REDIS_SOCKET_TIMEOUT=1

# --- HTTP Async (aiohttp) ---
AIOHTTP_POOL_LIMIT=20
AIOHTTP_LIMIT_PER_HOST=5
AIOHTTP_TIMEOUT_TOTAL=5

# --- HTTP Sync (requests) ---
REQUESTS_POOL_CONNECTIONS=10
REQUESTS_POOL_MAXSIZE=10
REQUESTS_RETRIES=1
REQUESTS_TIMEOUT=5.0
REQUESTS_RETRY_BACKOFF=0.1
```

### 🚀 Production (High Performance)
הגדרות "רחבות" ויציבות – תמיכה במקביליות גבוהה (High Concurrency) ועמידות בפני איטיות רגעית.

```bash
# --- MongoDB (Production) ---
MONGODB_MAX_POOL_SIZE=100         # ניתן להגדיל ל-200 בעומס כבד
MONGODB_MIN_POOL_SIZE=10
MONGODB_WAIT_QUEUE_TIMEOUT_MS=5000
MONGODB_MAX_IDLE_TIME_MS=30000
MONGODB_CONNECT_TIMEOUT_MS=10000
MONGODB_SOCKET_TIMEOUT_MS=20000
MONGODB_SERVER_SELECTION_TIMEOUT_MS=5000
MONGODB_HEARTBEAT_FREQUENCY_MS=10000

# --- Redis (Production) ---
REDIS_MAX_CONNECTIONS=100         # ניתן להגדיל ל-200 בעומס כבד
REDIS_CONNECT_TIMEOUT=2.0
REDIS_SOCKET_TIMEOUT=2.0

# --- HTTP Async (aiohttp - Production) ---
AIOHTTP_POOL_LIMIT=100            # מגבלה גלובלית
AIOHTTP_LIMIT_PER_HOST=25         # הגנה על שירותים חיצוניים ספציפיים מהצפה
AIOHTTP_TIMEOUT_TOTAL=15

# --- HTTP Sync (requests - Production) ---
REQUESTS_POOL_CONNECTIONS=20
REQUESTS_POOL_MAXSIZE=100
REQUESTS_RETRIES=3
REQUESTS_TIMEOUT=10.0
REQUESTS_RETRY_BACKOFF=0.5
```
