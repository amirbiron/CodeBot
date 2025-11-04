ביצועים והרחבה (Performance & Scaling)
=======================================

עימוד (Pagination)
-------------------
- ברירת מחדל: ``SEARCH_PAGE_SIZE`` (ראו `config.py`).
- דפוס איטרטיבי: משיכת דפים עוקבים עד מיצוי, תוך שמירה על זיכרון נמוך.
- לממשקי UI: השתמשו ב-``UI_PAGE_SIZE`` לתצוגות רשימה.

Projection
----------
- צמצמו I/O וזיכרון בעזרת ``projection`` בשאילתות Mongo.
- העדיפו להחזיר רק את השדות הנדרשים למסך/לשירות קורא.
- שמרו על תאימות לאחור: אל תשנו payloads קיימים בלי לעדכן את הצרכנים.

דגשים
------
- בחרו אינדקסים תואמי עימוד (ראו :doc:`database/indexing`).
- הימנעו מ-``COLLSCAN`` בדפים מאוחרים; הסלמה ל-cursor/אינדקס משולב.
- מדדו באמצעות Prometheus/Jaeger כדי לאתר צווארי בקבוק.

כוונון Connection Pooling ו-Timeouts
------------------------------------

- MongoDB:
  - התחילו מ-``MONGODB_MAX_POOL_SIZE=100`` ו-``MONGODB_MIN_POOL_SIZE=5``.
  - ``MONGODB_WAIT_QUEUE_TIMEOUT_MS=5000`` כדי למנוע המתנות ארוכות.
  - עקבו אחרי ``connPoolStats`` וטעינת שרת DB.
- Redis:
  - ``REDIS_MAX_CONNECTIONS=50~200`` לפי עומס. השאירו ``health_check_interval=30`` (בקוד).
  - ``REDIS_CONNECT_TIMEOUT``/``REDIS_SOCKET_TIMEOUT`` שמרניים. ב-``SAFE_MODE`` ברירות מחדל נמוכות יותר.
- HTTP Async (aiohttp):
  - ``AIOHTTP_POOL_LIMIT=50~100`` ו-``AIOHTTP_LIMIT_PER_HOST=25``.
  - ``AIOHTTP_TIMEOUT_TOTAL=12~15`` לייצוב תחת עומס.
- HTTP Sync (requests via http_sync):
  - ``REQUESTS_POOL_CONNECTIONS=20`` ו-``REQUESTS_POOL_MAXSIZE=100``.
  - ``REQUESTS_RETRIES=2`` עם ``REQUESTS_RETRY_BACKOFF=0.2``.

לוגי איטיות (מהיר לאיתור צווארי בקבוק)
---------------------------------------

- WebApp Flask: הגדירו ``SLOW_MS`` (למשל ``500``) כדי לרשום בקשות איטיות כ-``slow_request`` עם path/method/status/ms.
- HTTP סינכרוני: הגדירו ``HTTP_SLOW_MS`` (למשל ``400``) כדי לרשום ``slow_http`` עם method/url/status/ms.
- MongoDB: הגדירו ``DB_SLOW_MS`` (למשל ``20``) כדי לרשום ``slow_mongo`` דרך CommandListener.

טיפים:
- התחילו בספים שמרניים בפרוד והורידו/העלו בהתאם לרעש/תועלת.
- רגישו מידע: הלוגים אינם כוללים כותרות/סודות; מומלץ לא לכלול query params רגישים ב-URLים.

בדיקות מהירות אחרי שינוי ENV
------------------------------

בדקו לוגים ומדדים לאחר עדכון ערכי Pool/Timeout:

- MongoDB: עלייה ב-``waitQueueTimeout``, ``serverSelectionTimeout`` → הגדילו ``MAX_POOL_SIZE`` או בדקו אינדקסים.
- Redis: ``connected_clients``, ``latency``. אם יש Timeouts – הקטינו עומס או הגדילו Pool.
- HTTP: יחס 5xx/429 ו-Latency. ודאו שימוש ב-Session משותף (aiohttp/requests) לשימור Keep‑Alive.

הנחיות לפי סביבה
-----------------

- Dev: ערכים נמוכים לשמירת משאבים מקומיים.
- Staging: קרוב לפרוד עם Monitoring מודגש.
- Production: התאם לערכי עומס אמיתי; הגדל בהדרגה וצפה במדדים.
