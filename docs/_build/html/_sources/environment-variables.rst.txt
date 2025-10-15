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
     - טוקן GitHub
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
   * - ``PUBLIC_SHARE_TTL_DAYS``
     - תוקף ברירת מחדל לקישורי שיתוף (ימים)
     - לא
     - ``7``
     - ``14``
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
   * - ``CACHE_ENABLED``
     - הפעלת קאש פנימי
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
   * - ``ENCRYPTION_KEY``
     - מפתח הצפנה לנתונים רגישים
     - לא
     - -
     - ``32-byte-key``
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
