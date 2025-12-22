Visual Rule Engine - מנוע כללים ויזואלי
==========================================

.. note::
   פיצ'ר זה זמין רק למשתמשי אדמין (``ADMIN_USER_IDS``).
   ראו :doc:`security` להגדרת הרשאות.

סקירה כללית
------------

ה-Visual Rule Engine מאפשר ליצור כללים מורכבים להתראות (Alerts) בממשק גרפי,
ללא צורך בכתיבת קוד. כל כלל מורכב מ:

- **תנאים (Conditions)** - מתי הכלל יופעל
- **פעולות (Actions)** - מה לעשות כשהכלל מתאים

**מתי להשתמש:**

- סינון התראות רועשות (Suppress)
- פתיחת Issue אוטומטי ב-GitHub עבור שגיאות חדשות
- שליחת webhook לשירות חיצוני
- ניתוב התראות לפי חומרה/סביבה/פרויקט

**מה זה לא:**

- לא תחליף ל-Alertmanager rules (Prometheus)
- לא מערכת Workflow מלאה
- לא מנגנון Rate-limiting להתראות

זרימת ההחלטה
-------------

התרשים הבא מסביר מה קורה כשהתראה נכנסת למערכת:

.. mermaid::

   graph TD
       A[Alert Received] --> B{Enabled Rules exist?}
       B -- No --> C[Send Alert - Default]
       B -- Yes --> D{Evaluate Rules}
       
       D --> E{Match Found?}
       E -- No --> C
       E -- Yes --> F{Action Type}
       
       F -- Suppress --> G[🛑 Stop / Drop Alert]
       F -- Send Alert --> C
       F -- GitHub Issue --> H[📝 Create Issue]
       F -- Webhook --> I[🌐 Call Webhook]
       
       H --> C
       I --> C

.. important::
   הערכת כללים מתבצעת ב-``internal_alerts.emit_internal_alert`` **לפני** שליחה ל-forwarders (Telegram/Slack).
   פעולת ``suppress`` עוצרת את שליחת ההתראה לחלוטין.

UI Walkthrough
--------------

גישה למסך הכללים
^^^^^^^^^^^^^^^^^

1. היכנסו ל-WebApp כמשתמש אדמין
2. נווטו ל: **Admin → Visual Rules** (``/admin/rules``)
3. תראו את רשימת הכללים הקיימים

יצירת כלל חדש
^^^^^^^^^^^^^

1. לחצו על **"כלל חדש"**
2. הזינו שם לכלל
3. הוסיפו תנאים (Conditions):
   
   - לחצו **"+ Add Condition"**
   - בחרו שדה (Field)
   - בחרו אופרטור (Operator)
   - הזינו ערך (Value)

4. ליצירת תנאי מורכב, השתמשו ב-Groups:
   
   - **AND** - כל התנאים חייבים להתקיים
   - **OR** - לפחות תנאי אחד חייב להתקיים
   - **NOT** - הפיכת תנאי (בדיוק ילד אחד)

5. הוסיפו פעולות (Actions):
   
   - לחצו **"+ Add Action"**
   - בחרו סוג פעולה

6. בדקו את הכלל עם כפתור **"Test"**
7. שמרו עם כפתור **"Save"**

הפעלה/כיבוי כלל
^^^^^^^^^^^^^^^^

- לחצו על מתג ה-Toggle ליד הכלל
- כלל מכובה לא יוערך אבל נשמר

מחיקת כלל
^^^^^^^^^^

- לחצו על אייקון פח האשפה ליד הכלל
- אשרו את המחיקה

מבנה הכלל (JSON Schema)
------------------------

התרשים הבא מציג את היררכיית מבנה הכלל:

.. mermaid::

   graph TD
       Root[Rule Object] --> Conditions
       Root --> Actions
       
       Conditions --> G1[Group AND]
       G1 --> C1[Condition: alert_type == sentry]
       G1 --> C2[Condition: is_new_error == true]
       
       Actions --> A1[Action: create_github_issue]
       
       style G1 fill:#e1f5fe,stroke:#01579b
       style C1 fill:#fff9c4,stroke:#fbc02d
       style C2 fill:#fff9c4,stroke:#fbc02d
       style A1 fill:#e8f5e9,stroke:#2e7d32

שדות הכלל
^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - שדה
     - סוג
     - תיאור
   * - ``rule_id``
     - string
     - מזהה ייחודי (נוצר אוטומטית)
   * - ``name``
     - string
     - שם הכלל (חובה)
   * - ``enabled``
     - boolean
     - האם הכלל פעיל
   * - ``conditions``
     - object
     - עץ התנאים
   * - ``actions``
     - array
     - רשימת פעולות

דוגמה 1: כלל פשוט (Suppress)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: json

   {
     "name": "השתק התראות Info בסביבת פיתוח",
     "conditions": {
       "type": "condition",
       "field": "environment",
       "operator": "eq",
       "value": "development"
     },
     "actions": [
       {
         "type": "suppress"
       }
     ]
   }

דוגמה 2: כלל עם Group (AND)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: json

   {
     "name": "התראה על שגיאות קריטיות בפרודקשן",
     "conditions": {
       "type": "group",
       "operator": "AND",
       "children": [
         {
           "type": "condition",
           "field": "severity",
           "operator": "eq",
           "value": "critical"
         },
         {
           "type": "condition",
           "field": "environment",
           "operator": "eq",
           "value": "production"
         }
       ]
     },
     "actions": [
       {
         "type": "webhook",
         "webhook_url": "https://hooks.slack.com/services/xxx"
       }
     ]
   }

דוגמה 3: OR עם NOT פנימי
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: json

   {
     "name": "התראה כשלא בשעות עבודה",
     "conditions": {
       "type": "group",
       "operator": "OR",
       "children": [
         {
           "type": "condition",
           "field": "hour_of_day",
           "operator": "lt",
           "value": 8
         },
         {
           "type": "condition",
           "field": "hour_of_day",
           "operator": "gt",
           "value": 18
         }
       ]
     },
     "actions": [
       {
         "type": "send_alert",
         "channel": "telegram",
         "severity": "warning"
       }
     ]
   }

דוגמה 4: GitHub Issue לשגיאות Sentry חדשות
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: json

   {
     "name": "פתיחת Issue בגיטהאב על שגיאת Sentry חדשה",
     "conditions": {
       "type": "group",
       "operator": "AND",
       "children": [
         {
           "type": "condition",
           "field": "alert_type",
           "operator": "eq",
           "value": "sentry_issue"
         },
         {
           "type": "condition",
           "field": "is_new_error",
           "operator": "eq",
           "value": "True"
         }
       ]
     },
     "actions": [
       {
         "type": "create_github_issue",
         "severity": "warning",
         "title_template": "[Sentry] {{summary}}"
       }
     ]
   }

**הסבר:**

- **Condition 1**: בודק שמדובר בהתראת Sentry
- **Condition 2**: בודק שזו שגיאה חדשה (``is_new_error == True``)
- **Action**: יוצר Issue בגיטהאב עם כותרת דינמית
- **Templating**: השימוש ב-``{{summary}}`` מחליף אוטומטית את התוכן בתיאור השגיאה

פעולות (Actions)
-----------------

suppress
^^^^^^^^^

**מה עושה:** מסמן את ההתראה כ-"silenced" ועוצר את שליחתה לכל הערוצים.

**איפה זה עוצר:** ב-``internal_alerts.emit_internal_alert``, לפני שליחה ל-Telegram/Slack.

.. code-block:: json

   {
     "type": "suppress"
   }

send_alert
^^^^^^^^^^^

**מה עושה:** שולח התראה מותאמת לערוץ ספציפי.

**ערוצים נתמכים:**

- ``telegram`` / ``default`` - נתמך מלא
- ``slack`` - בתכנון

**פרמטרים:**

.. list-table::
   :header-rows: 1

   * - פרמטר
     - סוג
     - תיאור
   * - ``channel``
     - string
     - ערוץ היעד (``telegram``, ``default``)
   * - ``severity``
     - string
     - חומרה להודעה
   * - ``message_template``
     - string
     - תבנית הודעה עם placeholders

**Placeholders זמינים:**

- ``{{rule_name}}`` - שם הכלל
- ``{{summary}}`` - תקציר ההתראה
- ``{{severity}}`` - חומרה
- ``{{triggered_conditions}}`` - רשימת תנאים שהותאמו

.. code-block:: json

   {
     "type": "send_alert",
     "channel": "telegram",
     "severity": "warning",
     "message_template": "🔔 {{rule_name}}: {{summary}}"
   }

create_github_issue
^^^^^^^^^^^^^^^^^^^^

**מה עושה:** יוצר Issue חדש ב-GitHub Repository.

**דרישות:**

- ``GITHUB_TOKEN`` מוגדר עם הרשאת ``repo``
- ``GITHUB_REPO`` מוגדר (בפורמט ``owner/repo``)

**פרמטרים:**

.. list-table::
   :header-rows: 1

   * - פרמטר
     - סוג
     - תיאור
   * - ``title_template``
     - string
     - תבנית כותרת (תומכת ב-placeholders)
   * - ``severity``
     - string
     - Label שיתווסף ל-Issue

**התנהגות "כבר קיים Issue":**

- המערכת בודקת אם יש Issue פתוח עם אותה כותרת
- אם קיים - לא נוצר Issue כפול
- הבדיקה מבוססת על Title בלבד

.. code-block:: json

   {
     "type": "create_github_issue",
     "title_template": "[Alert] {{summary}}",
     "severity": "critical"
   }

webhook
^^^^^^^^

**מה עושה:** שולח HTTP POST ל-URL חיצוני עם נתוני ההתראה.

**Payload:** נתוני ההתראה המלאים (``alert_data``) בפורמט JSON.

**Timeouts:** 10 שניות.

**SSRF Guardrails:**

- רק ``http://`` או ``https://``
- חסימת כתובות פנימיות (Private IPs, Loopback, Link-local)
- בדיקת DNS resolution לכל הכתובות

**Allowlist (אופציונלי):**

- ``ALLOWED_WEBHOOK_HOSTS`` - רשימת hostnames מדויקים (CSV)
- ``ALLOWED_WEBHOOK_SUFFIXES`` - סיומות דומיין (CSV, למשל ``.example.com``)

.. code-block:: json

   {
     "type": "webhook",
     "webhook_url": "https://hooks.slack.com/services/T00/B00/xxxx"
   }

.. warning::
   אם מוגדרים ``ALLOWED_WEBHOOK_HOSTS`` או ``ALLOWED_WEBHOOK_SUFFIXES``,
   רק URLs שמתאימים ל-allowlist יישלחו. אחרים ייחסמו.

Evaluation Context - שדות זמינים
---------------------------------

להלן רשימת כל השדות שזמינים לשימוש בתנאים:

שדות בסיסיים מההתראה
^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - שדה
     - סוג
     - תיאור
     - מקור
   * - ``alert_name``
     - string
     - שם ההתראה
     - ``alert_payload.name``
   * - ``severity``
     - string
     - רמת חומרה (info/warning/critical/anomaly)
     - ``alert_payload.severity``
   * - ``summary``
     - string
     - תיאור קצר
     - ``alert_payload.summary``
   * - ``source``
     - string
     - מקור ההתראה (sentry/internal/external)
     - ``alert_payload.source``
   * - ``is_silenced``
     - boolean
     - האם ההתראה הושתקה
     - ``alert_payload.silenced``

שדות מ-details
^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - שדה
     - סוג
     - תיאור
   * - ``alert_type``
     - string
     - סוג התראה (sentry_issue, deployment_event, וכו')
   * - ``sentry_issue_id``
     - string
     - מזהה ה-Issue ב-Sentry
   * - ``sentry_short_id``
     - string
     - מזהה קצר (PROJECT-123)
   * - ``project``
     - string
     - שם הפרויקט
   * - ``environment``
     - string
     - סביבה (production/staging/development)
   * - ``error_signature``
     - string
     - חתימת השגיאה (לזיהוי חוזר)
   * - ``error_signature_hash``
     - string
     - Hash של החתימה
   * - ``is_new_error``
     - boolean
     - האם זו שגיאה חדשה
   * - ``error_message``
     - string
     - הודעת השגיאה
   * - ``stack_trace``
     - string
     - Stack trace מלא
   * - ``occurrence_count``
     - int
     - מספר הופעות
   * - ``culprit``
     - string
     - מיקום השגיאה (פונקציה/קובץ)
   * - ``action``
     - string
     - פעולה (triggered/resolved)

שדות מדדים
^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - שדה
     - סוג
     - תיאור
   * - ``error_rate``
     - float
     - שיעור שגיאות
   * - ``requests_per_minute``
     - int
     - בקשות לדקה
   * - ``latency_avg_ms``
     - int
     - Latency ממוצע (ms)

שדות זמן (מחושבים)
^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :header-rows: 1

   * - שדה
     - סוג
     - תיאור
   * - ``hour_of_day``
     - int (0-23)
     - שעה נוכחית (UTC)
   * - ``day_of_week``
     - int (0-6)
     - יום בשבוע (0=ראשון, 6=שבת)

אופרטורים
----------

.. list-table::
   :header-rows: 1

   * - אופרטור
     - תיאור
     - דוגמה
   * - ``eq``
     - שווה
     - ``severity eq critical``
   * - ``ne``
     - לא שווה
     - ``environment ne production``
   * - ``gt``
     - גדול מ-
     - ``error_rate gt 0.05``
   * - ``gte``
     - גדול או שווה ל-
     - ``occurrence_count gte 10``
   * - ``lt``
     - קטן מ-
     - ``hour_of_day lt 8``
   * - ``lte``
     - קטן או שווה ל-
     - ``latency_avg_ms lte 500``
   * - ``contains``
     - מכיל מחרוזת
     - ``error_message contains "timeout"``
   * - ``not_contains``
     - לא מכיל מחרוזת
     - ``summary not_contains "test"``
   * - ``starts_with``
     - מתחיל ב-
     - ``alert_name starts_with "API"``
   * - ``ends_with``
     - מסתיים ב-
     - ``project ends_with "-prod"``
   * - ``regex``
     - התאמת ביטוי רגולרי
     - ``error_message regex ".*Error.*"``
   * - ``in``
     - ברשימה
     - ``severity in ["critical", "warning"]``
   * - ``not_in``
     - לא ברשימה
     - ``environment not_in ["development", "test"]``

.. note::
   אופרטור ``regex`` מוגן מפני ReDoS:
   
   - אורך דפוס מקסימלי: 200 תווים
   - אורך קלט מקסימלי: 10,000 תווים
   - Timeout: 1 שנייה
   - זיהוי דפוסים מסוכנים (catastrophic backtracking)

אבטחה
------

הרשאות אדמין
^^^^^^^^^^^^^

- רק משתמשים ב-``ADMIN_USER_IDS`` יכולים לגשת ל-API ולממשק
- בדיקת הרשאות מתבצעת בכל endpoint

הגדרת אדמינים:

.. code-block:: bash

   export ADMIN_USER_IDS="123456789,987654321"

Webhook SSRF Protection
^^^^^^^^^^^^^^^^^^^^^^^^

ברירת מחדל - חסימת כתובות פנימיות:

- Private IPs (``10.x.x.x``, ``192.168.x.x``, ``172.16-31.x.x``)
- Loopback (``127.0.0.1``, ``::1``)
- Link-local (``169.254.x.x``)
- Multicast / Unspecified

**Allowlist מפורש:**

למקרים שנדרש שליטה מדויקת על יעדים:

.. code-block:: bash

   # רשימת hostnames מדויקים
   export ALLOWED_WEBHOOK_HOSTS="hooks.slack.com,api.pagerduty.com"
   
   # או סיומות דומיין
   export ALLOWED_WEBHOOK_SUFFIXES=".example.com,.mycompany.net"

.. warning::
   כאשר מוגדר allowlist, רק URLs שמתאימים יישלחו.
   כתובות שלא ב-allowlist ייחסמו גם אם הן ציבוריות.

הסימולטור
-----------

הסימולטור מאפשר לבדוק כללים מבלי להפעיל אותם בפועל.

.. mermaid::

   sequenceDiagram
       participant User
       participant Simulator
       participant Engine
       participant GitHub
       
       Note over User, GitHub: 🧪 Simulation Mode
       User->>Simulator: Send Rule + Test Data
       Simulator->>Engine: Evaluate (Dry Run)
       Engine-->>Simulator: Result: Would create Issue
       Simulator-->>User: Show Green Light ✅
       
       Note over User, GitHub: 🚀 Real Production
       User->>Engine: Save Rule
       Engine->>GitHub: Create Issue via API

**מה בטוח לעשות בסימולטור:**

- לבדוק כל כלל
- לשנות נתוני בדיקה
- לראות אילו פעולות היו מתבצעות

**מה לא קורה בסימולטור:**

- לא נפתח Issue בגיטהאב
- לא נשלח webhook
- לא נשלחת התראה

משתני סביבה
-----------

ראו :doc:`environment-variables` לרשימה המלאה.

משתנים עיקריים לפיצ'ר:

.. list-table::
   :header-rows: 1

   * - משתנה
     - תיאור
     - ברירת מחדל
   * - ``ADMIN_USER_IDS``
     - מזהי משתמשים עם הרשאות אדמין (CSV)
     - "" (ריק)
   * - ``ALLOWED_WEBHOOK_HOSTS``
     - Allowlist ל-webhooks (CSV)
     - "" (ריק)
   * - ``ALLOWED_WEBHOOK_SUFFIXES``
     - סיומות דומיין מורשות (CSV)
     - "" (ריק)
   * - ``GITHUB_TOKEN``
     - טוקן GitHub ליצירת Issues
     - -
   * - ``GITHUB_REPO``
     - ריפו ליצירת Issues (``owner/repo``)
     - -
   * - ``RULES_VERBOSE_LOGGING``
     - לוגים מפורטים (לדיבוג)
     - ``false``

פתרון בעיות
-----------

"הכלל לא רץ"
^^^^^^^^^^^^^^

**אפשרות 1: אין כללים פעילים**

- ודאו שיש לפחות כלל אחד עם ``enabled: true``
- בדקו ב-API: ``GET /api/rules?enabled=true``

**אפשרות 2: המשתמש לא אדמין**

- ודאו שה-``user_id`` מופיע ב-``ADMIN_USER_IDS``

**אפשרות 3: כשל ולידציה**

- הפעילו ``RULES_VERBOSE_LOGGING=true``
- בדקו בלוגים שגיאות ולידציה

**אפשרות 4: תנאים לא מתאימים**

- השתמשו בסימולטור עם נתוני הבדיקה
- ודאו שהשדות קיימים ב-context

"webhook נחסם"
^^^^^^^^^^^^^^^^

**אפשרות 1: כתובת פנימית**

- webhooks לא יכולים לפנות ל-IPs פרטיים
- השתמשו ב-URL ציבורי

**אפשרות 2: לא ב-allowlist**

- אם הגדרתם ``ALLOWED_WEBHOOK_HOSTS`` או ``ALLOWED_WEBHOOK_SUFFIXES``,
  ודאו שה-URL מתאים

**אפשרות 3: DNS resolution נכשל**

- ודאו שה-hostname קיים ונגיש

"is_new_error תמיד False"
^^^^^^^^^^^^^^^^^^^^^^^^^^

**אפשרות 1: אין מספיק שדות לשגיאה**

הפרמטרים הבאים נדרשים לחישוב חתימה:

- ``error_message`` או ``message``
- ``culprit`` (מיקום השגיאה)

**אפשרות 2: אין חתימה**

- ודאו שה-``error_signature_hash`` מחושב
- בדקו שפונקציית ``enrich_alert_with_signature`` רצה

**אפשרות 3: השגיאה כבר נראתה**

- ``is_new_error`` יהיה ``True`` רק בפעם הראשונה
- חתימות נשמרות ב-DB

"GitHub Issue לא נוצר"
^^^^^^^^^^^^^^^^^^^^^^^^

**אפשרות 1: חסר GITHUB_TOKEN**

.. code-block:: bash

   export GITHUB_TOKEN=ghp_xxxxxxxxxxxx
   export GITHUB_REPO=owner/repo

**אפשרות 2: הרשאות Token**

- נדרשת הרשאת ``repo`` לפתיחת Issues

**אפשרות 3: Issue כפול**

- המערכת בודקת Issues קיימים עם אותה כותרת
- בדקו אם קיים Issue פתוח

Test Plan
---------

צ'קליסט ידני לאימות הפיצ'ר:

.. list-table::
   :header-rows: 1

   * - בדיקה
     - תוצאה צפויה
   * - יצירת כלל suppress לסביבת dev
     - התראות מ-dev לא נשלחות
   * - יצירת כלל webhook ל-host מאושר
     - webhook נשלח בהצלחה
   * - יצירת כלל webhook ל-host לא מאושר
     - webhook נחסם עם log warning
   * - בדיקת כלל בסימולטור
     - תוצאה ירוקה/אדומה ללא side effects
   * - יצירת כלל GitHub Issue
     - Issue נפתח בריפו
   * - ניסיון גישה ללא הרשאת אדמין
     - קבלת 403 Forbidden

API Reference
-------------

.. list-table::
   :header-rows: 1

   * - Endpoint
     - Method
     - תיאור
   * - ``/api/rules``
     - GET
     - רשימת כללים
   * - ``/api/rules``
     - POST
     - יצירת כלל חדש
   * - ``/api/rules/{id}``
     - GET
     - קבלת כלל ספציפי
   * - ``/api/rules/{id}``
     - PUT
     - עדכון כלל
   * - ``/api/rules/{id}``
     - DELETE
     - מחיקת כלל
   * - ``/api/rules/{id}/toggle``
     - POST
     - הפעלה/כיבוי כלל
   * - ``/api/rules/fields``
     - GET
     - שדות זמינים
   * - ``/api/rules/test``
     - POST
     - בדיקת כלל (סימולטור)

קישורים
-------

- :doc:`environment-variables` - משתני סביבה
- :doc:`alerts` - מערכת ההתראות
- :doc:`observability` - Observability Dashboard
