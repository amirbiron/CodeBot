התראות מבוססות לוגים (Log‑based Alerts)
=========================================

מה זה ולמה
-----------
מערכת התראות המבוססת על לוגים מנתחת את זרם האירועים של האפליקציה ומזהה תקלות בצורה חכמה באמצעות:

- סיווג שגיאות לפי חתימות (Signatures)
- Allowlist לרעשים ידועים כדי למנוע התראות שווא
- קיבוץ אירועים לפי ``fingerprint`` כדי לאחד שגיאות זהות
- מנגנון ``Cooldown`` שמונע הצפה של אותן התראות בפרק זמן קצר

הרכיבים בקוד
-------------
- ``monitoring/log_analyzer.py`` – ניתוח וקיבוץ אירועים מהלוגים
- ``monitoring/error_signatures.py`` – חתימות לזיהוי/סיווג שגיאות
- ``internal_alerts.py`` – שליחה וניהול התראות פנימיות, כולל מנגנון de‑dup
- ``scripts/run_log_aggregator.py`` – הרצה כ‑Sidecar מזרם הלוגים (Option A)

קבצי קונפיג
------------
- ``config/error_signatures.yml`` – הגדרת חתימות לזיהוי ודירוג שגיאות
- ``config/alerts.yml`` – ספים, קיבוץ, וחלונות זמן ל־Cooldown

דוגמה מינימלית: ``config/error_signatures.yml``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
מבנה הקובץ הוא מיפוי קטגוריה→רשימת regex, ועוד ``noise_allowlist`` (JSON גם נתמך):

.. code-block:: yaml

   noise_allowlist:
     - "Broken pipe|context canceled|499"
   critical:
     - "(Out of memory|OOMKilled)"
   network_db:
     - "(socket hang up|ECONNRESET|ETIMEDOUT|EAI_AGAIN)"
   app_runtime:
     - "(TypeError:|ReferenceError:|UnhandledPromiseRejection)"

דוגמה מינימלית: ``config/alerts.yml``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
.. code-block:: yaml

   window_minutes: 5
   min_count_default: 3
   cooldown_minutes: 10
   immediate_categories: ["critical"]

Option B – חיבור בתוך הקוד (מומש)
----------------------------------
Option B פעיל כברירת מחדל בקוד דרך Processor של ``structlog`` ואגרגטור יחיד (singleton).
ניתן להפעיל במצב צל (Shadow) כדי לאמת קיבוץ וסיווג בלי לשלוח התראות לסינקים.

משתני סביבה
~~~~~~~~~~~~
.. code-block:: bash

   # הפעלת האגרגטור (חובה להפעלה מלאה)
   export LOG_AGGREGATOR_ENABLED=1

   # מצב צל: מבצע קיבוץ/סיווג אך לא שולח התראות (אופציונלי)
   export LOG_AGGREGATOR_SHADOW=1

   # מיקומי קונפיג (ניתן להשאיר כברירת מחדל)
   export ERROR_SIGNATURES_PATH="config/error_signatures.yml"
   export ALERTS_GROUPING_CONFIG="config/alerts.yml"

   # סינקים של התראות (בחרו אחד או יותר)
   export ALERT_TELEGRAM_BOT_TOKEN="xxxx"
   export ALERT_TELEGRAM_CHAT_ID="123456"
   export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."

Option A – Sidecar מזרם לוגים
------------------------------
לתרחישים בהם רוצים להריץ אגרגטור חיצוני מזרם הלוגים (ללא חיבור פנימי):

.. code-block:: bash

   # דוגמה עקרונית – הזרמה מהלוגים לתוך האגרגטור
   render logs ... | python -u scripts/run_log_aggregator.py

ספים וקיבוץ – ברירות מחדל
--------------------------
- חלון זמן: 5 דקות (``window_minutes=5``)
- ספירה מינימלית: ``min_count_default=3`` לפני שליחה
- Cooldown: 10 דקות בין התראות דומות (``cooldown_minutes=10``)
- קטגוריה ``critical`` – שליחה מיידית גם ללא ספירה מצטברת

אסטרטגיית fingerprint וקנוניקליזציה
-------------------------------------
- זיהוי תבניות נפוצות ומיפוין לצורה קנונית (דוגמאות):
  - ``Out of memory|OOMKilled``
  - ``gunicorn.*worker timeout``
  - ``certificate verify failed|x509: .* expired``
  - ``ECONNRESET|ETIMEDOUT|EAI_AGAIN|socket hang up``
  - ``Too many open files|ENFILE|EMFILE``
  - ``No space left on device|ENOSPC``
  - ``Traceback\(|UnhandledPromiseRejection|TypeError:|ReferenceError:``
  - ``Exited with code (?!0)\d+``
- נפילה לקנוניקליזציה כללית: החלפת hex (``0x...``) ל־``0x?`` ומספרים ל־``#``, חיתוך לאורך 200 תווים, lowercase.
- יצירת fingerprint: ``sha1("{category}|{canonical}")[:12]`` – יציב לקיבוץ שגיאות דומות.

צ'קליסט למפתחים
----------------
- הגדירו ENV לפני הפעלת השירות: ``LOG_AGGREGATOR_ENABLED=1``; לשלב הצללה: ``LOG_AGGREGATOR_SHADOW=1``
- ודאו לוגים עם שדות שימושיים: ``event``, ו/או ``error``/``message``, אופציונלי: ``error_code``, ``operation``, ``request_id``
- עדכנו ``ERROR_SIGNATURES_PATH``/``ALERTS_GROUPING_CONFIG`` אם אתם משתמשים בקבצים מותאמים
- אל תייצרו לוגים עם האירועים ``internal_alert``/``alert_received`` בזרם העסקי כדי למנוע לולאות

בדיקה מקומית (סימולציה)
------------------------
הגדירו ENV והפעילו קטע בדיקה שמדמה שגיאה שתסווג לקבוצה:

.. code-block:: python

   import os
   os.environ["LOG_AGGREGATOR_ENABLED"] = "1"
   # אופציונלי: os.environ["LOG_AGGREGATOR_SHADOW"] = "1"
   # אופציונלי: os.environ["ERROR_SIGNATURES_PATH"] = "config/error_signatures.yml"
   # אופציונלי: os.environ["ALERTS_GROUPING_CONFIG"] = "config/alerts.yml"

   import observability as obs
   obs.setup_structlog_logging("INFO")

   # ידמה תקלה "socket hang up" (network_db) – תיגזר לקבוצה אחת
   obs.emit_event("db_call_failed", severity="error", error="socket hang up during query")

הנחיות לסוכני AI
-----------------
- כשצריך סטטוס בזמן אמת, הסתמכו על ChatOps – זה ה‑Source of Truth
- פקודות שימושיות: ראו :doc:`../chatops/observe` ו‑:doc:`../chatops/commands`
  - ``/observe -v`` מציג ספירות Alerts (DB/Memory) לפי חלון זמן והצלבה מול Dispatch Log
  - ``/errors`` מציג טעימות מהטעויות האחרונות (fallback כאשר אין Sentry)

אבטחה ופרטיות
--------------
- Redaction אוטומטי למפתחות רגישים בלוגים (token/password/secret/cookie/authorization)
- הגבילו דוגמאות בלוגים כדי למנוע חשיפת PII
- הימנעו מתבניות regex יקרות (".*" מרובה/גרידיות על מחרוזות ארוכות)

Rollout מומלץ
--------------
1. הפעלה ב‑Staging עם ``LOG_AGGREGATOR_SHADOW=1``
2. כוונון Allowlist/חתימות עד ירידה ברעשי שווא
3. הסרה של Shadow והפעלת שליחה לסינקים בסביבות הדרגתית עד Production

Troubleshooting
---------------
- לא נשלחות התראות: ודאו ``LOG_AGGREGATOR_ENABLED=1`` וסינק מוגדר (טלגרם/Slack)
- אין קיבוץ: בדקו ``ERROR_SIGNATURES_PATH`` תקין ושה‑regex תואם את הודעות השגיאה
- לולאות התראות: לעולם אל תשתמשו בלוג של Alert בתוך מסלול השליחה; סמנו/בדקו דגלים כגון ``internal_alert``/``alert_received`` כדי למנוע הדלפות חזרה ללוגים
- ביצועים: העדיפו חתימות מדויקות; אל תבצעו regex גורף על payloadים גדולים

ראו גם
-------
- :doc:`../alerts`
- :doc:`../observability`

קישורים לקוד
-------------
- ``monitoring/log_analyzer.py``
- ``monitoring/error_signatures.py``
- ``internal_alerts.py``
