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
   agents/rate-limiting
   doc-authoring
   style-glossary
   versioning-stable-anchors
   whats-new
   architecture
   contributing
   branch-protection-and-pr-rules

.. toctree::
   :maxdepth: 2
   :caption: מדריכים בסיסיים:

   installation
   configuration
   environment-variables
   performance-scaling
   performance-sticky-notes
   large-files-runbook

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
   database/detailed-schema

.. toctree::
   :maxdepth: 2
   :caption: עזרה ודוגמאות:

   examples
   testing
   testing-rate-limit-examples
   performance-tests
   ci-cd
   conversation-handlers
   troubleshooting
   development
   development/pre-commit
   development/tools
   development/scripts
   development/i18n
   integrations
   repository-integrations
   security
   monitoring
   git-lfs
   user/bookmarks
   user/sticky_notes
   user/reminders
   user/my_collections
   user/share_code
   user/github_browse
   user/download_repo
   BOT_TEST_PLAN_CONTAINER

.. toctree::
   :maxdepth: 2
   :caption: זרימות עבודה:

   workflows/index

.. toctree::
   :maxdepth: 2
   :caption: מנועי המערכת:

   engines/overview

.. toctree::
   :maxdepth: 2
   :caption: Edge Cases וטיפול בשגיאות:

   edge-cases

.. note::
   חלק מהפיצ'רים (Bookmarks, Collections, Sticky Notes) זמינים ב‑WebApp בלבד (לא בבוט).
   ראו :doc:`webapp/overview` לפרטים נוספים.

.. toctree::
   :maxdepth: 2
   :caption: איכות וקונבנציות:

   quality/type-safety
   quality/code-normalization
   ARCHITECTURE_LAYER_RULES


.. toctree::
   :maxdepth: 2
   :caption: WebApp:

   webapp/overview
   DEV_WEB_PUSH
   webapp/user-interfaces
   webapp/snippet-library
   webapp/onboarding
   webapp/caching
   webapp/advanced-caching
   webapp/static-checklist
   webapp/commands-catalog
   webapp/api-reference
   webapp/bulk-actions
   webapp/editor
   webapp/markdown-folding
   webapp/smooth-scrolling
   webapp/system-modules

.. toctree::
   :maxdepth: 2
   :caption: Observability

   observability
   observability/observability_dashboard
   api/ai_explain
   rate-limiting
   observability/guidelines
   logging_schema
   metrics
   resilience
   alerts
   observability/log_based_alerts
   observability/log-aggregator
   sentry
   runbooks/incident-checklist
   runbooks/logging-levels
   runbooks/github_backup_restore
   runbooks/slo

.. toctree::
   :maxdepth: 2
   :caption: פריסה ו-Workers

   deployment/workers

.. toctree::
   :maxdepth: 2
   :caption: ChatOps

   chatops/overview
   chatops/commands
   chatops/observe
   chatops/ratelimit
   chatops/playbooks
   chatops/permissions
   chatops/troubleshooting
   chatops/faq

.. toctree::
   :maxdepth: 2
   :caption: סוכני AI:

   ai-agents/guide
   agents/rate-limiting

.. toctree::
   :maxdepth: 2
   :caption: Observability – Advanced

   observability/events_catalog
   observability/error_codes
   observability/tracing_hotspots
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
* ⏰ תזכורות - ניהול זמן ומשימות

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

**ארגון וניהול אישי:**
   - סימניות (Bookmarks) - סימון נקודות חשובות בקוד
   - אוספים (Collections) - ארגון קבצים לפי נושאים
   - פתקים דביקים (Sticky Notes) - הערות ויזואליות על הקוד
   - מועדפים (Favorites) - סימון קבצים חשובים
   - תזכורות (Reminders) - תזכורות זמן משימות

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