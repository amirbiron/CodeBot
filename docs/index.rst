.. Code Keeper Bot documentation master file

Code Keeper Bot - תיעוד API
============================

ברוכים הבאים לתיעוד ה-API של Code Keeper Bot!

בוט זה מספק ממשק טלגרם מתקדם לניהול ושמירת קטעי קוד, עם תמיכה בשפות תכנות מרובות,
אינטגרציה עם GitHub, וכלי ניהול מתקדמים.

.. toctree::
   :maxdepth: 2
   :caption: למפתחים ולסוכני AI:

   quickstart-ai
   quickstart
   quickstart-contrib
   ai-guidelines
   doc-authoring
   style-glossary
   versioning-stable-anchors
   whats-new
   architecture
   contributing

.. toctree::
   :maxdepth: 2
   :caption: מדריכים בסיסיים:

   installation
   configuration
   environment-variables

.. toctree::
   :maxdepth: 2
   :caption: API Reference:

   api/index
   modules/index
   handlers/index
   services/index
   database/index
   database/indexing
   database/cursor-pagination
   database-schema

.. toctree::
   :maxdepth: 2
   :caption: עזרה ודוגמאות:

   examples
   testing
   ci-cd
   conversation-handlers
   troubleshooting
   development
   integrations
   security
   user/share_code
   user/github_browse
   user/download_repo

.. toctree::
   :maxdepth: 2
   :caption: WebApp:

   webapp/overview
   webapp/caching
   webapp/static-checklist
   webapp/api-reference
   webapp/bulk-actions

.. toctree::
   :maxdepth: 2
   :caption: Observability

   observability
   logging_schema
   metrics
   alerts
   sentry
   runbooks/logging-levels

.. toctree::
   :maxdepth: 2
   :caption: Observability – Advanced

   observability/events_catalog
   observability/error_codes
   observability/metrics_promql
   observability/alerts_playbook

סקירה כללית
------------

**Code Keeper Bot** הוא בוט טלגרם מתקדם המאפשר:

* 💾 שמירה וניהול של קטעי קוד
* 🔍 חיפוש מתקדם בקוד
* 🎨 הדגשת תחביר לשפות תכנות מרובות
* 📊 סטטיסטיקות שימוש מפורטות
* 🔗 אינטגרציה עם GitHub
* 📦 גיבוי ושחזור נתונים
* 🔐 אבטחה והצפנה

תכונות עיקריות
---------------

**ניהול קוד:**
   - שמירת קטעי קוד עם מטא-דאטה
   - תמיכה בשפות תכנות מרובות
   - הדגשת תחביר אוטומטית
   - חיפוש וסינון מתקדם

**אינטגרציות:**
   - העלאה ל-GitHub Gist
   - ייצוא לפורמטים שונים
   - שיתוף קוד בקלות

**כלי ניהול:**
   - גיבוי אוטומטי
   - סטטיסטיקות שימוש
   - ניהול משתמשים

התחלה מהירה
------------

.. code-block:: python

   from main import create_application
   from config import config
   
   # יצירת אפליקציית הבוט
   app = create_application(config.BOT_TOKEN)
   
   # הפעלת הבוט
   app.run_polling()

דרישות מערכת
-------------

* Python 3.9+
* MongoDB 4.4+
* Telegram Bot API Token
* Redis (אופציונלי, לקאש)

Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`