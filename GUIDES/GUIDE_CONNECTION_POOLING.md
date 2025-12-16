# מדריך הגדרות Connection Pool (מעודכן ל-2025)

הקוד בריפו כבר כולל מימושים אופטימליים לניהול חיבורים (Connection Pooling) עבור כל שירותי התשתית: MongoDB, Redis, HTTP Async (aiohttp), ו-HTTP Sync (requests).

מדריך זה מתמקד ב**הגדרות התצורה (Configuration)** המומלצות לכל סביבה, אותן יש להגדיר בקובץ ה-`.env`.

---

## 1. MongoDB (PyMongo)
**קובץ:** `database/manager.py`
המימוש כולל ניהול Pool אוטומטי, הגדרות Timeout, וניטור שאילתות איטיות (`slow_mongo`).

### משתני סביבה זמינים
| משתנה | ברירת מחדל | תיאור |
|-------|------------|-------|
| `MONGODB_MAX_POOL_SIZE` | `50` | מספר החיבורים המקסימלי ב-Pool. ב-Prod מומלץ להגדיל. |
| `MONGODB_MIN_POOL_SIZE` | `5` | מספר חיבורים מינימלי שישמרו פתוחים (למניעת Latency בגל ראשון). |
| `MONGODB_MAX_IDLE_TIME_MS` | `30000` | זמן מקסימלי שחיבור יכול להיות לא פעיל לפני שנסגר (30 שניות). |
| `MONGODB_WAIT_QUEUE_TIMEOUT_MS` | `5000` | זמן המתנה לחיבור פנוי לפני זריקת שגיאה (5 שניות). |
| `MONGODB_CONNECT_TIMEOUT_MS` | `10000` | Timeout ליצירת חיבור ראשוני (10 שניות). |

---

## 2. Redis (redis-py)
**קובץ:** `cache_manager.py`
המימוש כולל מנגנון Retry אוטומטי (`retry_on_timeout=True`), בדיקות בריאות (`health_check_interval=30`), וניהול Pool פנימי.

### משתני סביבה זמינים
| משתנה | ברירת מחדל | תיאור |
|-------|------------|-------|
| `REDIS_MAX_CONNECTIONS` | `50` | מקסימום חיבורים לשרת ה-Redis. |
| `REDIS_CONNECT_TIMEOUT` | `5` (או `1` ב-Safe Mode) | זמן המתנה לחיבור (שניות). |
| `REDIS_SOCKET_TIMEOUT` | `5` (או `1` ב-Safe Mode) | זמן המתנה לקריאה/כתיבה (שניות). |

---

## 3. HTTP Client (Async & Sync)
כל הבקשות היוצאות מהמערכת עוברות דרך מנגנוני Pooling מרכזיים המונעים יצירת חיבורים מיותרים (TCP Handshake).

### א-סינכרוני (aiohttp)
**קובץ:** `http_async.py` (שימוש דרך `http_async.get_session()`)
| משתנה | ברירת מחדל | תיאור |
|-------|------------|-------|
| `AIOHTTP_POOL_LIMIT` | `50` | סה"כ חיבורים מקביליים מותרים לכל היעדים יחד. |
| `AIOHTTP_LIMIT_PER_HOST` | `0` (ללא הגבלה) | הגבלת חיבורים ליעד ספציפי (מומלץ להגדיר ב-Prod למניעת עומס). |
| `AIOHTTP_TIMEOUT_TOTAL` | `10` | Timeout כולל לבקשה (שניות). |

### סינכרוני (requests)
**קובץ:** `http_sync.py` (שימוש דרך `http_sync.get_session()`)
| משתנה | ברירת מחדל | תיאור |
|-------|------------|-------|
| `REQUESTS_POOL_CONNECTIONS` | `20` | מספר ה-Pools הפנימיים (לרוב תואם למספר הוסטים ייחודיים). |
| `REQUESTS_POOL_MAXSIZE` | `100` | מקסימום חיבורים נשמרים בתוך כל Pool. |
| `REQUESTS_RETRIES` | `2` | מספר נסיונות חוזרים אוטומטיים (על שגיאות רשת/5xx). |
| `REQUESTS_TIMEOUT` | `8` | Timeout לבקשה (שניות). |

---

## תבניות מומלצות לפי סביבה

### 💻 Local Development / CI
הגדרות חסכוניות שמתאימות למכונות עם משאבים מוגבלים.

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

---

## איך לוודא שההגדרות עובדות?

1.  **לוגים באתחול:** חפשו לוגים כמו `db_connected` או `Redis אינו מוגדר` (במידה ומושבת).
2.  **לוגים בזמן ריצה:**
    *   **MongoDB:** המערכת מדפיסה לוג `slow_mongo` אם שאילתה לוקחת יותר מ-`DB_SLOW_MS` (אם מוגדר ב-env).
    *   **HTTP:** המערכת מדפיסה `slow_http_async` אם בקשה לוקחת יותר מ-`HTTP_SLOW_MS`.
3.  **מטריקות (Prometheus):**
    *   `cache_hits_total`, `cache_misses_total` (עבור Redis).
    *   `active_indexes` (עבור Mongo).
