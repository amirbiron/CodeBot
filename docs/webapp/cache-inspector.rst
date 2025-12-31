.. _webapp-cache-inspector:

Cache Inspector (לוח בקרה של Redis)
=====================================

מה זה Cache Inspector?
-----------------------

**Cache Inspector** הוא כלי אדמין שמאפשר לצפות ולנהל את ה-Redis cache בצורה בטוחה.
הכלי נותן נראות ל:

- סטטיסטיקות Redis (זיכרון, Hit Rate, מספר מפתחות)
- חיפוש מפתחות לפי תבנית
- צפייה ב-TTL וסטטוס
- מחיקת מפתחות בצורה מבוקרת

למה צריך את זה?
^^^^^^^^^^^^^^^

- **ניטור ביצועים**: מעקב אחר צריכת זיכרון ו-Hit Rate של ה-cache
- **איתור בעיות**: זיהוי מפתחות שתופסים יותר מדי מקום או בעלי TTL לא נכון
- **ניקוי ידני**: מחיקת מפתחות ספציפיים כשצריך לרענן cache
- **דיבוג**: הבנת מה נמצא ב-cache ברגע נתון

איך נכנסים?
-----------

**דרך ה-UI:**

1. כנסו לדף **Settings** (הגדרות)
2. גללו לקטגוריית **כלי אדמין**
3. לחצו על **Cache Inspector**

**ישירות:**

.. code-block:: text

   GET /admin/cache-inspector

.. note::
   הדף זמין **רק לאדמינים**. משתמשים ללא הרשאות יקבלו שגיאת 403.

יכולות עיקריות
--------------

סטטיסטיקות כלליות
^^^^^^^^^^^^^^^^^^

בראש הדף מוצגות הסטטיסטיקות הבאות:

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - מטריקה
     - תיאור
   * - **Memory**
     - כמות הזיכרון בשימוש (למשל ``1.5M``)
   * - **Hit Rate**
     - אחוז הפגיעות ב-cache (ככל שגבוה יותר, טוב יותר)
   * - **Total Keys**
     - מספר המפתחות הכולל ב-Redis
   * - **Connected Clients**
     - מספר הלקוחות המחוברים כרגע
   * - **Hits / Misses**
     - מספר הפגיעות והחטאות מאז עליית Redis
   * - **Uptime**
     - זמן פעילות Redis

חיפוש מפתחות
^^^^^^^^^^^^^

ניתן לחפש מפתחות לפי תבנית (Pattern):

- ``*`` - כל המפתחות
- ``user:*`` - כל המפתחות שמתחילים ב-``user:``
- ``*:settings`` - כל המפתחות שמסתיימים ב-``:settings``
- ``file:123:*`` - כל המפתחות של קובץ ספציפי

.. warning::
   החיפוש משתמש בפקודת **SCAN** ולא ב-**KEYS** כדי למנוע חסימת Redis.
   המשמעות: חיפוש בטוח גם ב-Redis עם מיליוני מפתחות.

**מגבלת תוצאות**: ניתן להגדיר כמה מפתחות להציג (עד 500 לדף).

הצגת TTL וסטטוס
^^^^^^^^^^^^^^^^

לכל מפתח מוצג סטטוס צבעוני:

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - סטטוס
     - צבע
     - משמעות
   * - **Active**
     - ירוק
     - מפתח פעיל עם TTL גדול מדקה
   * - **Expiring**
     - כתום
     - יפוג תוך דקה או פחות
   * - **Persistent**
     - כחול
     - ללא TTL (לא יפוג אוטומטית)
   * - **Expired**
     - אדום
     - פג תוקף / לא קיים

פעולות מחיקה
^^^^^^^^^^^^^

**מחיקת מפתח בודד:**

לחיצה על כפתור המחיקה ליד מפתח ספציפי.

**מחיקת תבנית:**

הזנת תבנית בשדה החיפוש ולחיצה על "מחק תבנית".

.. warning::
   לא ניתן למחוק ``*`` או ``**`` דרך תבנית - יש להשתמש ב-Clear All.

**Clear All (ניקוי מלא):**

מחיקת כל המפתחות ב-Redis. פעולה זו דורשת:

1. לחיצה על כפתור "Clear All"
2. אישור ב-Modal
3. שליחת ``confirm: true`` ב-API

אבטחה ובטיחות
--------------

הגנת הרשאות
^^^^^^^^^^^

- הדף והפעולות דורשים הרשאת **Admin**
- משתמשים רגילים מקבלים **403 Forbidden**
- בדיקת ההרשאות מתבצעת בצד השרת

הסתרת מידע רגיש (Masking)
^^^^^^^^^^^^^^^^^^^^^^^^^

מפתחות שמכילים את אחת מהתבניות הבאות **לא יציגו את הערך שלהם**:

- ``session:``
- ``token:``
- ``auth:``
- ``secret:``
- ``password:``
- ``credential:``
- ``api_key:``

במקום הערך יוצג: ``[SENSITIVE - HIDDEN]``

.. code-block:: text

   session:abc123    →  [SENSITIVE - HIDDEN]
   user:settings     →  {"theme": "dark", ...}

שימוש ב-SCAN במקום KEYS
^^^^^^^^^^^^^^^^^^^^^^^

כל פעולות החיפוש והמחיקה משתמשות בפקודת **SCAN** של Redis.
זה מבטיח:

- **לא חוסם** את Redis גם עם מיליוני מפתחות
- פעולה מבוקרת עם ``count=100`` בכל איטרציה
- הגנה על ביצועי המערכת

תקציב זמן למחיקות
^^^^^^^^^^^^^^^^^^

פעולות מחיקה מוגבלות בזמן כדי למנוע תקיעה:

- **מחיקת תבנית**: מוגבל ל-``CACHE_DELETE_PATTERN_BUDGET_SECONDS`` (ברירת מחדל: 5 שניות)
- **Clear All**: מוגבל ל-``CACHE_CLEAR_BUDGET_SECONDS`` (ברירת מחדל: 5 שניות)

API Endpoints
-------------

הממשק כולל את ה-APIs הבאים:

.. list-table::
   :header-rows: 1
   :widths: 15 35 50

   * - Method
     - Endpoint
     - תיאור
   * - ``GET``
     - ``/admin/cache-inspector``
     - דף ה-Inspector (HTML)
   * - ``POST``
     - ``/admin/cache-inspector/delete``
     - מחיקת מפתח/תבנית
   * - ``POST``
     - ``/admin/cache-inspector/clear-all``
     - ניקוי כל ה-cache
   * - ``GET``
     - ``/admin/cache-inspector/key/<key>``
     - פרטים מלאים על מפתח
   * - ``GET``
     - ``/api/cache/stats``
     - סטטיסטיקות (ציבורי למוניטורינג)

דוגמאות API
^^^^^^^^^^^

**מחיקת מפתח בודד:**

.. code-block:: bash

   curl -X POST /admin/cache-inspector/delete \
     -H "Content-Type: application/json" \
     -d '{"key": "user:123:settings"}'

**מחיקת תבנית:**

.. code-block:: bash

   curl -X POST /admin/cache-inspector/delete \
     -H "Content-Type: application/json" \
     -d '{"pattern": "temp:*"}'

**ניקוי מלא:**

.. code-block:: bash

   curl -X POST /admin/cache-inspector/clear-all \
     -H "Content-Type: application/json" \
     -d '{"confirm": true}'

**סטטיסטיקות:**

.. code-block:: bash

   curl /api/cache/stats

תקלות נפוצות
-------------

Redis מושבת
^^^^^^^^^^^

אם Redis לא זמין או לא מוגדר:

- הדף מציג ``N/A`` בכל השדות
- מוצגת הודעת אזהרה: ``Redis is disabled``
- פעולות מחיקה לא זמינות

**פתרון**: ודאו ש-``REDIS_URL`` מוגדר ו-``CACHE_ENABLED=true``

אין הרשאות
^^^^^^^^^^

אם מקבלים שגיאת 403:

- ודאו שאתם מחוברים למערכת
- ודאו שה-User ID שלכם ברשימת ``ADMIN_USER_IDS``

**פתרון**: הוסיפו את ה-Telegram User ID שלכם למשתנה ``ADMIN_USER_IDS``

חיפוש איטי
^^^^^^^^^^

אם החיפוש לוקח זמן רב:

- הקטינו את מגבלת התוצאות (limit)
- השתמשו בתבנית ספציפית יותר (למשל ``user:123:*`` במקום ``*``)

משתני סביבה רלוונטיים
---------------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - משתנה
     - תיאור
   * - ``REDIS_URL``
     - כתובת החיבור ל-Redis
   * - ``CACHE_ENABLED``
     - הפעלת cache (``true``/``false``)
   * - ``CACHE_CLEAR_BUDGET_SECONDS``
     - תקציב זמן לניקוי cache (ברירת מחדל: 5)
   * - ``CACHE_DELETE_PATTERN_BUDGET_SECONDS``
     - תקציב זמן למחיקת תבנית (ברירת מחדל: 5)
   * - ``ADMIN_USER_IDS``
     - רשימת User IDs עם הרשאות אדמין

ראו גם
------

- :doc:`/webapp/caching` – מדריך ל-HTTP Caching
- :doc:`/webapp/advanced-caching` – אסטרטגיות cache מתקדמות
- :doc:`/environment-variables` – רשימת משתני סביבה מלאה
- :doc:`/observability/background-jobs-monitor` – מוניטור Jobs ברקע
