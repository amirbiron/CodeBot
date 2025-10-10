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
   * - ``REDIS_URL``
     - חיבור ל-Redis (cache)
     - לא
     - -
     - ``redis://localhost:6379``
     - Bot
   * - ``LOG_LEVEL``
     - רמת logging
     - לא
     - ``INFO``
     - ``DEBUG``
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
