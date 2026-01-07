משתני סביבה - רפרנס
=====================

.. note::
   בכל פעם שמוסיפים או משנים משתני סביבה בקוד/Infra **חייבים** לעדכן עמוד זה (רפרנס משתני הסביבה) וכן לציין זאת ב-PR. בכך אנו מבטיחים שהמידע הופך ל-Single Source of Truth גם למפתחים וגם לאנשי DevOps.

טבלה מרכזית
------------

.. list-table:: Environment Variables
   :header-rows: 1

   * - משתנה
     - תיאור
     - חובה
     - ברירת מחדל
     - דוגמה
     - רכיב
   * - ``BOT_TOKEN``
     - טוקן הבוט מ-BotFather
     - כן
     - -
     - ``123456:ABC-DEF...``
     - Bot
   * - ``MONGODB_URL``
     - חיבור ל-MongoDB
     - כן
     - -
     - ``mongodb://localhost:27017``
     - Bot/WebApp
   * - ``MONGODB_MAX_POOL_SIZE``
     - גודל בריכת חיבורים מקסימלי ל‑MongoDB (maxPoolSize)
     - לא
     - ``50``
     - ``100``
     - Bot/WebApp
   * - ``MONGODB_MIN_POOL_SIZE``
     - גודל בריכת חיבורים מינימלי ל‑MongoDB (minPoolSize)
     - לא
     - ``5``
     - ``5``
     - Bot/WebApp
   * - ``MONGODB_MAX_IDLE_TIME_MS``
     - זמן השהייה מקסימלי בחוסר שימוש (maxIdleTimeMS)
     - לא
     - ``30000``
     - ``30000``
     - Bot/WebApp
   * - ``MONGODB_WAIT_QUEUE_TIMEOUT_MS``
     - זמן המתנה בתור ה‑Pool לפני כישלון (waitQueueTimeoutMS)
     - לא
     - ``8000``
     - ``10000``
     - Bot/WebApp
   * - ``MONGODB_SERVER_SELECTION_TIMEOUT_MS``
     - זמן בחירת שרת (serverSelectionTimeoutMS)
     - לא
     - ``5000``
     - ``5000``
     - Bot/WebApp
   * - ``MONGODB_SOCKET_TIMEOUT_MS``
     - זמן קצוב לקריאת/כתיבת שקע (socketTimeoutMS)
     - לא
     - ``45000``
     - ``45000``
     - Bot/WebApp
   * - ``MONGODB_CONNECT_TIMEOUT_MS``
     - זמן קצוב להתחברות (connectTimeoutMS)
     - לא
     - ``5000``
     - ``10000``
     - Bot/WebApp
   * - ``MONGODB_RETRY_WRITES``
     - הפעלת Retry לכתיבות (retryWrites)
     - לא
     - ``true``
     - ``true``
     - Bot/WebApp
   * - ``MONGODB_RETRY_READS``
     - הפעלת Retry לקריאות (retryReads)
     - לא
     - ``true``
     - ``true``
     - Bot/WebApp
   * - ``MONGODB_APPNAME``
     - שם אפליקציה לצורך Telemetry/Metadata ב‑MongoDB
     - לא
     - "" (ריק)
     - ``CodeBot``
     - Bot/WebApp
   * - ``DATABASE_NAME``
     - שם בסיס נתונים
     - לא
     - ``code_keeper_bot``
     - ``my_db``
     - Bot/WebApp
   * - ``SECRET_KEY``
     - מפתח הצפנה ל-Flask/WebApp
     - כן (WebApp)
     - -
     - ``supersecretkey123``
     - WebApp
   * - ``BOT_USERNAME``
     - שם משתמש הבוט
     - לא
     - ``my_code_keeper_bot``
     - ``@MyBot``
     - Bot/WebApp
   * - ``TELEGRAM_CONNECT_TIMEOUT_SECS``
     - טיימאאוט התחברות ל‑Telegram Bot API (שניות). מעלה סבילות לבעיות רשת קצרות.
     - לא
     - ``10.0``
     - ``10.0``
     - Bot
   * - ``TELEGRAM_POOL_TIMEOUT_SECS``
     - טיימאאוט המתנה ל‑connection מה‑pool (שניות) בעת קריאות ל‑Telegram Bot API.
     - לא
     - ``10.0``
     - ``10.0``
     - Bot
   * - ``TELEGRAM_READ_TIMEOUT_SECS``
     - טיימאאוט קריאה ל‑Telegram Bot API (שניות). מומלץ שיהיה גבוה מ‑``TELEGRAM_LONG_POLL_TIMEOUT_SECS`` כדי להקטין סיכוי ל‑``getUpdates`` Conflict בזמן "גיהוק" רשת.
     - לא
     - ``30.0``
     - ``30.0``
     - Bot
   * - ``TELEGRAM_WRITE_TIMEOUT_SECS``
     - טיימאאוט כתיבה ל‑Telegram Bot API (שניות).
     - לא
     - ``30.0``
     - ``30.0``
     - Bot
   * - ``TELEGRAM_LONG_POLL_TIMEOUT_SECS``
     - ``timeout`` של long‑polling עבור ``getUpdates`` (שניות). זה זמן ההמתנה בצד שרת Telegram לפני החזרת עדכונים.
     - לא
     - ``20``
     - ``20``
     - Bot
   * - ``TELEGRAM_POLL_INTERVAL_SECS``
     - ``poll_interval`` בין סבבי polling (שניות). ``0`` = ברירת מחדל של python-telegram-bot.
     - לא
     - ``0.0``
     - ``0.0``
     - Bot
   * - ``TELEGRAM_CONFLICT_BACKOFF_SECS``
     - זמן המתנה (שניות) לפני retry כאשר מתקבלת שגיאת ``409 Conflict`` מסוג "terminated by other getUpdates request".
     - לא
     - ``30``
     - ``30``
     - Bot
   * - ``TELEGRAM_CONFLICT_MAX_RETRIES``
     - כמה פעמים לנסות שוב (retry) אחרי ``409 Conflict``. אם מגיעים לתקרה — התהליך יוצא כדי לשחרר lock ולאפשר ל‑orchestrator לנסות התאוששות. ``0``/שלילי = ללא הגבלה (לא מומלץ).
     - לא
     - ``5``
     - ``5``
     - Bot
   * - ``TELEGRAM_CONFLICT_MAX_SECONDS``
     - חלון זמן מקסימלי (שניות) לרצף conflicts לפני יציאה מהתהליך (שחרור lock + recovery). ``0``/שלילי = ללא הגבלה (לא מומלץ).
     - לא
     - ``300``
     - ``300``
     - Bot
   * - ``GITHUB_TOKEN``
     - טוקן GitHub לשימוש בפעולות API. למינימום הרשאות ראו טבלת Scopes בהמשך.
     - לא
     - -
     - ``ghp_xxx...``
     - Bot
   * - ``WEBAPP_URL``
     - כתובת ה-WebApp
     - לא
     - -
     - ``https://my.app``
     - WebApp
   * - ``BOT_JOBS_API_BASE_URL``
     - בסיס URL ל-API הפנימי של הבוט (aiohttp) עבור Trigger של Jobs ממסך המוניטור (``POST /api/jobs/<job_id>/trigger``). אם לא מוגדר, כפתור ההפעלה ידנית במוניטור יהיה לא זמין.
     - לא
     - -
     - ``http://127.0.0.1:8080``
     - WebApp
   * - ``BOT_API_BASE_URL``
     - Alias/תאימות לאחור ל-``BOT_JOBS_API_BASE_URL`` (נבדק רק אם ``BOT_JOBS_API_BASE_URL`` ריק).
     - לא
     - -
     - ``http://127.0.0.1:8080``
     - WebApp
   * - ``WEBAPP_ENABLE_WARMUP``
     - הפעלת שלב warmup אוטומטי אחרי עליית Gunicorn (``1``/``0``)
     - לא
     - ``1``
     - ``0``
     - WebApp
   * - ``WEBAPP_WARMUP_URL``
     - יעד curl לבדיקת הבריאות הראשונית (ברירת מחדל ``http://127.0.0.1:$PORT/healthz``)
     - לא
     - ``http://127.0.0.1:$PORT/healthz``
     - ``https://internal.lb/healthz``
     - WebApp
   * - ``WEBAPP_WARMUP_MAX_ATTEMPTS``
     - מספר ניסיונות curl עבור בדיקת הבריאות
     - לא
     - ``15``
     - ``10``
     - WebApp
   * - ``WEBAPP_WARMUP_DELAY_SECONDS``
     - השהיה בין ניסיונות ה-warmup הראשיים (שניות)
     - לא
     - ``2``
     - ``5``
     - WebApp
   * - ``WEBAPP_WARMUP_BASE_URL``
     - בסיס ה-URL לבקשות ה-Frontend Warmup
     - לא
     - ``http://127.0.0.1:$PORT``
     - ``https://code-keeper-webapp.onrender.com``
     - WebApp
   * - ``WEBAPP_WSGI_APP``
     - מודול ה-WSGI של Flask עבור Gunicorn (בשימוש ``scripts/start_webapp.sh``)
     - לא
     - ``app:app``
     - ``app:app``
     - WebApp
   * - ``WEB_CONCURRENCY``
     - מספר ה-workers של Gunicorn ב-WebApp. אם מוגדר, גובר על ברירת המחדל של ``scripts/start_webapp.sh`` ומקטין ``queue_delay`` תחת עומס.
     - לא
     - ``2``
     - ``4``
     - WebApp
   * - ``WEBAPP_GUNICORN_WORKERS``
     - מספר ה-workers של Gunicorn (חלופה ל-``WEB_CONCURRENCY``)
     - לא
     - ``2``
     - ``4``
     - WebApp
   * - ``WEBAPP_GUNICORN_THREADS``
     - מספר Threads לכל worker כאשר משתמשים ב-``gthread`` (משפר מקביליות לבקשות I/O)
     - לא
     - ``2``
     - ``8``
     - WebApp
   * - ``WEBAPP_GUNICORN_WORKER_CLASS``
     - Worker class של Gunicorn (ברירת מחדל ``gthread``)
     - לא
     - ``gthread``
     - ``gthread``
     - WebApp
   * - ``WEBAPP_GUNICORN_TIMEOUT``
     - Timeout (שניות) לבקשה ב-Gunicorn
     - לא
     - ``60``
     - ``90``
     - WebApp
   * - ``WEBAPP_GUNICORN_KEEPALIVE``
     - keep-alive (שניות) לחיבורים ב-Gunicorn
     - לא
     - ``2``
     - ``5``
     - WebApp
   * - ``OBSERVABILITY_WARMUP_ENABLED``
     - הפעלה/כיבוי של Warmup “כבד” לדוחות Observability (למילוי קאש ו‑RAM) ברקע אחרי עליית התהליך
     - לא
     - ``true``
     - ``false``
     - WebApp
   * - ``OBSERVABILITY_WARMUP_DELAY_SECONDS``
     - השהייה (שניות) לפני תחילת Warmup הדוחות כדי לא להעמיס בזמן העלייה
     - לא
     - ``5``
     - ``10``
     - WebApp
   * - ``OBSERVABILITY_WARMUP_BUDGET_SECONDS``
     - תקציב זמן מקסימלי (שניות) ל‑Warmup הדוחות ברקע; מעבר לתקציב נעצור מוקדם
     - לא
     - ``20``
     - ``30``
     - WebApp
   * - ``OBSERVABILITY_WARMUP_RANGES``
     - רשימת טווחי זמן (CSV) לחימום ``/api/observability/aggregations`` (למשל ``24h,7d,30d``)
     - לא
     - ``24h,7d,30d``
     - ``24h,7d``
     - WebApp
   * - ``OBSERVABILITY_WARMUP_SLOW_LIMIT``
     - ערך ``slow_endpoints_limit`` עבור החימום (ברירת מחדל כמו ב‑API)
     - לא
     - ``5``
     - ``10``
     - WebApp
   * - ``ALERT_TAGS_COLLECTION``
     - שם ה-Collection לתגיות התראות (Manual Alert Tagging) ב-Observability.
     - לא
     - ``alert_tags``
     - ``alert_tags``
     - WebApp/Observability
   * - ``ALERT_TAGS_DB_DISABLED``
     - אם ``true`` מכבה שמירה/שליפה של תגיות להתראות (Manual Alert Tagging) מה-DB.
     - לא
     - ``false``
     - ``true``
     - WebApp/Observability
   * - ``PUBLIC_BASE_URL``
     - כתובת בסיס ציבורית ליצירת קישורי שיתוף
     - לא
     - "" (ריק)
     - ``https://share.example.com``
     - WebApp
   * - ``WEEKLY_TIP_ENABLED``
     - מתג כללי להצגת רכיב ההכרזות (on/off)
     - לא
     - ``true``
     - ``true``
     - WebApp
   * - ``PUBLIC_SHARE_TTL_DAYS``
     - תוקף ברירת מחדל לקישורי שיתוף (ימים)
     - לא
     - ``7``
     - ``14``
     - WebApp
   * - ``ADMIN_USER_IDS``
     - מזהי משתמש טלגרם עם הרשאות אדמין (CSV)
     - לא
     - "" (ריק)
     - ``123,456``
     - Bot/WebApp
   * - ``DB_HEALTH_TOKEN``
     - טוקן להגנה על נתיבים פנימיים רגישים בשרת ה-aiohttp: ``/api/db/*`` וגם ``/api/jobs/*`` (נשלח כ-``Authorization: Bearer <token>``). ללא טוקן ה-API חסום (403) והדשבורד ``/db-health`` יחזיר 403.
     - כן (DB Health)
     - "" (ריק)
     - ``db_health_super_secret_token``
     - Bot/WebApp
   * - ``DB_HEALTH_SLOW_THRESHOLD_MS``
     - סף ברירת מחדל לזיהוי slow queries (באלפיות שנייה) עבור ``currentOp``.
     - לא
     - ``1000``
     - ``1500``
     - Bot/WebApp
   * - ``DB_HEALTH_POOL_REFRESH_SEC``
     - תדירות רענון מומלצת (שניות) לסטטוס ה-pool בדשבורד. (משתנה תיעודי/קונפיגורציה כללית)
     - לא
     - ``5``
     - ``5``
     - WebApp
   * - ``DB_HEALTH_OPS_REFRESH_SEC``
     - תדירות רענון מומלצת (שניות) לרשימת slow queries בדשבורד. (משתנה תיעודי/קונפיגורציה כללית)
     - לא
     - ``10``
     - ``10``
     - WebApp
   * - ``DB_HEALTH_COLLECTIONS_COOLDOWN_SEC``
     - זמן Cooldown (שניות) בין קריאות ל-``/api/db/collections`` (פעולת ``collStats``). קריאה נוספת בתוך החלון תחזיר ``429`` עם Header ``Retry-After``.
     - לא
     - ``30``
     - ``30``
     - WebApp
   * - ``PREMIUM_USER_IDS``
     - מזהי משתמש טלגרם לסטטוס פרימיום (CSV)
     - לא
     - "" (ריק)
     - ``123,456``
     - WebApp
   * - ``FA_SRI_HASH``
     - ערך SRI עבור ספריית אייקונים (למשל FontAwesome)
     - לא
     - "" (ריק)
     - ``sha384-...``
     - WebApp
   * - ``UPTIME_PROVIDER``
     - ספק ניטור (למשל ``betteruptime``)
     - לא
     - "" (ריק)
     - ``betteruptime``
     - WebApp
   * - ``UPTIME_API_KEY``
     - מפתח API לשירות הניטור (אם רלוונטי)
     - לא
     - "" (ריק)
     - ``bu_apikey_xxx``
     - WebApp
   * - ``UPTIME_MONITOR_ID``
     - מזהה מוניטור
     - לא
     - "" (ריק)
     - ``abc123``
     - WebApp
   * - ``UPTIME_STATUS_URL``
     - קישור לעמוד סטטוס ציבורי
     - לא
     - "" (ריק)
     - ``https://status.example.com``
     - WebApp
   * - ``UPTIME_WIDGET_SCRIPT_URL``
     - כתובת סקריפט הווידג'ט לעמודי סטטוס
     - לא
     - ``https://uptime.betterstack.com/widgets/announcement.js``
     - ``https://.../widget.js``
     - WebApp
   * - ``UPTIME_WIDGET_ID``
     - מזהה ווידג'ט (data-id)
     - לא
     - "" (ריק)
     - ``abcd-1234``
     - WebApp
   * - ``UPTIME_CACHE_TTL_SECONDS``
     - TTL למטמון תוצאות Uptime
     - לא
     - ``120`` (מינימום 30)
     - ``300``
     - WebApp
   * - ``VAPID_PUBLIC_KEY``
     - מפתח ציבורי ל‑Web Push (VAPID)
     - לא
     - "" (ריק)
     - ``BExxx...``
     - WebApp
   * - ``VAPID_PRIVATE_KEY``
     - מפתח פרטי ל‑Web Push (VAPID)
     - לא
     - "" (ריק)
     - ``xxxxxxxx``
     - WebApp
   * - ``VAPID_SUB_EMAIL``
     - Subject (דוא"ל) לתביעות VAPID
     - לא
     - "" (ריק)
     - ``support@example.com``
     - WebApp
   * - ``PUSH_NOTIFICATIONS_ENABLED``
     - הפעלת שליחת Web Push (רקע)
     - לא
     - ``true``
     - ``false``
     - WebApp
   * - ``PUSH_REMOTE_DELIVERY_ENABLED``
     - שליחה דרך Worker חיצוני (במקום pywebpush)
     - לא
     - ``false``
     - ``true``
     - WebApp
   * - ``PUSH_DELIVERY_URL``
     - כתובת בסיס ל‑Worker (ללא ``/send``)
     - לא
     - "" (ריק)
     - ``https://code-keeper-push-worker.onrender.com``
     - WebApp
   * - ``PUSH_DELIVERY_TOKEN``
     - טוקן Bearer לאימות שרת→Worker
     - לא
     - "" (ריק)
     - ``s3cr3t-token``
     - WebApp/Worker
   * - ``PUSH_DELIVERY_TIMEOUT_SECONDS``
     - Timeout לבקשת ``/send`` ל‑Worker (שניות)
     - לא
     - ``3``
     - ``2``
     - WebApp
   * - ``PUSH_WORKER_PORT``
     - פורט פנימי ל‑Sidecar Worker (localhost בלבד)
     - לא
     - ``18080``
     - ``18080``
     - WebApp/Worker
   * - ``WORKER_VAPID_PUBLIC_KEY``
     - מפתח ציבורי ל‑VAPID עבור ה‑Worker (Sidecar)
     - לא
     - "" (ריק)
     - ``BExxx...``
     - Worker
   * - ``WORKER_VAPID_PRIVATE_KEY``
     - מפתח פרטי ל‑VAPID עבור ה‑Worker (Sidecar)
     - לא
     - "" (ריק)
     - ``xxxxxxxx``
     - Worker
   * - ``WORKER_VAPID_SUB_EMAIL``
     - Subject (דוא"ל) לתביעות VAPID עבור ה‑Worker
     - לא
     - ``support@example.com``
     - ``alerts@example.com``
     - Worker
   * - ``PERSISTENT_LOGIN_DAYS``
     - תוקף התחברות מתמשכת (ימים)
     - לא
     - ``180`` (מינימום 30)
     - ``365``
     - WebApp
   * - ``PORT``
     - פורט להרצת ה-WebApp
     - לא
     - ``5000``
     - ``8080``
     - WebApp
   * - ``DEBUG``
     - מצב דיבאג ל-WebApp
     - לא
     - ``false``
     - ``true``
     - WebApp
   * - ``REDIS_URL``
     - חיבור ל-Redis (cache)
     - לא
     - -
     - ``redis://localhost:6379``
     - Bot
   * - ``REDIS_CONNECT_TIMEOUT``
     - Timeout התחברות ל-Redis (שניות)
     - לא
     - ``3`` (או ``1`` ב-``SAFE_MODE``)
     - ``2``
     - Bot/WebApp
   * - ``REDIS_SOCKET_TIMEOUT``
     - Timeout קריאת שקע ל-Redis (שניות)
     - לא
     - ``5`` (או ``1`` ב-``SAFE_MODE``)
     - ``2``
     - Bot/WebApp
   * - ``SAFE_MODE``
     - מצב שמרני: מוריד ברירות מחדל של Timeouts לטובת יציבות בסביבות חלשות
     - לא
     - ``false``
     - ``true``
     - Bot/WebApp
   * - ``CACHE_ENABLED``
     - הפעלת קאש פנימי
     - לא
     - ``false``
     - ``true``
     - Bot/WebApp
   * - ``CACHE_CLEAR_BUDGET_SECONDS``
     - תקציב זמן לניקוי קאש (מונע תקיעה ב-Redis)
     - לא
     - ``5``
     - ``1``
     - Bot/WebApp
   * - ``CACHE_DELETE_PATTERN_BUDGET_SECONDS``
     - תקציב זמן למחיקת תבנית מפתחות בקאש (SCAN+DEL) כדי למנוע תקיעה ב-Redis גדול
     - לא
     - ``5`` (נופל ל-``CACHE_CLEAR_BUDGET_SECONDS`` אם לא מוגדר)
     - ``1``
     - Bot/WebApp
   * - ``DISABLE_BACKGROUND_CLEANUP``
     - דילוג כולל על עבודות ניקוי רקע (קאש/גיבויים)
     - לא
     - ``false``
     - ``true``
     - Bot
   * - ``JOBS_STUCK_THRESHOLD_MINUTES``
     - סף (בדקות) לזיהוי הרצות Jobs "תקועות" והפקת אירוע ``job_stuck`` (נבדק מול ``job_runs`` ב-DB).
     - לא
     - ``20``
     - ``30``
     - Bot
   * - ``JOBS_STUCK_MONITOR_INTERVAL_SECS``
     - תדירות הריצה (שניות) של מוניטור Jobs "תקועות" שמפיק ``job_stuck``.
     - לא
     - ``60``
     - ``120``
     - Bot
   * - ``CACHE_MAINT_INTERVAL_SECS``
     - מרווח בין ריצות תחזוקת קאש (שניות)
     - לא
     - ``600`` (מינימום 60)
     - ``300``
     - Bot
   * - ``CACHE_MAINT_FIRST_SECS``
     - דיליי לפני הרצת תחזוקת קאש הראשונה (שניות)
     - לא
     - ``30``
     - ``10``
     - Bot
   * - ``CACHE_MAINT_MAX_SCAN``
     - מספר מפתחות מקסימלי לסריקה ב-clear_stale
     - לא
     - ``1000``
     - ``5000``
     - Bot
   * - ``CACHE_MAINT_TTL_THRESHOLD``
     - TTL (בשניות) מתחתיו ייחשב "שבק״ לניקוי עדין
     - לא
     - ``60``
     - ``120``
     - Bot
   * - ``BACKUPS_CLEANUP_ENABLED``
     - הפעלת ניקוי גיבויי ZIP ברקע
     - לא
     - ``false`` (כבוי כברירת מחדל)
     - ``true``
     - Bot
   * - ``BACKUPS_CLEANUP_INTERVAL_SECS``
     - מרווח בין ריצות ניקוי גיבויים (שניות)
     - לא
     - ``86400`` (מינימום 3600)
     - ``43200``
     - Bot
   * - ``BACKUPS_CLEANUP_FIRST_SECS``
     - דיליי לפני ריצת ניקוי גיבויים הראשונה (שניות)
     - לא
     - ``180``
     - ``60``
     - Bot
   * - ``BACKUPS_RETENTION_DAYS``
     - ימי שמירת ארכיבי גיבוי בדיסק/GridFS לפני מחיקה
     - לא
     - ``30`` (מינימום 1)
     - ``14``
     - Bot
   * - ``BACKUPS_MAX_PER_USER``
     - מספר גיבויים מקסימלי לשמירה לכל משתמש (מעבר יימחקו הוותיקים)
     - לא
     - ``None`` (ביטול מגבלה)
     - ``10``
     - Bot
   * - ``BACKUPS_CLEANUP_BUDGET_SECONDS``
     - תקציב זמן לניקוי גיבויים (מונע עומס)
     - לא
     - ``3``
     - ``5``
     - Bot
   * - ``BACKUPS_DISK_MIN_FREE_BYTES``
     - סף (ב־bytes) להתראת "דיסק כמעט מלא" לפני שמירת ZIP
     - לא
     - ``209715200`` (200MB)
     - ``314572800`` (300MB)
     - Bot
   * - ``DISABLE_CACHE_MAINTENANCE``
     - דילוג על פעולות ניקוי קאש (לוג בלבד)
     - לא
     - ``false``
     - ``true``
     - Bot/WebApp
   * - ``DISABLE_PREEMPTIVE_ACTIONS``
     - דילוג על פעולות מנע (PHE) כמו ניקוי קאש
     - לא
     - ``false``
     - ``true``
     - Bot/WebApp
   * - ``LOG_LEVEL``
     - רמת logging (``DEBUG``/``INFO``/``WARNING``/``ERROR``/``CRITICAL`` או ערך מספרי כמו ``10``)
     - לא
     - ``INFO``
     - ``DEBUG``
     - Bot/WebApp
   * - ``LOG_FORMAT``
     - פורמט לוגים (``text``/``json``)
     - לא
     - ``text``
     - ``json``
     - Bot/WebApp
   * - ``LOG_INFO_SAMPLE_RATE``
     - שיעור דגימה ללוגים ברמת ``INFO`` (0.0–1.0)
     - לא
     - ``1.0``
     - ``0.1``
     - Bot/WebApp
   * - ``LOG_INFO_SAMPLE_ALLOWLIST``
     - אירועים שלא נדגמים לעולם (מופרדים בפסיקים)
     - לא
     - ``business_metric,performance,github_sync``
     - ``event_a,event_b``
     - Bot/WebApp
   * - ``ENVIRONMENT``
     - שם הסביבה לדיווחי Sentry/לוגים (``production``/``staging``/``dev``)
     - לא
     - ``production``
     - ``staging``
     - Bot/WebApp
   * - ``MAX_CODE_SIZE``
     - גודל קוד מקסימלי לשמירה (בתווים)
     - לא
     - ``100000``
     - ``200000``
     - Bot
   * - ``MAX_FILES_PER_USER``
     - מגבלת כמות קבצים למשתמש
     - לא
     - ``1000``
     - ``2000``
     - Bot
   * - ``HIGHLIGHT_THEME``
     - ערכת צבעים להדגשת תחביר
     - לא
     - ``github-dark``
     - ``monokai``
     - WebApp
   * - ``GIT_CHECKPOINT_PREFIX``
     - קידומת לשמירת checkpoints
     - לא
     - ``checkpoint``
     - ``ckpt``
     - Bot
   * - ``GOOGLE_CLIENT_ID``
     - OAuth Client ID של Google
     - לא
     - -
     - ``xxx.apps.googleusercontent.com``
     - Integrations
   * - ``GOOGLE_CLIENT_SECRET``
     - OAuth Client Secret של Google
     - לא
     - -
     - ``********``
     - Integrations
   * - ``GOOGLE_OAUTH_SCOPES``
     - מרחבי OAuth לברירת מחדל
     - לא
     - ``https://www.googleapis.com/auth/drive.file``
     - ``...``
     - Integrations
   * - ``GOOGLE_TOKEN_REFRESH_MARGIN_SECS``
     - מרווח חידוש טוקן בטרם פקיעה (שניות)
     - לא
     - ``120``
     - ``300``
     - Integrations
   * - ``DRIVE_MENU_V2``
     - הפעלת תפריט Drive v2
     - לא
     - ``true``
     - ``false``
     - WebApp
   * - ``DOCUMENTATION_URL``
     - קישור לאתר התיעוד הרשמי
     - לא
     - ``https://amirbiron.github.io/CodeBot/``
     - ``https://docs.example.com``
     - WebApp
   * - ``BOT_LABEL``
     - תווית תצוגה לבוט
     - לא
     - ``CodeBot``
     - ``CKB``
     - Bot/WebApp
   * - ``DRIVE_ADD_HASH``
     - הוספת hash לקבצים משותפים
     - לא
     - ``false``
     - ``true``
     - Integrations
   * - ``NORMALIZE_CODE_ON_SAVE``
     - נרמול קוד בשמירה
     - לא
     - ``true``
     - ``false``
     - Bot
   * - ``MAINTENANCE_MODE``
     - מצב תחזוקה המדכא פעולות משתמשים
     - לא
     - ``false``
     - ``true``
     - Bot/WebApp
   * - ``MAINTENANCE_MESSAGE``
     - הודעה למצב תחזוקה
     - לא
     - הודעת ברירת מחדל ידידותית
     - ``"🚀 אנחנו מעלים עדכון חדש!"``
     - WebApp
   * - ``MAINTENANCE_AUTO_WARMUP_SECS``
     - חימום אוטומטי לאחר יציאה מתחזוקה (שניות)
     - לא
     - ``30``
     - ``60``
     - WebApp
   * - ``MAINTENANCE_WARMUP_GRACE_SECS``
     - חלון חסד (שניות) שנוסף ל-warmup כדי לכסות שיהוי איטי בתחילת ריצה
     - לא
     - ``0.75``
     - ``1.5``
     - Bot/WebApp
   * - ``RATE_LIMIT_PER_MINUTE``
     - מגבלת קצב בקשות לדקה
     - לא
     - ``30``
     - ``60``
     - WebApp
   * - ``RECYCLE_TTL_DAYS``
     - ימי שמירת פריטים בסל המחזור
     - לא
     - ``7``
     - ``30``
     - Bot/WebApp
   * - ``REPORTER_MONGODB_URL``
     - URI חלופי ל-reporter (עדיפות על ``MONGODB_URL``)
     - לא
     - -
     - ``mongodb://...``
     - Reporter
   * - ``REPORTER_MONGODB_URI``
     - שם חלופי ל-URI של reporter
     - לא
     - -
     - ``mongodb://...``
     - Reporter
   * - ``REPORTER_SERVICE_ID``
     - מזהה שירות עבור הדוחות
     - לא
     - ``srv-d29d72adbo4c73bcuep0``
     - ``srv-xxxx``
     - Reporter
   * - ``ENABLE_INTERNAL_SHARE_WEB``
     - הפעלת שירות שיתוף פנימי
     - לא
     - ``false``
     - ``true``
     - WebApp
   * - ``PORT``
     - פורט להרצת שירותים פנימיים/בדיקות
     - לא
     - ``10000`` (ב-main), ``5000`` (ב-WebApp)
     - ``8080``
     - Bot/WebApp
   * - ``AIOHTTP_POOL_LIMIT``
     - גודל בריכת חיבורים ל‑aiohttp
     - לא
     - ``50``
     - ``100``
     - Bot/WebApp
   * - ``AIOHTTP_TIMEOUT_TOTAL``
     - Timeout כולל לשיחות aiohttp (שניות)
     - לא
     - ``10``
     - ``30``
     - Bot/WebApp
   * - ``AIOHTTP_LIMIT_PER_HOST``
     - מגבלה פר‑Host לחיבורים במקביל (aiohttp TCPConnector)
     - לא
     - ``0`` (ללא מגבלה פר‑Host)
     - ``25``
     - Bot/WebApp
   * - ``REDIS_MAX_CONNECTIONS``
     - גודל בריכת חיבורים ל‑Redis
     - לא
     - ``50``
     - ``200``
     - Bot/WebApp
   * - ``REQUESTS_POOL_CONNECTIONS``
     - מספר Connection Pools גלובליים ל‑requests (per host)
     - לא
     - ``20``
     - ``20``
     - Bot/WebApp
   * - ``REQUESTS_POOL_MAXSIZE``
     - מקס׳ חיבורים בו‑זמנית בכל Pool (requests)
     - לא
     - ``100``
     - ``100``
     - Bot/WebApp
   * - ``REQUESTS_TIMEOUT``
     - Timeout ברירת מחדל לבקשות סינכרוניות (requests)
     - לא
     - ``8``
     - ``8``
     - Bot/WebApp
   * - ``REQUESTS_RETRIES``
     - מספר ניסיונות Retry על סטטוסים זמניים (5xx)
     - לא
     - ``2``
     - ``2``
     - Bot/WebApp
   * - ``REQUESTS_RETRY_BACKOFF``
     - backoff_factor בין ניסיונות ה‑Retry (שניות)
     - לא
     - ``0.2``
     - ``0.2``
     - Bot/WebApp
   * - ``SLOW_MS``
     - סף מילישניות ללוג "בקשה איטית" ב‑Flask/WebApp
     - לא
     - ``0`` (מכובה)
     - ``500``
     - WebApp
   * - ``HTTP_SLOW_MS``
     - סף מילישניות ללוג "slow_http" ב‑http_sync (requests)
     - לא
     - ``0`` (מכובה)
     - ``400``
     - Bot/WebApp
   * - ``DB_SLOW_MS``
     - סף מילישניות ללוג "slow_mongo" (MongoDB CommandListener)
     - לא
     - ``0`` (מכובה)
     - ``20``
     - Bot/WebApp
   * - ``PROFILER_ENABLED``
     - הפעלת Query Performance Profiler (ניטור שאילתות MongoDB איטיות + דשבורד). ראו :doc:`observability/query-performance-profiler`.
     - לא
     - ``true``
     - ``false``
     - Bot/WebApp
   * - ``PROFILER_SLOW_THRESHOLD_MS``
     - סף זמן (מילישניות) להגדרת "שאילתה איטית" עבור הפרופיילר
     - לא
     - ``100``
     - ``250``
     - Bot/WebApp
   * - ``PROFILER_MAX_BUFFER_SIZE``
     - מספר מקסימלי של רשומות slow queries שנשמרות בזיכרון (Deque) לצורכי UI מהיר
     - לא
     - ``1000``
     - ``2000``
     - Bot/WebApp
   * - ``PROFILER_AUTH_TOKEN``
     - טוקן גישה ל-API של הפרופיילר (נשלח כ-Header ``X-Profiler-Token``). אם ריק, ההגנה מתבססת על הרשאת Admin ב-WebApp.
     - לא
     - "" (ריק)
     - ``replace_me``
     - Bot/WebApp
   * - ``PROFILER_ALLOWED_IPS``
     - Allowlist של כתובות IP מורשות (CSV) ל-API של הפרופיילר. אם ריק, אין הגבלת IP.
     - לא
     - "" (ריק)
     - ``127.0.0.1,10.0.0.1``
     - Bot/WebApp
   * - ``PROFILER_RATE_LIMIT``
     - מגבלת בקשות לדקה ל-endpoints של הפרופיילר (Rate Limiting)
     - לא
     - ``60``
     - ``30``
     - Bot/WebApp
   * - ``PROFILER_METRICS_ENABLED``
     - הפעלה/כיבוי של מטריקות Prometheus לפרופיילר (Slow Queries / Buffer Size וכו')
     - לא
     - ``true``
     - ``false``
     - Bot/WebApp
   * - ``QUEUE_DELAY_WARN_MS``
     - סף מילישניות להתראת ``queue_delay_high`` כאשר התקבלה כותרת ``X-Queue-Start``/``X-Request-Start`` והשרת מזהה זמן המתנה בתור לפני טיפול בבקשה
     - לא
     - ``500``
     - ``1000``
     - WebApp
   * - ``COLLECTIONS_API_ITEMS_SLOW_MS``
     - סף מילישניות ללוג ביצועים ב-API של ``GET /api/collections/<id>/items`` (כדי לזהות בקשות איטיות וגודל payload)
     - לא
     - ``500``
     - ``300``
     - WebApp
   * - ``SEARCH_PAGE_SIZE``
     - גודל דף חיפוש בצד ה‑DB
     - לא
     - ``200``
     - ``500``
     - Bot/WebApp
   * - ``UI_PAGE_SIZE``
     - גודל דף ליסטים ב‑UI
     - לא
     - ``10``
     - ``20``
     - WebApp
   * - ``ENCRYPTION_KEY``
     - מפתח הצפנה לנתונים רגישים
     - לא
     - -
     - ``32-byte-key``
     - Bot/WebApp
   * - ``SENTRY_DSN``
     - DSN לשילוב עם Sentry (שגיאות ותובנות)
     - לא
     - "" (ריק)
     - ``https://xxx@o1234.ingest.sentry.io/5678``
     - Bot/WebApp
   * - ``SENTRY_TRACES_SAMPLE_RATE``
     - דגימת Traces (0.0–1.0)
     - לא
     - ``0.0``
     - ``0.1``
     - Bot/WebApp
   * - ``SENTRY_PROFILES_SAMPLE_RATE``
     - דגימת Profiles (0.0–1.0)
     - לא
     - ``0.0``
     - ``0.1``
     - Bot/WebApp

התראות וניטור (הרחבה)
----------------------

.. list-table:: Alerts & Observability
   :header-rows: 1

   * - משתנה
     - תיאור
     - חובה
     - ברירת מחדל
     - דוגמה
     - רכיב
   * - ``DRILL_MODE_ENABLED``
     - מפעיל Drill Mode (תרגולים) ב-WebApp/API. כאשר כבוי, ``/api/observability/drills/run`` יחזיר ``drill_disabled``.
     - לא
     - ``false``
     - ``true``
     - WebApp/Observability
   * - ``ALERT_TAGS_COLLECTION``
     - שם ה-Collection לתגיות התראות (Manual Alert Tagging) ב-Observability.
     - לא
     - ``alert_tags``
     - ``alert_tags``
     - WebApp/Observability
   * - ``ALERT_TAGS_DB_DISABLED``
     - אם ``true`` מכבה שמירה/שליפה של תגיות להתראות (Manual Alert Tagging) מה-DB.
     - לא
     - ``false``
     - ``true``
     - WebApp/Observability
   * - ``ALERTMANAGER_WEBHOOK_SECRET``
     - טוקן שצריך להופיע בכותרת ``X-Alertmanager-Token`` או בפרמטר ``token`` כדי לאמת קריאות ל־``/alertmanager/webhook``.
     - לא
     - "" (ריק)
     - ``secret123``
     - WebApp
   * - ``SENTRY_WEBHOOK_SECRET``
     - סוד לאימות קריאות ל־``/webhooks/sentry`` (אם ריק, השירות מאפשר קריאות ללא אימות – מומלץ להגדיר). נבדק כ-``Authorization: Bearer`` או ``?token=`` וגם תומך בחתימת HMAC כאשר קיימת.
     - לא
     - "" (ריק)
     - ``secret123``
     - WebApp
   * - ``SENTRY_WEBHOOK_DEDUP_WINDOW_SECONDS``
     - חלון דה-דופליקציה (בשניות) להתראות Sentry שמגיעות ב-Webhook כדי למנוע burst (``0`` מנטרל).
     - לא
     - ``300``
     - ``600``
     - WebApp
   * - ``ALERTMANAGER_IP_ALLOWLIST``
     - רשימת IPs (מופרדים בפסיק) שמורשים לצרוך את ה-webhook; נבדק מול ``X-Forwarded-For``/``remote_addr``.
     - לא
     - "" (ריק)
     - ``10.0.0.5,10.0.0.6``
     - WebApp
   * - ``ALLOWED_WEBHOOK_HOSTS``
     - Allowlist אופציונלי ליעדי ``webhook`` (Visual Rule Engine). אם מוגדר, יישלח webhook רק ל-hostnames שמופיעים ברשימה (CSV, התאמה מדויקת).
     - לא
     - "" (ריק)
     - ``hooks.slack.com,api.example.com``
     - Bot/WebApp
   * - ``ALLOWED_WEBHOOK_SUFFIXES``
     - Allowlist אופציונלי ליעדי ``webhook`` לפי סיומות דומיין (CSV). אם מוגדר, יישלח webhook רק לדומיינים שמסתיימים באחת הסיומות (למשל ``.example.com``).
     - לא
     - "" (ריק)
     - ``.example.com,.mycompany.net``
     - Bot/WebApp
   * - ``SLACK_WEBHOOK_URL``
     - כתובת Incoming Webhook של Slack לשליחת התראות.
     - לא
     - "" (ריק)
     - ``https://hooks.slack.com/services/...``
     - Bot
   * - ``PUBLIC_URL``
     - כתובת ציבורית בסיסית של ה-WebApp (משמשת ליצירת קישור יציב ל־Observability Dashboard בהודעות התראה).
     - לא
     - ``https://code-keeper-webapp.onrender.com``
     - ``https://code-keeper-webapp.onrender.com``
     - Bot/WebApp
   * - ``ALERT_TELEGRAM_BOT_TOKEN``
     - טוקן בוט ייעודי לשליחת התראות לטלגרם (נפרד מהבוט הראשי אם רוצים).
     - לא
     - -
     - ``123456:ABC-DEF...``
     - Bot/WebApp
   * - ``ALERT_TELEGRAM_CHAT_ID``
     - Chat ID/Channel שאליו נשלחות התראות (לדוגמה ``-100123`` או ``@myteam``).
     - לא
     - -
     - ``-1001234567890``
     - Bot/WebApp
   * - ``ALERT_TELEGRAM_MIN_SEVERITY``
     - דרגת החומרה המינימלית שתישלח לטלגרם (``info``/``warning``/``error``/``critical``).
     - לא
     - ``info``
     - ``warning``
     - Bot/WebApp
   * - ``ALERT_STARTUP_GRACE_PERIOD_SECONDS``
     - חלון חסד (שניות) לאחר אתחול התהליך שבו מושתקים רק alerts "רועשים" מתוך allowlist (Mongo/Latency/EWMA) כדי למנוע רעשי דיפלוי.
     - לא
     - ``1200``
     - ``1200``
     - Bot/WebApp
   * - ``ALERTS_TEXT_INCLUDE_DASHBOARD_LINK_TELEGRAM``
     - אם ``true`` מוסיף שורת ``📊 Dashboard: ...`` לגוף ההודעה בטלגרם. ברירת מחדל כבוי כדי להימנע מכפילות (יש כפתור Inline).
     - לא
     - ``false``
     - ``true``
     - Bot/WebApp
   * - ``ALERTS_TEXT_INCLUDE_DASHBOARD_LINK_SLACK``
     - אם ``true`` מוסיף שורת ``📊 Dashboard: ...`` לגוף ההודעה ב-Slack (ברירת מחדל פעיל כי אין כפתור).
     - לא
     - ``true``
     - ``false``
     - Bot/WebApp
   * - ``GRAFANA_URL``
     - בסיס ה-URL של Grafana לכתיבת annotations על התראות.
     - לא
     - "" (ריק)
     - ``https://grafana.example.com``
     - Bot
   * - ``GRAFANA_API_TOKEN``
     - אסימון Bearer ל-Grafana כשמוסיפים annotations דרך ה-API.
     - לא
     - "" (ריק)
     - ``glsa_xxx``
     - Bot
   * - ``ALERTS_DB_ENABLED``
     - מפעיל כתיבה/קריאה ל-MongoDB עבור לוג התראות וסיילנסים.
     - לא
     - ``false``
     - ``true``
     - Bot/Observability
   * - ``DRILLS_DB_ENABLED``
     - מפעיל שמירת היסטוריית Drill ב-MongoDB (ברירת מחדל נסמכת על ``ALERTS_DB_ENABLED``/``METRICS_DB_ENABLED``).
     - לא
     - "" (ריק = יורש מ-ALERTS_DB_ENABLED/METRICS_DB_ENABLED)
     - ``true``
     - WebApp/Observability
   * - ``ALERTS_COLLECTION``
     - שם הקולקשן שבו נשמרות התראות מנורמלות.
     - לא
     - ``alerts_log``
     - ``alerts_log_prod``
     - Bot/Observability
   * - ``ALERT_TYPES_CATALOG_COLLECTION``
     - שם הקולקשן שבו נשמר Catalog (Registry) של כל ``alert_type`` שנצפה אי פעם. משמש ל-Coverage Report כ-To-Do קבוע ל-Runbooks/Quick Fixes.
     - לא
     - ``alert_types_catalog``
     - ``alert_types_catalog_prod``
     - Bot/Observability
   * - ``DRILLS_COLLECTION``
     - שם הקולקשן שבו נשמרת היסטוריית Drill Mode (תרגולים).
     - לא
     - ``drill_history``
     - ``drill_history_prod``
     - WebApp/Observability
   * - ``ALERTS_SILENCES_COLLECTION``
     - שם הקולקשן לסיילנסים (pattern + TTL).
     - לא
     - ``alerts_silences``
     - ``alerts_silences_eu``
     - Bot/Observability
   * - ``ALERTS_TTL_DAYS``
     - כמה ימים נשמרת התראה לפני מחיקה אוטומטית (TTL index).
     - לא
     - ``30``
     - ``14``
     - Bot/Observability
   * - ``DRILLS_TTL_DAYS``
     - כמה ימים נשמרת היסטוריית Drill לפני מחיקה אוטומטית (TTL index).
     - לא
     - ``90``
     - ``30``
     - WebApp/Observability
   * - ``ALERTS_GROUPING_CONFIG``
     - נתיב ל־YAML שמגדיר איך לאגד אירועים לקטגוריות התראה (log aggregator).
     - לא
     - ``config/alerts.yml``
     - ``config/custom_alerts.yml``
     - Bot/Observability
   * - ``ALERTS_USE_POOLED_HTTP``
     - כאשר ערכו ``true``/``1`` משתמשים ב-``http_sync`` המאוחד בעת שליחת Slack/Telegram.
     - לא
     - ``false``
     - ``true``
     - Bot
   * - ``ALERT_ANOMALY_BATCH_WINDOW_SECONDS``
     - חלון זמן (שניות) לאיגוד התראות anomaly דומות לפני הודעה מרוכזת.
     - לא
     - ``180``
     - ``120``
     - Bot
   * - ``ALERT_ERRORS_PER_MINUTE``
     - סף כמות שגיאות לדקה שמעורר ``anomaly_detected`` מהמודול metrics.
     - לא
     - ``20``
     - ``40``
     - Bot
   * - ``ALERT_AVG_RESPONSE_TIME``
     - רף ה-EWMA של זמן תגובה (שניות) שמעורר התראת latency (``0`` מנטרל).
     - לא
     - ``3.0``
     - ``2.5``
     - Bot
   * - ``ANOMALY_IGNORE_ENDPOINTS``
     - רשימת נתיבי URL (CSV/JSON list) שמוחרגים מעדכון EWMA ומדגימת ``slow_endpoints`` (המטריקות הרגילות עדיין נרשמות לגרפים).
     - לא
     - ``""``
     - ``/api/observability/aggregations,/api/observability/timeseries``
     - WebApp/Observability
   * - ``ALERT_AVG_RESPONSE_TIME_DEPLOY``
     - רף חלופי לאותה התראה בזמן חלון חסד לאחר Deploy.
     - לא
     - ``10.0``
     - ``6.0``
     - Bot
   * - ``DEPLOY_GRACE_PERIOD_SECONDS``
     - אורך חלון החסד (שניות) שבו משתמשים ברף Deploy.
     - לא
     - ``120``
     - ``180``
     - Bot
   * - ``ALERT_COOLDOWN_SECONDS``
     - קירור מינימלי בין שתי התראות מאותו סוג.
     - לא
     - ``300``
     - ``600``
     - Bot
   * - ``ALERT_DISPATCH_LOG_MAX``
     - מספר הרשומות שנשמרות בזיכרון עבור מעקב שליחות.
     - לא
     - ``500``
     - ``200``
     - Bot
   * - ``ALERT_EACH_ERROR``
     - מפעיל fallback שמוציא התראה נפרדת עבור כל שגיאה (עם קירור קשיח).
     - לא
     - ``false``
     - ``true``
     - Bot
   * - ``ALERT_EACH_ERROR_COOLDOWN_SECONDS``
     - קירור בין התראות fallback מאותה חתימת שגיאה.
     - לא
     - ``120``
     - ``60``
     - Bot
   * - ``ALERT_EACH_ERROR_TTL_SECONDS``
     - TTL לחתימות במאגר הדה-דופליקציה (ברירת המחדל: שעה או פי 10 מהקירור).
     - לא
     - ``3600``
     - ``7200``
     - Bot
   * - ``ALERT_EACH_ERROR_MAX_KEYS``
     - כמות החתימות שנשמרות במקביל לפני שמסירים את הוותיקות.
     - לא
     - ``1000``
     - ``2000``
     - Bot
   * - ``ALERT_QUICK_FIX_PATH``
     - קובץ JSON עם פתרונות/צעדים קצרים שמוצמדים להתראות בצ'אט.
     - לא
     - ``config/alert_quick_fixes.json``
     - ``config/custom_fixes.json``
     - Bot/WebApp
   * - ``OBSERVABILITY_RUNBOOK_PATH``
     - נתיב חלופי ל-``observability_runbooks.yml`` שמזין את ה-Runbooks וה-Quick Fix הדינמי.
     - לא
     - ``config/observability_runbooks.yml``
     - ``/etc/codebot/runbooks.yml``
     - WebApp/Observability
   * - ``OBS_RUNBOOK_STATE_TTL``
     - משך (בשניות) לשמירת סטטוס הצעדים שסומנו כ"בוצעו" ב-Runbook.
     - לא
     - ``14400``
     - ``7200``
     - WebApp/Observability
   * - ``OBS_RUNBOOK_EVENT_TTL``
     - זמן שמירת אירועי ה-Replay במטמון צד שרת לצורך שליפות Runbook (שניות).
     - לא
     - ``900``
     - ``1800``
     - WebApp/Observability
   * - ``ALERT_EXTERNAL_SERVICES``
     - רשימת מחרוזות (CSV) של שירותים חיצוניים שיזוהו כ-``external`` במדד High Error Rate (למשל ``uptimerobot``/``github api``); שגיאות מהמקורות האלה ייצרו רק התרעת Warning ולא יריצו Auto-Remediation.
     - לא
     - ``uptime,uptimerobot,uptime_robot,betteruptime,statuscake,pingdom,external_monitor,github api,github_api``
     - ``uptimerobot,github api,statuspage``
     - WebApp/Observability
   * - ``OBS_AI_EXPLAIN_URL``
     - Endpoint לשירות ההסבר החכם של הדשבורד (מקבל ``POST`` עם ``context`` ומחזיר ``root_cause``/``actions``/``signals``).
     - לא
     - "" (ריק)
     - ``https://ai.example.com/explain``
     - WebApp/Observability
   * - ``OBS_AI_EXPLAIN_TOKEN``
     - אסימון Bearer שנשלח ב-Header ``Authorization`` כאשר השירות מוגן (אופציונלי).
     - לא
     - "" (ריק)
     - ``sk-live-123`` / ``bearer-xyz``
     - WebApp/Observability
   * - ``OBS_AI_EXPLAIN_TIMEOUT``
     - Timeout (שניות) לפנייה לשירות ה-AI לפני נפילה לניתוח היוריסטי.
     - לא
     - ``12``
     - ``20``
     - WebApp/Observability
   * - ``OBS_AI_EXPLAIN_CACHE_TTL``
     - חיי המטמון (שניות) לתוצאות AI לפי ``alert_uid`` ב-Observability.
     - לא
     - ``600``
     - ``900``
     - WebApp/Observability
   * - ``SILENCE_MAX_DAYS``
     - מגבלת ימים לסיילנס יחיד שנוצר דרך ChatOps.
     - לא
     - ``7``
     - ``3``
     - Bot
   * - ``SILENCES_MAX_ACTIVE``
     - מספר הסיילנסים הפעילים המקסימלי לפני שיצירת חדשים נחסמת.
     - לא
     - ``50``
     - ``100``
     - Bot
   * - ``SENSITIVE_COMMAND_COOLDOWN_SEC``
     - קירור ברירת מחדל (שניות) לפקודות אדמין רגישות בצ'אט.
     - לא
     - ``5``
     - ``10``
     - Bot/ChatOps
   * - ``ALLOWED_CHAT_IDS``
     - CSV של Chats/Channels שמורשים להשתמש ביכולות אדמין (לדוגמה ערוצי ניהול).
     - לא
     - "" (ריק = אין הגבלה)
     - ``-1001,-1002``
     - Bot/ChatOps
   * - ``INTERNAL_ALERTS_BUFFER``
     - כמות ההתראות הפנימיות שנשמרות בזיכרון לבקרה.
     - לא
     - ``200``
     - ``500``
     - Bot
   * - ``SENTRY_API_URL``
     - בסיס ה-API של Sentry (אם משתמשים ב-self-hosted).
     - לא
     - ``https://sentry.io/api/0``
     - ``https://sentry.example.com/api/0``
     - Bot/ChatOps
   * - ``SENTRY_AUTH_TOKEN``
     - אסימון Bearer לקריאות API (נדרש ל-ChatOps / integrations).
     - לא
     - "" (ריק)
     - ``sentry_pat_xxx``
     - Bot/ChatOps
   * - ``SENTRY_DASHBOARD_URL``
     - URL מלא לאזור ה-Issues בסקופ ארגוני; גובר על לינקים שנבנים מה-DSN.
     - לא
     - "" (ריק)
     - ``https://sentry.io/organizations/acme/issues``
     - Bot/WebApp
   * - ``SENTRY_ORG``/``SENTRY_ORG_SLUG``
     - ה-slug של הארגון ב-Sentry (משמש לבניית URLs וקריאות API).
     - לא
     - "" (ריק)
     - ``codebot``
     - Bot/ChatOps
   * - ``SENTRY_PROJECT``/``SENTRY_PROJECT_SLUG``
     - פרויקט ברירת מחדל לסינון Issues/Events.
     - לא
     - "" (ריק)
     - ``codebot-web``
     - Bot/ChatOps
   * - ``SENTRY_PROJECT_URL``
     - URL ישיר לפרויקט ספציפי במקרה שאין Dashboard ארגוני.
     - לא
     - "" (ריק)
     - ``https://sentry.io/organizations/acme/projects/codebot``
     - Bot/ChatOps
   * - ``SENTRY_POLL_ENABLED``
     - מפעיל Polling תקופתי ל-Sentry (חלופה כאשר אין אפשרות Webhook ב-Sentry). הבוט ימשוך Issues אחרונים וייצר ``internal_alerts`` מסוג ``alert_type=sentry_issue``.
     - לא
     - ``false``
     - ``true``
     - Bot
   * - ``SENTRY_POLL_INTERVAL_SECS``
     - כל כמה שניות לבצע Polling ל-Sentry (מינימום 30).
     - לא
     - ``300``
     - ``120``
     - Bot
   * - ``SENTRY_POLL_FIRST_SECS``
     - דיליי לפני ריצת ה-Poll הראשונה לאחר עלייה (שניות).
     - לא
     - ``20``
     - ``5``
     - Bot
   * - ``SENTRY_POLL_LIMIT``
     - כמה Issues למשוך בכל Poll (מינימום 1, מקסימום 100).
     - לא
     - ``10``
     - ``25``
     - Bot
   * - ``SENTRY_POLL_SEVERITY``
     - דרגת החומרה שתישלח כ-``internal_alerts`` עבור Sentry Poll (``info``/``warning``/``error``/``critical``).
     - לא
     - ``error``
     - ``warning``
     - Bot
   * - ``SENTRY_POLL_SEED_SILENT``
     - אם ``true`` ההרצה הראשונה רק "זורעת" מצב (Seed) ולא שולחת התראות על Issues קיימים; רק פעילות חדשה בהמשך תייצר התראה.
     - לא
     - ``true``
     - ``false``
     - Bot
   * - ``SENTRY_POLL_DEDUP_SECONDS``
     - חלון דה-דופליקציה (בשניות) לכל Issue כדי למנוע הצפה (``0`` מנטרל).
     - לא
     - ``900``
     - ``300``
     - Bot
   * - ``SENTRY_TEST_NOTIFICATIONS_JOB``
     - 1/``true`` מפעיל Job מדמה ששולח אירוע בדיקה ל-Sentry לצורכי ניטור.
     - לא
     - ``false``
     - ``true``
     - Bot/ChatOps

מדדים, OTEL וחיזוי
-------------------

.. list-table:: Metrics & Predictive Controls
   :header-rows: 1

   * - משתנה
     - תיאור
     - חובה
     - ברירת מחדל
     - דוגמה
     - רכיב
   * - ``ENABLE_METRICS``
     - מפעיל/מכבה יצוא Metrics (Prometheus/OTEL). שימושי בסביבות שאין בהן endpoints חיצוניים.
     - לא
     - ``false``
     - ``true``
     - Bot/WebApp
   * - ``METRICS_DB_ENABLED``
     - Dual-write של metrics ל-MongoDB (לצד Prometheus).
     - לא
     - ``false``
     - ``true``
     - Bot/Observability
   * - ``METRICS_COLLECTION``
     - שם הקולקשן לכתיבת metrics כש-DB מופעל.
     - לא
     - ``service_metrics``
     - ``service_metrics_eu``
     - Bot/Observability
   * - ``METRICS_BATCH_SIZE``
     - גודל הבאצ' (מספר דגימות) שנשלחות בכל flush.
     - לא
     - ``50``
     - ``200``
     - Bot/Observability
   * - ``METRICS_FLUSH_INTERVAL_SEC``
     - כל כמה שניות לרוקן את הבאפר של metrics.
     - לא
     - ``5``
     - ``10``
     - Bot/Observability
   * - ``METRICS_EWMA_ALPHA``
     - מקדם EWMA (0-1) לחישוב אנומליות latency/error-rate.
     - לא
     - ``0.2``
     - ``0.1``
     - Bot
   * - ``METRICS_MAX_BUFFER``
     - מספר הדגימות המקסימלי שנשמר בזיכרון לפני שמתחילים לדלג.
     - לא
     - ``5000``
     - ``10000``
     - Bot
   * - ``ERROR_HISTORY_SECONDS``
     - חלון זמן (בשניות) לשמירת errors לצורך תרשימי חום.
     - לא
     - ``600``
     - ``900``
     - Bot
   * - ``ERROR_HISTORY_MAX_SAMPLES``
     - מספר מקסימלי של רשומות שגיאה שנשמרות בחלון.
     - לא
     - ``2000``
     - ``5000``
     - Bot
   * - ``ERROR_SIGNATURES_PATH``
     - נתיב לקובץ החתימות (YAML) שמשמש את log aggregator לסיווג שגיאות.
     - לא
     - ``config/error_signatures.yml``
     - ``config/custom_error_signatures.yml``
     - Bot
   * - ``HTTP_SAMPLE_BUFFER``
     - כמות דגימות HTTP שנשמרות ב־deque לצורך סטטיסטיקות.
     - לא
     - ``2000``
     - ``4000``
     - Bot/WebApp
   * - ``HTTP_SAMPLE_RETENTION_SECONDS``
     - זמן שמירת הדגימות (שניות) לפני שמנקים אותן.
     - לא
     - ``600``
     - ``1200``
     - Bot/WebApp
   * - ``RECENT_ERRORS_BUFFER``
     - מספר השגיאות האחרונות שמוצגות ב-ChatOps (Deque).
     - לא
     - ``200``
     - ``400``
     - Bot/ChatOps
   * - ``MEMORY_USAGE_THRESHOLD_PERCENT``
     - אחוז שימוש בזיכרון שמפעיל התראות חיזוי (למשל 85%).
     - לא
     - ``85``
     - ``90``
     - Bot
   * - ``OTEL_EXPORTER_INSECURE``
     - כאשר ``true`` מאפשר שימוש ב-OTLP gRPC ללא TLS (למטרות לוקאליות).
     - לא
     - ``false``
     - ``true``
     - Bot/WebApp
   * - ``OTEL_EXPORTER_OTLP_ENDPOINT``
     - כתובת OTLP כללית (gRPC/HTTP) לייצוא traces/metrics אם אין חלוקה.
     - לא
     - "" (ריק)
     - ``https://otel-collector:4317``
     - Bot/WebApp
   * - ``OTEL_EXPORTER_OTLP_METRICS_ENDPOINT``
     - כתובת ייעודית למטריקות OTLP (אם שונה מה-endpoint הראשי).
     - לא
     - "" (ריק)
     - ``https://otel-collector:4318/v1/metrics``
     - Bot/WebApp
   * - ``OTEL_EXPORTER_OTLP_TRACES_ENDPOINT``
     - כתובת ייעודית ל-traces OTLP.
     - לא
     - "" (ריק)
     - ``https://otel-collector:4318/v1/traces``
     - Bot/WebApp
   * - ``PREDICTION_MAX_AGE_SECONDS``
     - כמה זמן לשמור קבצי חיזוי/תקריות לפני ניקוי (ברירת מחדל 24 שעות).
     - לא
     - ``86400``
     - ``43200``
     - Bot
   * - ``PREDICTIVE_MODEL``
     - סוג המודל לחיזוי (``exp_smoothing`` או ``linear``).
     - לא
     - ``exp_smoothing``
     - ``linear``
     - Bot
   * - ``PREDICTIVE_HALFLIFE_MINUTES``
     - זמן מחצית החיים בדקות ל-weighting של EW regression.
     - לא
     - ``30``
     - ``15``
     - Bot
   * - ``PREDICTIVE_HORIZON_SECONDS``
     - טווח החיזוי (שניות קדימה) לפני שמכריזים על סכנה קרובה.
     - לא
     - ``900``
     - ``600``
     - Bot
   * - ``PREDICTIVE_FEEDBACK_INTERVAL_SEC``
     - כל כמה שניות נמדדת דיוק ההחיזוי (feedback loop).
     - לא
     - ``300``
     - ``120``
     - Bot
   * - ``PREDICTIVE_CLEANUP_INTERVAL_SEC``
     - כל כמה זמן לנקות חיזויים ו-incidents ישנים.
     - לא
     - ``3600``
     - ``900``
     - Bot
   * - ``PREDICTIVE_SAMPLER_ENABLED``
     - מפעיל את ה-sampler שרץ ברקע ואוסף מדידות לטובת החיזוי.
     - לא
     - ``true``
     - ``false``
     - Bot
   * - ``PREDICTIVE_SAMPLER_METRICS_URL``
     - בסיס ה-URL שממנו הסמפולר קורא סטטיסטיקות (ברירת מחדל: ``WEBAPP_URL``/``PUBLIC_BASE_URL``).
     - לא
     - "" (auto)
     - ``https://internal-observability/api``
     - Bot
   * - ``PREDICTIVE_SAMPLER_INTERVAL_SECS``
     - תדירות ריצה של הסמפולר (שניות).
     - לא
     - ``60``
     - ``30``
     - Bot
   * - ``PREDICTIVE_SAMPLER_FIRST_SECS``
     - דילי לפני ריצת הסמפולר הראשונה.
     - לא
     - ``10``
     - ``5``
     - Bot
   * - ``PREDICTIVE_SAMPLER_RUN_IN_TESTS``
     - כאשר ``true`` הסמפולר רץ גם במהלך Pytest (ברירת מחדל כבוי כדי לא להאריך טסטים).
     - לא
     - ``false``
     - ``true``
     - Bot

תפעול, אינטגרציות ופיצ'רים
---------------------------

.. list-table:: Operations & Feature Flags
   :header-rows: 1

   * - משתנה
     - תיאור
     - חובה
     - ברירת מחדל
     - דוגמה
     - רכיב
   * - ``BACKUPS_STORAGE``
     - בחירת מנגנון גיבוי: ``mongo`` (GridFS) או ``fs`` (מערכת קבצים מקומית).
     - לא
     - ``mongo``
     - ``fs``
     - Bot/WebApp
   * - ``BACKUPS_DIR``
     - נתיב גיבויים בלוקאל (אם ``BACKUPS_STORAGE=fs``); אחרת נבחר אוטומטית.
     - לא
     - נתיב ברירת מחדל (``/app/backups``)
     - ``/var/lib/codebot/backups``
     - Bot/WebApp
   * - ``BACKUPS_SHOW_ALL_IF_EMPTY``
     - כאשר ``true`` מאפשר לממשק להציג את כל הקבצים גם כשאין פילטר (שימושי ל-ops).
     - לא
     - ``false``
     - ``true``
     - Bot
   * - ``CACHE_WARMING_ENABLED``
     - מפעיל חימום קאש מתוזמן לאחר אתחול.
     - לא
     - ``true``
     - ``false``
     - Bot
   * - ``CACHE_WARMING_BUDGET_SECONDS``
     - תקציב הזמן המרבי ללופ החימום (מונע עיכובים ארוכים).
     - לא
     - ``5.0``
     - ``0.2``
     - Bot
   * - ``CACHE_WARMING_INTERVAL_SECS``
     - כל כמה זמן (שניות) להריץ warming job.
     - לא
     - ``900``
     - ``300``
     - Bot
   * - ``CACHE_WARMING_FIRST_SECS``
     - דילי לפני ריצת ה-warming הראשונה אחרי עלייה.
     - לא
     - ``45``
     - ``5``
     - Bot
   * - ``DISABLE_ACTIVITY_REPORTER``
     - 1/``true`` מדליק קצר את דיווחי activity (שימושי בטסטים/לוקאל).
     - לא
     - ``0``
     - ``1``
     - Bot
   * - ``DISABLE_DB``
     - עוקף כל אינטראקציה עם MongoDB (בדרך כלל לטסטים).
     - לא
     - ``false``
     - ``true``
     - Bot/WebApp
   * - ``DISABLE_WEEKLY_REPORTS``
     - מדליק/מכבה שליחת דו"חות שבועיים (reminders).
     - לא
     - ``false``
     - ``true``
     - Bot
   * - ``DUMMY_BOT_TOKEN``
     - טוקן בדיקה שמשמש סביבות שבהן אין צורך להתחבר לטלגרם (למשל docs build).
     - לא
     - ``dummy_token``
     - ``test_token``
     - Bot/WebApp
   * - ``DRIVE_RESCHEDULE_BOOTSTRAP_DELAY``
     - כמה שניות להמתין לפני תחילת משימות ה-Drive rescheduler.
     - לא
     - ``5``
     - ``1``
     - Bot
   * - ``DRIVE_RESCHEDULE_FIRST_DELAY``
     - דילי לכל משימת שמירה/Keepalive הראשונה.
     - לא
     - ``60``
     - ``10``
     - Bot
   * - ``DRIVE_RESCHEDULE_INTERVAL``
     - הפרש זמנים בין הריצות הבאות של ה-Drive rescheduler.
     - לא
     - ``900``
     - ``300``
     - Bot
   * - ``APSCHEDULER_COLLECTION``
     - שם קולקשן ברירת המחדל עבור משימות APScheduler כאשר נשמרות ב-MongoDB.
     - לא
     - ``scheduler_jobs``
     - ``scheduler_jobs_eu``
     - Bot
   * - ``WEEKLY_REPORT_DELAY_SECS``
     - כמה זמן להמתין אחרי עלייה לפני הפעלת job הדו"חות השבועיים.
     - לא
     - ``3600``
     - ``600``
     - Bot
   * - ``RATE_LIMIT_SHADOW_MODE``
     - במצב ``true`` המגביל רק סופר חריגות ולא חוסם משתמשים (לבדיקות/דרג).
     - לא
     - ``false``
     - ``true``
     - Bot/WebApp
   * - ``ALLOW_SEED_NON_LOCAL``
     - מאפשר לסקריפט ה-seed לרוץ גם כשכתובת ה-Mongo אינה לוקאלית (לברירת מחדל אסור).
     - לא
     - ``false``
     - ``true``
     - Scripts
   * - ``CHATOPS_ALLOW_ALL_IF_NO_ADMINS``
     - כאשר ``true`` ואם ``ADMIN_USER_IDS`` ריק, כל משתמש נחשב אדמין (מתאים לסביבות dev).
     - לא
     - ``false``
     - ``true``
     - Bot/ChatOps
   * - ``USE_NEW_SAVE_FLOW``
     - מפעיל את מסלול השמירה המחודש (ניסיוני) בהנדלרים של save.
     - לא
     - ``false``
     - ``true``
     - Bot
   * - ``REFACTOR_LAYERED_MODE``
     - 1/``true`` מחייב את מנוע הרה-פקטור לפעול במצב IA Layered (בדיקות/POC).
     - לא
     - ``false``
     - ``true``
     - Bot
   * - ``PASTEBIN_API_KEY``
     - מפתח API עבור Pastebin ליצירת לינקים שיתופיים.
     - לא
     - "" (ריק)
     - ``pastebin_key``
     - Bot/WebApp
   * - ``WEBAPP_LOGIN_SECRET``
     - סוד משותף בין הבוט לוובאפ לטובת אימות single-sign-on.
     - לא
     - "" (ריק)
     - ``super-shared-secret``
     - WebApp/Bot
   * - ``SUPPORT_EMAIL``
     - כתובת דוא"ל שמוצגת בהודעות ומספקת fallback ל-``VAPID_SUB_EMAIL``.
     - לא
     - "" (ריק)
     - ``support@example.com``
     - Bot/WebApp
   * - ``TOKEN_ENC_KEY``
     - מפתח Fernet (Base64) להצפנת טוקנים רגישים במסד (ראה ``docs/SECURITY_TOKENS``).
     - לא
     - "" (ריק)
     - ``Cr4ZEXxx...``
     - Bot
   * - ``PUSH_CLAIM_TTL_SECONDS``
     - משך הזמן שבו claim של תזכורת push נחשב בתוקף לפני שמשחררים אותו.
     - לא
     - ``60``
     - ``120``
     - Bot/WebApp
   * - ``PUSH_DELIVERY_URGENCY``
     - Urgency header לברירת מחדל ב-Web Push (``very-low``/``low``/``normal``/``high``).
     - לא
     - ``high``
     - ``low``
     - WebApp
   * - ``PUSH_SEND_INTERVAL_SECONDS``
     - מרווח ההמתנה בין סריקות מתוזמנות של תזכורות push.
     - לא
     - ``60`` (מינימום 20)
     - ``30``
     - WebApp
   * - ``GITHUB_API_BASE_DELAY``
     - דילי בסיסי בין בקשות GitHub כדי להישאר מתחת לרף rate-limit.
     - לא
     - ``2.0``
     - ``1.0``
     - Bot/ChatOps
   * - ``GITHUB_BACKOFF_DELAY``
     - מקדם backoff (שניות) שמתווסף בכל ניסיון כושל לקריאות GitHub.
     - לא
     - ``5.0``
     - ``3.0``
     - Bot/ChatOps
   * - ``GITHUB_NOTIFICATIONS_PR_MIN_COOLDOWN``
     - קירור (דקות) בין שליחת התראות PR באותו ערוץ כדי למנוע הצפה.
     - לא
     - ``30``
     - ``10``
     - Bot/ChatOps
   * - ``LOG_AGG_ECHO``
     - כאשר ``true`` סקריפט ``run_log_aggregator`` ידפיס לשגיאה כל שורה שנקלטה כ-match (לדיבוג).
     - לא
     - ``0``
     - ``1``
     - Scripts
   * - ``LOG_AGG_RELOAD_SECONDS``
     - כל כמה שניות סקריפט הלוג-אגגרטור יטען מחדש את קבצי החתימות.
     - לא
     - ``60``
     - ``10``
     - Scripts
   * - ``LOCK_MAX_WAIT_SECONDS``
     - כמה זמן לחכות ללוק לפני שמתייאשים (``0`` = המתנה אינסופית).
     - לא
     - ``0``
     - ``15``
     - Bot
   * - ``LOCK_RETRY_INTERVAL_SECONDS``
     - זמן המתנה בין ניסיונות נעילה חוזרים.
     - לא
     - ``5``
     - ``1``
     - Bot
   * - ``APP_VERSION``
     - מחרוזת גרסה שמוזנת מהפלטפורמה (Render/Heroku) לצורכי Telemetry.
     - לא
     - "" (ריק)
     - ``2025.12.1``
     - Bot/WebApp
   * - ``ASSET_VERSION``
     - מזהה לצורך cache-busting של קבצי סטטיק (נוסף ל-query param).
     - לא
     - "" (ריק)
     - ``78f3dea``
     - WebApp
   * - ``DEPLOYMENT_TYPE``
     - מחרוזת תיאור (למשל ``render``, ``kubernetes``) שמופיעה בלוגים/טופס סטטוס.
     - לא
     - "" (ריק)
     - ``kubernetes``
     - Bot/WebApp
   * - ``ENV``
     - שם סביבת הריצה (fallback כאשר ``ENVIRONMENT`` לא מוגדר).
     - לא
     - ``production``
     - ``staging``
     - Bot/WebApp
   * - ``GIT_COMMIT`` / ``RENDER_GIT_COMMIT`` / ``HEROKU_SLUG_COMMIT`` / ``SOURCE_VERSION``
     - מזהי הקומיט כפי שמוזנים ע"י הפלטפורמה; מופיעים בדוחות גרסה.
     - לא
     - "" (ריק)
     - ``cafe123``
     - Bot/WebApp
   * - ``HOSTNAME``
     - שם המכונה המדווח בלוגים / ב-claim של push (לרוב מוזן ע"י התשתית, אבל ניתן לעקוף).
     - לא
     - ערך מערכת
     - ``codebot-worker-1``
     - Bot/WebApp
   * - ``MONGODB_COMPRESSORS``
     - רשימת הקומפרסורים שהקליינט יבקש מ-Mongo (למשל ``zstd,snappy``).
     - לא
     - "" (Auto)
     - ``zstd,snappy``
     - Bot/WebApp
   * - ``MONGO_URI`` / ``MONGO_DB_NAME``
     - אליאסים המשמשים סקריפטי עזר (כמו setup_bookmarks) כאשר אין ``MONGODB_URL``/``DATABASE_NAME``.
     - לא
     - ``""`` / ``code_keeper_bot``
     - ``mongodb://localhost:27017`` / ``my_db``
     - Scripts

דגלי בדיקות ופיתוח
-------------------

.. list-table:: Dev & Testing Flags
   :header-rows: 1

   * - משתנה
     - תיאור
     - חובה
     - ברירת מחדל
     - דוגמה
     - רכיב
   * - ``ONLY_LIGHT_PERF``
     - כאשר ``1`` תוסף הביצועים מריץ רק טסטים מסומנים כ"קלים" ומדלג על כבדים.
     - לא
     - ``0``
     - ``1``
     - Tests
   * - ``PERF_HEAVY_PERCENTILE``
     - אחוזון שמפריד בין טסטים "כבדים" ל"קלים" (ברירת מחדל 90).
     - לא
     - ``90``
     - ``75``
     - Tests
   * - ``PYTEST`` / ``PYTEST_CURRENT_TEST`` / ``PYTEST_RUNNING``
     - דגלים שמאותתים לקוד שאנו בתוך Pytest (למשל כדי לנטרל Jobs). Pytest מגדיר אותם אוטומטית.
     - לא
     - "" (ריק)
     - ``1``
     - Bot/WebApp
   * - ``SPHINX_MOCK_IMPORTS``
     - 1/``true`` גורם ל-build של התיעוד למקם מודולים בעזרת mocks במקום לייבא בפועל.
     - לא
     - ``false``
     - ``true``
     - Docs
   * - ``PIP_NO_SETUPTOOLS`` / ``PIP_NO_WHEEL``
     - דגלים של סקריפט ``get-pip.py`` בלבד; השאירו כבויים אלא אם מריצים את הסקריפט כחלק מאוטומציה.
     - לא
     - "" (ריק)
     - ``1``
     - Tooling

דוגמאות קונפיגורציה
--------------------

Development::

   BOT_TOKEN=your_bot_token_here
   MONGODB_URL=mongodb://localhost:27017
   DATABASE_NAME=code_keeper_dev
   LOG_LEVEL=DEBUG

Staging::

   BOT_TOKEN=staging_bot_token
   MONGODB_URL=mongodb+srv://user:pass@cluster.mongodb.net
   DATABASE_NAME=code_keeper_staging
   LOG_LEVEL=INFO
   REDIS_URL=redis://staging-redis:6379

Production::

   BOT_TOKEN=prod_bot_token
   MONGODB_URL=mongodb+srv://user:pass@prod-cluster.mongodb.net
   DATABASE_NAME=code_keeper_prod
   LOG_LEVEL=WARNING
   REDIS_URL=redis://prod-redis:6379
   ENCRYPTION_KEY=your-32-byte-encryption-key

קישורים
-------

- :doc:`installation`
- :doc:`configuration`
- `SECURITY_TOKENS (מסמך ריפו)` <https://github.com/amirbiron/CodeBot/blob/main/docs/SECURITY_TOKENS.md>`_

טבלת Scopes לפיצ'רים של GitHub
--------------------------------

.. list-table:: Feature → Required Scopes
   :header-rows: 1

   * - Feature
     - Required Scopes
   * - Create Pull Request
     - ``repo``, ``workflow``
   * - Write files (Trees/Contents API)
     - ``repo``
   * - Read repository metadata (branches, commits, PRs)
     - ``repo``
   * - Trigger workflows / read checks status
     - ``workflow``

הערה: הקפידו להעניק הרשאות מינימליות בלבד. לפרטים נוספים ראו :doc:`integrations`.
