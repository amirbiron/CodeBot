Rate Limiting
=============

Environment variables
---------------------

- ``RATE_LIMIT_ENABLED``: Enable rate limiting globally (default: ``true``)
- ``RATE_LIMIT_SHADOW_MODE``: Count-only mode, no blocking (default: ``false``). Recommended to start with ``true`` in staging.
- ``RATE_LIMIT_STRATEGY``: ``moving-window`` or ``fixed-window`` (default: ``moving-window``)
- ``ADMIN_USER_IDS``: Comma-separated Telegram user IDs that bypass some limits.

Databases and Cache (Pooling/Timeouts)
--------------------------------------

- ``MONGODB_URL``: MongoDB connection string (``mongodb://`` or ``mongodb+srv://``)
- ``MONGODB_MAX_POOL_SIZE`` / ``MONGODB_MIN_POOL_SIZE`` / ``MONGODB_MAX_IDLE_TIME_MS`` / ``MONGODB_WAIT_QUEUE_TIMEOUT_MS`` / ``MONGODB_SERVER_SELECTION_TIMEOUT_MS`` / ``MONGODB_SOCKET_TIMEOUT_MS`` / ``MONGODB_CONNECT_TIMEOUT_MS`` / ``MONGODB_RETRY_WRITES`` / ``MONGODB_RETRY_READS`` / ``MONGODB_APPNAME`` – כוונון Pooling ו‑Timeouts ל‑MongoDB. ראו :doc:`environment-variables` לברירות מחדל ודוגמאות.
- ``REDIS_URL``: Redis connection string. Use ``rediss://`` with TLS in production.
- ``REDIS_MAX_CONNECTIONS`` / ``REDIS_CONNECT_TIMEOUT`` / ``REDIS_SOCKET_TIMEOUT`` / ``SAFE_MODE`` – גודל Pool ו‑Timeouts ל‑Redis.

.. note::
   בעבודה עם Docker/Compose הגדירו כתובות ע״י שמות השירותים (למשל ``redis://redis:6379`` או ``mongodb://mongo:27017``) — לא להשתמש ב‑``localhost`` בין קונטיינרים.

HTTP Clients
------------

- Async (``aiohttp``): ``AIOHTTP_POOL_LIMIT`` / ``AIOHTTP_LIMIT_PER_HOST`` / ``AIOHTTP_TIMEOUT_TOTAL``
- Sync (``requests`` via ``http_sync``): ``REQUESTS_POOL_CONNECTIONS`` / ``REQUESTS_POOL_MAXSIZE`` / ``REQUESTS_TIMEOUT`` / ``REQUESTS_RETRIES`` / ``REQUESTS_RETRY_BACKOFF``

שימוש ב‑http_async (Async HTTP)
-------------------------------

בעת ביצוע קריאות א-סינכרוניות השתמשו ב‑``http_async`` המספק ``aiohttp.ClientSession`` משותף עם הגדרות מ‑ENV.

הנחיות:

- אל תפתחו ``aiohttp.ClientSession`` ישירות; קבלו אותו דרך ``http_async.get_session()``.
- סגירה מתבצעת אוטומטית ב‑atexit; לסגירה ידנית (למשל בטסטים/teardown) השתמשו ב‑``await http_async.close_session()``.
- פרמטרים: ``AIOHTTP_TIMEOUT_TOTAL`` (ברירת מחדל 10s), ``AIOHTTP_POOL_LIMIT`` (50), ``AIOHTTP_LIMIT_PER_HOST`` (0=ללא מגבלה per‑host).
- בבדיקות/ריסטארטים חמים: אם מופיעה השגיאה "attached to a different loop" — סגרו את הסשן ואז קבלו חדש.

דוגמה קצרה::

   from http_async import get_session
   session = get_session()
   async with session.get("https://api.example.com/data") as resp:
       data = await resp.json()

שימוש ב‑http_sync (Sync HTTP)
-----------------------------

בעת ביצוע קריאות סינכרוניות מומלץ להשתמש במודול ``http_sync`` שמספק ``requests.Session`` גלובלי עם Pool ו‑Retries מוגדרים לפי ENV.

דוגמה קצרה::

   from http_sync import request
   resp = request('GET', 'https://api.example.com/data', headers={'Accept': 'application/json'})
   data = resp.json()

Flask
-----

- Uses Flask-Limiter with ``storage_uri`` pointing to ``REDIS_URL`` when set, otherwise in-memory fallback.
- 429 handler returns JSON with ``error``, ``message``, and ``retry_after`` fields.
- Health and metrics endpoints are exempt from limiting.

Telegram Bot
------------

- Keeps the existing lightweight in-memory limiter for a fast gate.
- If ``limits`` + Redis are available and ``REDIS_URL`` is set, a per-user global limiter runs in shadow mode for visibility.

Metrics
-------

- ``rate_limit_hits_total{source,scope,limit,result}``
- ``rate_limit_blocked_total{source,scope,limit}``

Security
--------

- Always use ``rediss://`` in production (Render Redis supports TLS).
- Keep ``ADMIN_USER_IDS`` minimal.

Databases and Cache (Pooling/Timeouts)
--------------------------------------

- ``MONGODB_URL``: MongoDB connection string (``mongodb://`` or ``mongodb+srv://``)
- ``MONGODB_MAX_POOL_SIZE`` / ``MONGODB_MIN_POOL_SIZE`` / ``MONGODB_MAX_IDLE_TIME_MS`` / ``MONGODB_WAIT_QUEUE_TIMEOUT_MS`` / ``MONGODB_SERVER_SELECTION_TIMEOUT_MS`` / ``MONGODB_SOCKET_TIMEOUT_MS`` / ``MONGODB_CONNECT_TIMEOUT_MS`` / ``MONGODB_RETRY_WRITES`` / ``MONGODB_RETRY_READS`` / ``MONGODB_APPNAME`` – כוונון Pooling ו‑Timeouts ל‑MongoDB. ראו :doc:`environment-variables` לברירות מחדל ודוגמאות.
- ``REDIS_URL``: Redis connection string (use ``rediss://`` with TLS in production).
- ``REDIS_MAX_CONNECTIONS`` / ``REDIS_CONNECT_TIMEOUT`` / ``REDIS_SOCKET_TIMEOUT`` / ``SAFE_MODE`` – גודל Pool ו‑Timeouts ל‑Redis.

.. note::
   בעבודה עם Docker/Compose הגדירו כתובות ע"י שמות השירותים (למשל ``redis://redis:6379`` או ``mongodb://mongo:27017``) — אל תשתמשו ב‑``localhost`` בין קונטיינרים.

HTTP Clients
------------

- Async (``aiohttp``): ``AIOHTTP_POOL_LIMIT`` / ``AIOHTTP_LIMIT_PER_HOST`` / ``AIOHTTP_TIMEOUT_TOTAL``
- Sync (``requests`` via ``http_sync``): ``REQUESTS_POOL_CONNECTIONS`` / ``REQUESTS_POOL_MAXSIZE`` / ``REQUESTS_TIMEOUT`` / ``REQUESTS_RETRIES`` / ``REQUESTS_RETRY_BACKOFF``

שימוש ב-http_sync (Sync HTTP)
-----------------------------

בעת ביצוע קריאות סינכרוניות מומלץ להשתמש במודול ``http_sync`` שמספק ``requests.Session`` גלובלי עם Pool ו‑Retries מוגדרים לפי ENV.

דוגמה קצרה::

   from http_sync import request
   resp = request('GET', 'https://api.example.com/data', headers={'Accept': 'application/json'})
   data = resp.json()

Config via Pydantic Settings
============================

הפרויקט משתמש ב-``pydantic-settings`` לטעינת קונפיגורציה בצורה עקבית בכל השכבות (בוט/ווב/שירותים).

היררכיית טעינה
---------------

- שרשור קבצים/ENV לפי הסדר: ``.env.local`` → ``.env`` → משתני סביבה
- טיפוסים מאומתים אוטומטית בזמן טעינה (Validation)

דוגמה (מצומצם) מתוך ``config.py``::

   class BotConfig(BaseSettings):
       BOT_TOKEN: str
       MONGODB_URL: str
       REDIS_URL: str | None = None
       RATE_LIMIT_ENABLED: bool = True
       RATE_LIMIT_SHADOW_MODE: bool = False

   def load_config() -> BotConfig:
       return BotConfig()

ולידציות
---------

- ``MONGODB_URL`` חייב להתחיל ב-``mongodb://`` או ``mongodb+srv://`` – אחרת תיזרק שגיאת ולידציה.

.env.example
------------

מומלץ לעדכן קובץ דוגמה ``.env.example`` עם השדות העיקריים (ללא סודות):

::

   BOT_TOKEN=changeme
   MONGODB_URL=mongodb://localhost:27017/codebot
   REDIS_URL=
   RATE_LIMIT_ENABLED=true
   RATE_LIMIT_SHADOW_MODE=true
   ADMIN_USER_IDS=

שימוש לסוכנים
-------------

- סוכן AI צריך להסתמך על API אחיד של ``config`` כדי למנוע פערים בין שכבות.
- אין להטמיע סודות בקוד; שימוש ב-ENV בלבד.

פרמטרי קונפיגורציה מרכזיים (חדשים)
------------------------------------
להלן פרמטרים שנוספו ל־``config.py`` ומומלץ להכיר:

- ``AIOHTTP_POOL_LIMIT`` – גודל בריכת חיבורים ברירת מחדל ל‑aiohttp
- ``AIOHTTP_TIMEOUT_TOTAL`` – Timeout כולל לשיחות aiohttp (שניות)
- ``REDIS_MAX_CONNECTIONS`` / ``REDIS_CONNECT_TIMEOUT`` / ``REDIS_SOCKET_TIMEOUT`` – כוונון חיבורי Redis
- ``SEARCH_PAGE_SIZE`` – גודל דף ברירת מחדל לעימוד חיפוש בצד ה‑DB
- ``UI_PAGE_SIZE`` – גודל דף ברירת מחדל לרשימות ב‑UI

איחוד תיעוד קונפיגורציה
------------------------
- עמוד זה (:doc:`configuration`) מספק הסברים ו‑best‑practices.
- עמוד :doc:`environment-variables` מכיל טבלת רפרנס מלאה עם דוגמאות.
- מומלץ להתחיל מכאן ואז לעבור לרפרנס לפי צורך.
