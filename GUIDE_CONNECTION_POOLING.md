### מדריך Connection Pooling משופר (מותאם לריפו)

מסמך זה מסביר איך להגדיר ולכוונן Connection Pooling עבור כל השכבות שנמצאות בשימוש בריפו: MongoDB (PyMongo), Redis (redis-py), HTTP Async (aiohttp), ו-HTTP Sync (requests). ההמלצות כאן תואמות ישירות לקוד הקיים, עם דוגמאות ENV וקוד יישומי.


### TL;DR – ברירות מחדל בטוחות ומומלצות
- **MongoDB (PyMongo)**: `maxPoolSize=50~200` (ברירת מחדל מומלצת: 100), `minPoolSize=5~10`, `waitQueueTimeoutMS=2000~5000`, `maxIdleTimeMS=30_000~60_000`.
- **Redis (redis-py)**: `REDIS_MAX_CONNECTIONS=50~200`, `socket_connect_timeout=1~5`, `socket_timeout=1~5`, `health_check_interval=30`.
- **aiohttp (Async HTTP)**: שימוש ב-ClientSession משותף לתהליך עם `TCPConnector(limit=50~200, limit_per_host=10~50)` ו-`ClientTimeout(total=10~15)`.
- **requests (Sync HTTP)**: שימוש ב-`requests.Session` גלובלי עם `HTTPAdapter(pool_connections=20~50, pool_maxsize=50~200, max_retries=2~3)`.


### מיפוי הקוד הקיים בריפו (היכן מנוהלים החיבורים)
- **MongoDB** – יצירת Client עם Pool והגדרות:
  - קובץ: `database/manager.py` – נעשה שימוש ב-PyMongo עם פרמטרים של Pool:
    - `maxPoolSize=50`, `minPoolSize=5`, `maxIdleTimeMS=30000`, `waitQueueTimeoutMS=5000`, `serverSelectionTimeoutMS=3000`, `socketTimeoutMS=20000`, `connectTimeoutMS=10000`, `retryWrites=True`, `retryReads=True`.
- **Redis** – שימוש ב-`redis.from_url(...)` עם Pool פנימי:
  - קובץ: `cache_manager.py` – מגדיר `max_connections`, `retry_on_timeout=True`, `health_check_interval=30` וזמני timeout.
- **HTTP Async (aiohttp)** – פתיחת סשן לכל פעולה עם Pool מוגדר:
  - קבצים: `integrations.py`, `integrations_github_monitor.py`, `bot_handlers.py`, `integrations_sentry.py`, `utils.py` ועוד – יוצרים `ClientSession(timeout=..., connector=TCPConnector(limit=...))`.
- **HTTP Sync (requests)** – קריאות ממוקדות ללא `Session` משותף:
  - קובץ: `webapp/app.py` – שימוש ב-`requests.get/post(..., timeout=...)`.


### למה כדאי לשנות? (עקרונות)
- **Reuse over Recreate**: יצירת סשן/חיבור לכל בקשה מוסיפה Latency (TCP/TLS Handshake). Pool משותף חוסך זמן ומוריד עומס על שרתים.
- **Backpressure**: מגבלת Pool מגינה על השירות מפני ריבוי מקביליות לא מבוקרות (OOM/Timeouts).
- **תצורה דינמית**: העברת הגדלים/זמנים ל-ENV מאפשרת טיוב לכל סביבת פריסה (dev/staging/prod) ללא שינוי קוד.


### MongoDB (PyMongo) – מה יש היום ומה מומלץ
- הקיים בקוד (`database/manager.py`): שימוש ב-`MongoClient` עם Pool מאופיין היטב.
- המלצות שדרוג:
  - הפוך את ערכי ה-Pool לברי-כוונון דרך ENV/Config (ללא שינוי התנהגות ברירת המחדל).
  - בדיקות בריאות: `client.admin.command('ping')` (קיים), ושקילת מדידת `connPoolStats` למעקב במטריקות.

דוגמה להגדרות ENV מוצעות:
```dotenv
# MongoDB
MONGODB_URL=mongodb://user:pass@host:27017/db
MONGODB_MAX_POOL_SIZE=100
MONGODB_MIN_POOL_SIZE=5
MONGODB_WAIT_QUEUE_TIMEOUT_MS=5000
MONGODB_MAX_IDLE_TIME_MS=30000
MONGODB_SERVER_SELECTION_TIMEOUT_MS=3000
MONGODB_SOCKET_TIMEOUT_MS=20000
MONGODB_CONNECT_TIMEOUT_MS=10000
```

סקיצה לשדרוג פונקציית החיבור (ליישום עתידי בקוד – לא חובה עכשיו):
```python
# database/manager.py (הדגמה)
import os
from datetime import timezone
from config import config
...
self.client = MongoClient(
    config.MONGODB_URL,
    maxPoolSize=int(os.getenv('MONGODB_MAX_POOL_SIZE', '100')),
    minPoolSize=int(os.getenv('MONGODB_MIN_POOL_SIZE', '5')),
    maxIdleTimeMS=int(os.getenv('MONGODB_MAX_IDLE_TIME_MS', '30000')),
    waitQueueTimeoutMS=int(os.getenv('MONGODB_WAIT_QUEUE_TIMEOUT_MS', '5000')),
    serverSelectionTimeoutMS=int(os.getenv('MONGODB_SERVER_SELECTION_TIMEOUT_MS', '3000')),
    socketTimeoutMS=int(os.getenv('MONGODB_SOCKET_TIMEOUT_MS', '20000')),
    connectTimeoutMS=int(os.getenv('MONGODB_CONNECT_TIMEOUT_MS', '10000')),
    retryWrites=True,
    retryReads=True,
    tz_aware=True,
    tzinfo=timezone.utc,
    appname=os.getenv('MONGODB_APPNAME') or None,
    compressors=[c for c in (os.getenv('MONGODB_COMPRESSORS') or '').split(',') if c],
    heartbeatFrequencyMS=int(os.getenv('MONGODB_HEARTBEAT_FREQUENCY_MS', '10000')),
)
```

מעקב Pool (אופציונלי):
```python
# איסוף סטטיסטיקות חיבורי Mongo (לייצוא למטריקות/לוגים)
stats = self.client.admin.command('connPoolStats')
# דוגמאות מעניינות: stats['numClientConnections'], stats['totalInUse'], stats['totalAvailable']
```


### Redis (redis-py) – מה יש היום ומה מומלץ
- הקיים בקוד (`cache_manager.py`): שימוש ב-`redis.from_url(...)` עם `max_connections`, זמני timeout, `retry_on_timeout=True`, `health_check_interval=30`.
- המלצות שדרוג:
  - כיוונון `REDIS_MAX_CONNECTIONS` לפי עומס (50–200 מקסימום במרבית התרחישים).
  - השארת `health_check_interval=30` (כבר מוגדר) – מאזנת בעיות עם Idle connections.

ENV לדוגמה:
```dotenv
# Redis
REDIS_URL=redis://localhost:6379/0
REDIS_MAX_CONNECTIONS=100
REDIS_CONNECT_TIMEOUT=2.0
REDIS_SOCKET_TIMEOUT=2.0
```

אין צורך בשינויים מהותיים בקוד – הוא כבר משתמש בפולינג פנימי של redis-py. הכיוונון נעשה דרך ENV.


### HTTP Async (aiohttp) – מעבר ל-ClientSession משותף
- הקיים: פתיחת `ClientSession` חדש פר פעולה עם `TCPConnector(limit=...)` ו-`ClientTimeout(total=...)` (כבר טוב מבחינת מגבלת Pool ו-Timeouts).
- מומלץ: **Session משותף** לכל התהליך, כדי לשמר חיבורי Keep-Alive ולחסוך Handshakes.

ENV קיימים ומומלצים:
```dotenv
AIOHTTP_POOL_LIMIT=100
AIOHTTP_TIMEOUT_TOTAL=15
AIOHTTP_LIMIT_PER_HOST=25   # חדש (מומלץ להוסיף)
```

מודול מוצע לשיתוף סשן (יישום עתידי):
```python
# http_async.py (מומלץ להוסיף)
from __future__ import annotations
import aiohttp
from typing import Optional
import os

_session: Optional[aiohttp.ClientSession] = None

def get_session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        total = int(os.getenv('AIOHTTP_TIMEOUT_TOTAL', '10'))
        limit = int(os.getenv('AIOHTTP_POOL_LIMIT', '50'))
        try:
            limit_per_host = int(os.getenv('AIOHTTP_LIMIT_PER_HOST', '0'))
        except (ValueError, TypeError):
            limit_per_host = 0  # 0 = ללא מגבלה פר-הוסט
        timeout = aiohttp.ClientTimeout(total=total)
        connector = aiohttp.TCPConnector(limit=limit, limit_per_host=limit_per_host)
        _session = aiohttp.ClientSession(timeout=timeout, connector=connector)
    return _session

async def close_session() -> None:
    global _session
    if _session and not _session.closed:
        await _session.close()
```

שילוב בקוד קיים (דוגמה):
```python
# integrations.py – במקום ליצור ClientSession חדש בכל פעם
from http_async import get_session
...
session = get_session()
async with session.post(url, data=payload) as resp:
    ...
```

סגירה מסודרת:
```python
# main.py
import atexit
import asyncio
from http_async import close_session

@atexit.register
def _shutdown_http_session():
    try:
        loop = asyncio.get_event_loop()
        if not loop.is_closed():
            loop.run_until_complete(close_session())
    except RuntimeError:
        # אין event loop פעיל
        pass
    except Exception:
        pass
```

הערה לטסטים: בקובץ `tests/test_aiohttp_pooling_timeouts.py` נבדק ש-`ClientSession` מקבל `timeout` ו-`connector`. במעבר ל-Session משותף, שמרו את אותה תצורה בעת יצירת הסשן הגלובלי.


### HTTP Sync (requests) – שימוש ב-Session עם HTTPAdapter
- הקיים: קריאות נקודתיות עם `requests.get/post(..., timeout=...)`.
- מומלץ: להשתמש ב-`requests.Session` גלובלי עם `HTTPAdapter` שמגדיר Pool ו-Retries.

ENV לדוגמה:
```dotenv
REQUESTS_POOL_CONNECTIONS=20
REQUESTS_POOL_MAXSIZE=100
REQUESTS_TIMEOUT=8
REQUESTS_RETRIES=2
```

מודול מוצע:
```python
# http_sync.py (מומלץ להוסיף)
import os
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

_local = threading.local()

def _create_session() -> requests.Session:
    pool_conns = int(os.getenv('REQUESTS_POOL_CONNECTIONS', '20'))
    pool_max = int(os.getenv('REQUESTS_POOL_MAXSIZE', '100'))
    retries = int(os.getenv('REQUESTS_RETRIES', '2'))
    backoff = float(os.getenv('REQUESTS_RETRY_BACKOFF', '0.2'))
    status_forcelist = (500, 502, 503, 504)
    allowed = frozenset(['GET', 'POST', 'PUT', 'PATCH', 'DELETE'])

    sess = requests.Session()
    # הערה: urllib3 ישנות משתמשות ב-`method_whitelist` ולא ב-`allowed_methods`.
    try:
        retry = Retry(total=retries, backoff_factor=backoff,
                      status_forcelist=status_forcelist,
                      allowed_methods=allowed, raise_on_status=False)
    except TypeError:
        retry = Retry(total=retries, backoff_factor=backoff,
                      status_forcelist=status_forcelist,
                      method_whitelist=allowed, raise_on_status=False)
    adapter = HTTPAdapter(pool_connections=pool_conns, pool_maxsize=pool_max, max_retries=retry)
    sess.mount('https://', adapter)
    sess.mount('http://', adapter)
    return sess

def get_session() -> requests.Session:
    if not hasattr(_local, 'session'):
        _local.session = _create_session()
    return _local.session

def request(method: str, url: str, **kwargs):
    timeout = kwargs.pop('timeout', float(os.getenv('REQUESTS_TIMEOUT', '8')))
    return get_session().request(method=method, url=url, timeout=timeout, **kwargs)
```

שילוב בקוד קיים (דוגמה מתוך `webapp/app.py`):
```python
from http_sync import request
...
resp = request('GET', url, headers=headers)  # timeout יוגדר מה-ENV כברירת מחדל
```


### תוספות חשובות מהמדריך השני (חיזוקים קלים)
- **aiohttp – Connector מועשר**: הפעלת DNS cache, הגדרת `limit_per_host`, והשארת `enable_cleanup_closed` לפינוי חיבורים.

```python
import os, aiohttp
url = "https://example.com"  # דוגמה בלבד; קבעו SSL לפי היעד בפועל
connector = aiohttp.TCPConnector(
    limit=int(os.getenv('AIOHTTP_POOL_LIMIT', '50')),
    limit_per_host=int(os.getenv('AIOHTTP_LIMIT_PER_HOST', '25')),
    use_dns_cache=True,
    ttl_dns_cache=300,
    enable_cleanup_closed=True,
    force_close=False,
    ssl=False if url.startswith('http://') else None,
)
timeout = aiohttp.ClientTimeout(total=int(os.getenv('AIOHTTP_TIMEOUT_TOTAL', '10')))
session = aiohttp.ClientSession(timeout=timeout, connector=connector)
```

- **MongoDB – הרחבות בטוחות (אופציונלי)**: `appname="CodeBot"`, דחיסה (`compressors` כאשר נתמך), ו-`heartbeatFrequencyMS=10000`. אין תמיכה ב-`waitQueueMultiple` ב-PyMongo – אל להשתמש.

```dotenv
# MongoDB (אופציונלי)
MONGODB_APPNAME=CodeBot
MONGODB_COMPRESSORS=zstd,snappy,zlib
MONGODB_HEARTBEAT_FREQUENCY_MS=10000
```

- **Redis – Backoff אקספוננציאלי (אם גרסה תומכת)**: ב-redis-py ≥ 4.2 ניתן להוסיף `Retry`/`ExponentialBackoff` לשיפור התאוששות.

```python
# דוגמה אופציונלית
# from redis.retry import Retry
# from redis.backoff import ExponentialBackoff
# client = redis.from_url(REDIS_URL, retry=Retry(ExponentialBackoff(), 3))
```

- **Health checks**: 
  - Mongo: `admin.command('ping')` ו-`connPoolStats`.
  - Redis: `client.ping()` ו-`INFO` counters.
  - HTTP: מדידה סביב קריאות ורישום `limit/limit_per_host`.

- **צ'קליסט קצר ליישום הדרגתי**:
  - הוספת `AIOHTTP_LIMIT_PER_HOST` ל-ENV ושימוש בו בכל `TCPConnector`.
  - מעבר הדרגתי ל-Sessions משותפים (aiohttp/requests) תוך שמירת התאמה לטסטים קיימים.
  - הוספת מטריקות שימוש ב-Pool ו-Timeouts.
  - אימות ב-Staging בעומס אמיתי לפני Production.

### הנחיות כיוונון לפי סביבה
- **Local/Dev**:
  - `AIOHTTP_POOL_LIMIT=20`, `AIOHTTP_LIMIT_PER_HOST=10`, `AIOHTTP_TIMEOUT_TOTAL=10`
  - `REDIS_MAX_CONNECTIONS=20`
  - MongoDB: `MAX_POOL_SIZE=20`, `MIN_POOL_SIZE=2`
- **Staging**:
  - `AIOHTTP_POOL_LIMIT=50~100`, `AIOHTTP_LIMIT_PER_HOST=25`, `AIOHTTP_TIMEOUT_TOTAL=12~15`
  - `REDIS_MAX_CONNECTIONS=50~100`
  - MongoDB: `MAX_POOL_SIZE=50~100`, `MIN_POOL_SIZE=5`
- **Production**:
  - התאם לפי עומס אמיתי: התחל ב-`AIOHTTP_POOL_LIMIT=100`, `AIOHTTP_LIMIT_PER_HOST=25~50`
  - Redis: `REDIS_MAX_CONNECTIONS=100~200`
  - MongoDB: `MAX_POOL_SIZE=100~200`, `MIN_POOL_SIZE=5~10`

כלל אצבע: גודל Pool ≈ מקביליות שיא רצויה לכל רכיב, עם מרווח קטן (~20%)
להתפרצות זמנית.


### ניטור ותקלות נפוצות
- **אינדיקציות לרוויה**:
  - עלייה ב-`Timeouts`/`waitQueueTimeout` (Mongo), או `ClientTimeout` (aiohttp), או `ReadTimeout` (requests/Redis).
  - זמן תגובה עולה למרות עומס יחסית קבוע.
- **מה בודקים**:
  - MongoDB: `connPoolStats`, טעינת CPU/IO של השרת, אינדקסים.
  - Redis: latency monitor, `INFO` counters (hit/miss, used_memory, connected_clients).
  - HTTP: סטטוסים 5xx/429, עיכובים ב-DNS/TLS.
- **דרכי טיפול**:
  - הגדל `limit`/`maxPoolSize` בהדרגה, או הקטן Timeouts אם יש חסימות ארוכות.
  - וודא Reuse של Sessions (aiohttp/requests) כדי לצמצם Handshakes.


### מה כבר טוב בקוד הזה
- aiohttp כבר מקבל `ClientTimeout(total=...)` ו-`TCPConnector(limit=...)` בכל המקומות הקריטיים.
- Redis מוגדר עם `retry_on_timeout=True` ו-`health_check_interval=30`.
- MongoDB מוגדר עם ברירות מחדל טובות ל-Production (כולל retryable reads/writes).


### תבנית .env מומלצת (לנקודת פתיחה)
```dotenv
# MongoDB
MONGODB_URL=mongodb://user:pass@host:27017/db
MONGODB_MAX_POOL_SIZE=100
MONGODB_MIN_POOL_SIZE=5
MONGODB_WAIT_QUEUE_TIMEOUT_MS=5000
MONGODB_MAX_IDLE_TIME_MS=30000
MONGODB_SERVER_SELECTION_TIMEOUT_MS=3000
MONGODB_SOCKET_TIMEOUT_MS=20000
MONGODB_CONNECT_TIMEOUT_MS=10000

# Redis
REDIS_URL=redis://localhost:6379/0
REDIS_MAX_CONNECTIONS=100
REDIS_CONNECT_TIMEOUT=2.0
REDIS_SOCKET_TIMEOUT=2.0

# aiohttp
AIOHTTP_POOL_LIMIT=100
AIOHTTP_LIMIT_PER_HOST=25
AIOHTTP_TIMEOUT_TOTAL=15

# requests
REQUESTS_POOL_CONNECTIONS=20
REQUESTS_POOL_MAXSIZE=100
REQUESTS_TIMEOUT=8
REQUESTS_RETRIES=2
REQUESTS_RETRY_BACKOFF=0.2
```


### הערות אבטחה ותפעול
- אל תרשמו סודות/טוקנים בלוגים. הגדירו אותם ב-ENV בלבד.
- וודאו Timeouts שמרניים כדי להימנע מ-thread/worker תקועים.
- בהדרגה: שנו ערכי Pool/Timeout והביטו במדדים לפני ואחרי.


### שאלות? הרחבות?
אם תרצו, אפשר להפוך חלק מההצעות כאן ל-PR קטן: הוספת מודולי `http_async.py` ו-`http_sync.py`, קריאות לשימוש בהם במקומות המרכזיים, ושדות חדשים ל-`BotConfig` (אופציונלי).