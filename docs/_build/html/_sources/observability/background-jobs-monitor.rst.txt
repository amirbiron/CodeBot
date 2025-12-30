Background Jobs Monitor
=======================

סקירה כללית
-----------

פיצ'ר ה-Background Jobs Monitor מספק נראות (Observability) מלאה לכל ה-Jobs הרצים ברקע במערכת,
כולל פעולות משתמש דינמיות (Drive, Reminders, Batch Operations).

**מה הפיצ'ר נותן:**

- רישום מרכזי של כל ה-Jobs במערכת (``JobRegistry``)
- מעקב בזמן אמת אחרי הרצות (``JobTracker``)
- דשבורד ויזואלי ב-WebApp: ``GET /jobs/monitor``
- פקודות ChatOps בטלגרם: ``/jobs``
- התראות אוטומטיות על כשלים ו-Jobs תקועים
- API מלא לצריכה פרוגרמטית

רכיבים וקוד רלוונטי
-------------------

+-------------------------------+-------------------------------------------+
| קובץ                          | תפקיד                                     |
+===============================+===========================================+
| ``services/job_registry.py``  | רישום הגדרות Jobs (Singleton)             |
+-------------------------------+-------------------------------------------+
| ``services/job_tracker.py``   | מעקב הרצות + שמירה ל-DB                   |
+-------------------------------+-------------------------------------------+
| ``database/job_runs_collection.py`` | הגדרת אינדקסים ו-TTL               |
+-------------------------------+-------------------------------------------+
| ``services/webserver.py``     | aiohttp API (Bot-side)                    |
+-------------------------------+-------------------------------------------+
| ``webapp/app.py``             | Flask API + דשבורד (WebApp-side)          |
+-------------------------------+-------------------------------------------+
| ``webapp/templates/jobs_monitor.html`` | תבנית הדשבורד               |
+-------------------------------+-------------------------------------------+
| ``chatops/jobs_commands.py``  | פקודת ``/jobs`` בטלגרם                    |
+-------------------------------+-------------------------------------------+
| ``config/alerts.yml``         | הגדרות Alerts ל-Jobs                      |
+-------------------------------+-------------------------------------------+

מסד נתונים
----------

קולקציה: ``job_runs``
~~~~~~~~~~~~~~~~~~~~~

כל הרצה נשמרת בקולקציה ``job_runs`` עם TTL של **7 ימים** (מחיקה אוטומטית).

**שדות עיקריים:**

.. code-block:: javascript

   {
     "run_id": "abc123def456",     // מזהה ייחודי להרצה
     "job_id": "cache_warming",    // מזהה ה-Job
     "status": "running",          // pending|running|completed|failed|skipped
     "progress": 45,               // אחוזים (0-100)
     "total_items": 100,           // סה"כ פריטים
     "processed_items": 45,        // פריטים שעובדו
     "started_at": ISODate(...),
     "ended_at": ISODate(...),
     "trigger": "scheduled",       // scheduled|manual|api
     "user_id": 123456,            // אם קשור למשתמש ספציפי
     "logs": [...],                // עד 50 רשומות אחרונות
     "error_message": "...",       // במקרה כישלון
     "result": {...}               // תוצאה סופית
   }

**אינדקסים:**

.. code-block:: python

   JOB_RUNS_INDEXES = [
       {"keys": [("job_id", 1), ("started_at", -1)]},
       {"keys": [("status", 1)]},
       {"keys": [("started_at", -1)], "expireAfterSeconds": 604800},  # TTL 7 ימים
       {"keys": [("user_id", 1), ("job_id", 1)], "sparse": True},
   ]

UI / WebApp
-----------

גישה לדשבורד
~~~~~~~~~~~~

נכנסים ל: ``https://your-app.onrender.com/jobs/monitor``

.. note::
   הדשבורד דורש הרשאת Admin או Token תקין.

מה רואים בדשבורד
~~~~~~~~~~~~~~~~~

1. **רשימת Jobs** – כל ה-Jobs הרשומים במערכת עם סטטוס (מופעל/מושבת)
2. **הרצות פעילות** – Jobs שרצים כרגע עם אחוז התקדמות
3. **היסטוריה** – הרצות אחרונות (מה-DB)
4. **לוגים** – לחיצה על הרצה פותחת Modal עם לוגים מפורטים

Jobs סטטיים vs. דינמיים
~~~~~~~~~~~~~~~~~~~~~~~~

+------------------+----------------------------------------------+-------------------+
| סוג              | הסבר                                         | ``can_trigger``   |
+==================+==============================================+===================+
| **סטטי**         | מוגדר ב-``JobRegistry`` עם callback          | ``true``          |
+------------------+----------------------------------------------+-------------------+
| **דינמי**        | נוצר מפעולות משתמש (Drive/Reminders/Batch)   | ``false``         |
+------------------+----------------------------------------------+-------------------+

Jobs דינמיים לא ניתנים להפעלה ידנית מהדשבורד כי אין להם callback קבוע –
הם נוצרים כתגובה לפעולות משתמש ספציפיות.

API Reference
-------------

כל הנתיבים מוגנים ב-Bearer Token (``DB_HEALTH_TOKEN``).

GET /api/jobs
~~~~~~~~~~~~~

רשימת כל ה-Jobs הרשומים.

.. code-block:: bash

   curl -H "Authorization: Bearer $DB_HEALTH_TOKEN" \
        https://your-bot-api/api/jobs

**תשובה:**

.. code-block:: json

   {
     "jobs": [
       {
         "job_id": "cache_warming",
         "name": "Cache Warming",
         "category": "cache",
         "job_type": "repeating",
         "enabled": true,
         "interval_seconds": 3600,
         "can_trigger": true
       }
     ]
   }

GET /api/jobs/active
~~~~~~~~~~~~~~~~~~~~

הרצות פעילות בזמן אמת (מהזיכרון).

GET /api/jobs/{job_id}
~~~~~~~~~~~~~~~~~~~~~~

פרטי Job ספציפי + היסטוריית 20 הרצות אחרונות.

GET /api/jobs/runs/{run_id}
~~~~~~~~~~~~~~~~~~~~~~~~~~~

פרטי הרצה בודדת כולל לוגים מלאים.

POST /api/jobs/{job_id}/trigger
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

הפעלה ידנית של Job.

**תנאים:**

- ל-Job יש ``callback_name`` מוגדר
- ה-Job מופעל (``enabled=true``)
- אין הרצה פעילה (אלא אם ``allow_concurrent=true``)

.. code-block:: bash

   curl -X POST \
        -H "Authorization: Bearer $DB_HEALTH_TOKEN" \
        https://your-bot-api/api/jobs/cache_warming/trigger

אבטחה
-----

הגנה על ה-API
~~~~~~~~~~~~~

כל הנתיבים ``/api/jobs/*`` מוגנים ב-**Bearer Token**:

- ב-aiohttp (Bot API): Token נבדק ב-``services/webserver.py``
- ב-Flask (WebApp): פרוקסי לבוט עם אותו Token

**הגדרה:**

.. code-block:: bash

   export DB_HEALTH_TOKEN="your-secure-random-token"

.. warning::
   אל תחשפו את ``DB_HEALTH_TOKEN`` בלוגים או בצד לקוח!
   ה-WebApp משתמש בו רק בצד השרת (Server-to-Server).

ENV וקונפיגורציה
----------------

משתני סביבה
~~~~~~~~~~~

+-----------------------------------+-----------+-------------------------------------------+
| משתנה                             | ברירת מחדל | תיאור                                     |
+===================================+===========+===========================================+
| ``DB_HEALTH_TOKEN``               | (חובה)    | Token לאימות API                          |
+-----------------------------------+-----------+-------------------------------------------+
| ``BOT_JOBS_API_BASE_URL``         | –         | URL בסיס ל-API של הבוט (נדרש לטריגר)      |
+-----------------------------------+-----------+-------------------------------------------+
| ``BOT_API_BASE_URL``              | –         | Fallback ל-``BOT_JOBS_API_BASE_URL``      |
+-----------------------------------+-----------+-------------------------------------------+
| ``JOBS_STUCK_THRESHOLD_MINUTES``  | ``20``    | סף דקות לזיהוי Job תקוע                   |
+-----------------------------------+-----------+-------------------------------------------+
| ``JOBS_STUCK_MONITOR_INTERVAL_SECS`` | ``60`` | אינטרוול בדיקת Jobs תקועים              |
+-----------------------------------+-----------+-------------------------------------------+
| ``WEBAPP_URL``                    | –         | URL לקישורים ללוגים בהודעות ChatOps       |
+-----------------------------------+-----------+-------------------------------------------+

ChatOps – פקודת /jobs
---------------------

פקודות זמינות
~~~~~~~~~~~~~

+---------------------------+-------------------------------------------+
| פקודה                     | תיאור                                     |
+===========================+===========================================+
| ``/jobs``                 | סיכום כל ה-Jobs לפי קטגוריה               |
+---------------------------+-------------------------------------------+
| ``/jobs active``          | הרצות פעילות כרגע + אחוז התקדמות          |
+---------------------------+-------------------------------------------+
| ``/jobs failed``          | 10 כשלים אחרונים עם קישור ללוגים          |
+---------------------------+-------------------------------------------+
| ``/jobs <job_id>``        | פרטי Job + 5 הרצות אחרונות                |
+---------------------------+-------------------------------------------+
| ``/jobs <category>``      | Jobs בקטגוריה (backup/cache/sync/...)     |
+---------------------------+-------------------------------------------+

דוגמאות
~~~~~~~

**רשימת הרצות פעילות:**

.. code-block:: text

   /jobs active

   ⚡ הרצות פעילות:

   🔄 `cache_warming` - 45% (450/1000)
      [📋 לוגים](https://your-app/jobs/monitor?run_id=abc123)

**כשלים אחרונים:**

.. code-block:: text

   /jobs failed

   ❌ כשלים אחרונים:

   ❌ `drive_sync` 30/12 14:23
      `Connection timeout after 30s`
      [📋 לוגים](https://your-app/jobs/monitor?run_id=xyz789)

.. note::
   הקישורים ללוגים תלויים בהגדרת ``WEBAPP_URL``.

Alerts
------

הגדרות ב-alerts.yml
~~~~~~~~~~~~~~~~~~~

.. code-block:: yaml

   alerts:
     - name: job_failure_alert
       event_pattern: "job_failed"
       severity: error
       cooldown_seconds: 300
       message: "❌ Job {job_id} נכשל: {error}"

     - name: job_stuck_alert
       event_pattern: "job_stuck"
       severity: critical
       cooldown_seconds: 600
       message: "⚠️ Job {job_id} תקוע כבר {minutes} דקות"

Flow של Alerts
~~~~~~~~~~~~~~

1. ``JobTracker`` קורא ל-``emit_event("job_failed", ...)`` בכישלון
2. מערכת ה-Observability קולטת את האירוע
3. בדיקה מול ``alerts.yml`` ו-cooldown
4. שליחת התראה לערוץ המוגדר (Telegram/Slack)

**זיהוי Jobs תקועים:**

מתבצע ב-background loop (כל ``JOBS_STUCK_MONITOR_INTERVAL_SECS`` שניות):

1. סריקת ``job_runs`` עם ``status=running``
2. אם ``started_at`` לפני יותר מ-``JOBS_STUCK_THRESHOLD_MINUTES`` דקות
3. פליטת ``emit_event("job_stuck", ...)``

Troubleshooting
---------------

"הטריגר לא עובד"
~~~~~~~~~~~~~~~~

**בעיה:** לחיצה על כפתור "הפעל" בדשבורד לא עושה כלום.

**פתרונות:**

1. וודאו שהוגדר ``BOT_JOBS_API_BASE_URL`` (או ``BOT_API_BASE_URL``)
2. וודאו שהוגדר ``DB_HEALTH_TOKEN`` **גם בבוט וגם ב-WebApp**
3. בדקו שה-URL נגיש מה-WebApp לבוט (אין firewall/network issues)
4. בדקו לוגים: ``jobs_trigger_failed`` או ``jobs_api_proxy_error``

"אין jobs דינמיים בדשבורד"
~~~~~~~~~~~~~~~~~~~~~~~~~~

**בעיה:** רואים רק Jobs סטטיים, לא רואים הרצות של Drive/Reminders.

**סיבות אפשריות:**

1. **אין עדיין הרצות** – המשתמש לא ביצע פעולות שיוצרות Jobs דינמיים
2. **TTL** – הרצות נמחקו אחרי 7 ימים
3. **הרשאות** – בדקו שיש גישה לקולקציית ``job_runs``

"לא מגיעים Alerts"
~~~~~~~~~~~~~~~~~~

**בעיה:** Jobs נכשלים אבל לא מגיעות התראות.

**פתרונות:**

1. וודאו קיום ותקינות ``config/alerts.yml``
2. בדקו ש-``PyYAML`` מותקן
3. בדקו cooldown – ייתכן שהתראה נשלחה לאחרונה
4. וודאו שערוץ ההתראות מוגדר נכון

"Job תקוע אבל אין התראה"
~~~~~~~~~~~~~~~~~~~~~~~~~

**בעיה:** Job רץ כבר שעות ולא מגיעה התראת "stuck".

**פתרונות:**

1. בדקו ש-``JOBS_STUCK_THRESHOLD_MINUTES`` לא גדול מדי
2. וודאו שה-background loop רץ (בדקו לוגים של ``stuck_jobs_check``)
3. בדקו cooldown ב-alerts.yml (``cooldown_seconds: 600``)

"השרת מחזיר 401/403"
~~~~~~~~~~~~~~~~~~~~~

**בעיה:** API מחזיר שגיאת הרשאה.

**פתרונות:**

1. וודאו שה-Token נשלח כ-``Authorization: Bearer <token>``
2. וודאו שאותו ``DB_HEALTH_TOKEN`` מוגדר בשני הצדדים
3. בדקו שאין רווחים/שורות חדשות ב-Token

"לוגים ריקים בדשבורד"
~~~~~~~~~~~~~~~~~~~~~

**בעיה:** לוגים לא מופיעים למרות שה-Job רץ.

**סיבות:**

1. לוגים נשמרים בפעימות (כל 10 לוגים או error)
2. אם ה-Job מסתיים מהר, ייתכן שהלוגים לא הספיקו להישמר
3. בדקו ``logs`` בדוקומנט ב-MongoDB ישירות

Best Practices
--------------

1. **הגדירו כל המשתנים הנדרשים** לפני פריסה:

   .. code-block:: bash

      export DB_HEALTH_TOKEN="$(openssl rand -hex 32)"
      export BOT_JOBS_API_BASE_URL="https://your-bot.onrender.com"
      export WEBAPP_URL="https://your-webapp.onrender.com"

2. **אל תשתמשו באותו Token** ל-DB_HEALTH_TOKEN בסביבות שונות

3. **הגדירו Alerts חכמים** עם cooldown מתאים למניעת spam

4. **נטרו את גודל הקולקציה** – למרות ה-TTL, יכול להצטבר הרבה מידע

ראו גם
------

- :doc:`/observability` – סקירה כללית של Observability
- :doc:`/alerts` – מערכת ההתראות
- :doc:`/chatops/commands` – רשימת פקודות ChatOps
- :doc:`/webapp/overview` – סקירת WebApp
