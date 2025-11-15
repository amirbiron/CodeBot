משתני סביבה - רפרנס
=====================

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
     - ``5000``
     - ``5000``
     - Bot/WebApp
   * - ``MONGODB_SERVER_SELECTION_TIMEOUT_MS``
     - זמן בחירת שרת (serverSelectionTimeoutMS)
     - לא
     - ``3000``
     - ``5000``
     - Bot/WebApp
   * - ``MONGODB_SOCKET_TIMEOUT_MS``
     - זמן קצוב לקריאת/כתיבת שקע (socketTimeoutMS)
     - לא
     - ``20000``
     - ``30000``
     - Bot/WebApp
   * - ``MONGODB_CONNECT_TIMEOUT_MS``
     - זמן קצוב להתחברות (connectTimeoutMS)
     - לא
     - ``10000``
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
     - ``5`` (או ``1`` ב-``SAFE_MODE``)
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
     - ``1`` ל-``clear_stale``; ``2`` ל-``clear_all``
     - ``1``
     - Bot/WebApp
   * - ``DISABLE_BACKGROUND_CLEANUP``
     - דילוג כולל על עבודות ניקוי רקע (קאש/גיבויים)
     - לא
     - ``false``
     - ``true``
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
     - רמת logging
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
