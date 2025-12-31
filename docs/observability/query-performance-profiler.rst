Query Performance Profiler
==========================

.. contents:: תוכן עניינים
   :local:
   :depth: 2

Overview
--------

**Query Performance Profiler** הוא כלי ניטור לשאילתות MongoDB איטיות, המספק:

1. **זיהוי שאילתות איטיות** – מעקב בזמן אמת אחרי שאילתות שחורגות מסף זמן מוגדר
2. **ניתוח Explain Plans** – הצגה ויזואלית של תוכנית הביצוע של MongoDB (כולל Aggregation Pipelines)
3. **המלצות אופטימיזציה** – הצעות אוטומטיות לשיפור ביצועים
4. **היסטוריית שאילתות** – שמירה וניתוח של דפוסי שאילתות לאורך זמן

קהל יעד
~~~~~~~~

הפרופיילר מיועד ל-**Admin** בלבד. גישה אליו דורשת:

- הרשאת Admin ב-WebApp, **או**
- טוקן ייעודי (``X-Profiler-Token``)

מה הכלי לא עושה
~~~~~~~~~~~~~~~~~

- לא מחליף את MongoDB Profiler המובנה ברמת ה-DB
- לא מספק אופטימיזציה אוטומטית (רק המלצות)
- לא מיועד ל-Production Debugging בזמן אמת של שאילתות בודדות

ממשק משתמש (WebApp)
--------------------

הנתיב
~~~~~~

``GET /admin/profiler``

איך להגיע
~~~~~~~~~~

1. דרך Settings → כלי אדמין → Query Profiler
2. או ישירות לכתובת ``/admin/profiler``

מה רואים בדשבורד
~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - אזור
     - תיאור
   * - Summary
     - סיכום כללי: מספר שאילתות איטיות, זמן ממוצע, collections מושפעים
   * - Slow Queries Table
     - טבלה עם שאילתות איטיות, כולל סינון לפי collection
   * - ניתוח Query/Pipeline
     - טופס להזנת שאילתה לניתוח מיידי
   * - Explain Visualization
     - ויזואליזציה של שלבי הביצוע (COLLSCAN, IXSCAN, FETCH וכו')
   * - Recommendations
     - המלצות אופטימיזציה לפי חומרה (קריטי/אזהרה/מידע)

.. note::
   ברירת המחדל של ה-verbosity היא ``queryPlanner`` (בטוח) – לא מריץ את השאילתה בפועל.

API Reference
-------------

Authentication
~~~~~~~~~~~~~~

אם ``PROFILER_AUTH_TOKEN`` מוגדר, יש לשלוח את הטוקן בכותרת:

.. code-block:: text

   X-Profiler-Token: <your-token>

אם הטוקן לא מוגדר, הגישה מתבססת על הרשאת Admin ב-WebApp Session.

Endpoints
~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 15 50 35

   * - Method
     - Endpoint
     - תיאור
   * - GET
     - ``/api/profiler/summary``
     - סיכום מצב הפרופיילר
   * - GET
     - ``/api/profiler/slow-queries``
     - רשימת שאילתות איטיות (עם סינון)
   * - POST
     - ``/api/profiler/explain``
     - הרצת Explain Plan על שאילתה/pipeline
   * - POST
     - ``/api/profiler/recommendations``
     - ניתוח והמלצות לשאילתה
   * - POST
     - ``/api/profiler/analyze``
     - Alias ל-recommendations
   * - GET
     - ``/api/profiler/collection/<name>/stats``
     - סטטיסטיקות collection (גודל, אינדקסים)

GET /api/profiler/summary
^^^^^^^^^^^^^^^^^^^^^^^^^^

מחזיר סיכום כללי:

.. code-block:: bash

   curl -H "X-Profiler-Token: $TOKEN" \
        https://your-app.com/api/profiler/summary

**Response:**

.. code-block:: json

   {
     "status": "success",
     "data": {
       "total_slow_queries": 42,
       "collections_affected": ["code_snippets", "users"],
       "avg_execution_time_ms": 350.5,
       "max_execution_time_ms": 2500.0,
       "unique_patterns": 15,
       "threshold_ms": 100
     }
   }

GET /api/profiler/slow-queries
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

**Query Parameters:**

.. list-table::
   :header-rows: 1

   * - Parameter
     - תיאור
     - ברירת מחדל
   * - ``limit``
     - מספר שאילתות להחזיר
     - ``50``
   * - ``collection``
     - סינון לפי collection
     - (הכל)
   * - ``min_time``
     - זמן ביצוע מינימלי (ms)
     - (הכל)
   * - ``hours``
     - שאילתות מהשעות האחרונות
     - (הכל)

**דוגמה:**

.. code-block:: bash

   curl -H "X-Profiler-Token: $TOKEN" \
        "https://your-app.com/api/profiler/slow-queries?limit=20&collection=code_snippets&hours=24"

POST /api/profiler/explain
^^^^^^^^^^^^^^^^^^^^^^^^^^^

מריץ Explain Plan על שאילתה או Aggregation Pipeline.

**Body (Query):**

.. code-block:: json

   {
     "collection": "code_snippets",
     "query": {"user_id": "123", "is_deleted": false},
     "verbosity": "queryPlanner"
   }

**Body (Pipeline):**

.. code-block:: json

   {
     "collection": "code_snippets",
     "pipeline": [
       {"$match": {"user_id": "123"}},
       {"$group": {"_id": "$language", "count": {"$sum": 1}}}
     ],
     "verbosity": "queryPlanner"
   }

**דוגמה:**

.. code-block:: bash

   curl -X POST \
        -H "X-Profiler-Token: $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"collection":"code_snippets","query":{"user_id":"<value>"}}' \
        https://your-app.com/api/profiler/explain

POST /api/profiler/recommendations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

מחזיר Explain Plan + המלצות אופטימיזציה:

.. code-block:: bash

   curl -X POST \
        -H "X-Profiler-Token: $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"collection":"code_snippets","query":{"user_id":"<value>"}}' \
        https://your-app.com/api/profiler/recommendations

GET /api/profiler/collection/<name>/stats
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

מחזיר סטטיסטיקות collection:

.. code-block:: bash

   curl -H "X-Profiler-Token: $TOKEN" \
        https://your-app.com/api/profiler/collection/code_snippets/stats

**Response:**

.. code-block:: json

   {
     "status": "success",
     "data": {
       "size_bytes": 1048576,
       "count": 5000,
       "avg_obj_size": 210,
       "index_count": 3,
       "indexes": ["_id_", "user_id_1", "user_id_1_is_deleted_1"],
       "total_index_size": 524288
     }
   }

Security
--------

Authentication
~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - שכבה
     - משתנה/מנגנון
     - תיאור
   * - Token
     - ``PROFILER_AUTH_TOKEN``
     - טוקן נשלח ב-Header ``X-Profiler-Token``
   * - IP Allowlist
     - ``PROFILER_ALLOWED_IPS``
     - רשימת IPs מורשים (CSV)
   * - Rate Limit
     - ``PROFILER_RATE_LIMIT``
     - מגבלת בקשות לדקה (ברירת מחדל: 60)
   * - Admin Session
     - WebApp
     - אם אין Token, נדרשת הרשאת Admin

הגדרת Token
~~~~~~~~~~~~

.. code-block:: bash

   # .env
   PROFILER_AUTH_TOKEN=my-secure-profiler-token
   PROFILER_ALLOWED_IPS=127.0.0.1,10.0.0.1

אזהרת Observer Effect
-----------------------

.. warning::
   **Observer Effect** – הרצת ``explain("executionStats")`` או ``explain("allPlansExecution")`` **מריצה את השאילתה בפועל!**

   **הסיכונים:**

   - אם השאילתה איטית כי היא מעמיסה על ה-CPU, הרצת ה-Explain תכפיל את העומס
   - אם השאילתה נועלת מסמכים (write operations), זה עלול להחמיר את המצב
   - ב-Production עמוס, הרצה אוטומטית של explain יכולה ליצור "אפקט שלג"

**המלצות:**

1. **השתמש ב-``queryPlanner`` כברירת מחדל** – לא מריץ את השאילתה, רק מציג את התוכנית
2. **הרץ ``executionStats`` רק לפי דרישה** – כפי שממומש בכפתור "נתח" בדשבורד
3. **אל תריץ explain אוטומטית לכל שאילתה איטית** – זה יכפיל את הבעיה
4. **שקול הרצת explain בשעות שפל** או על replica secondary

.. list-table:: רמות Verbosity
   :header-rows: 1

   * - רמה
     - תיאור
     - מתי להשתמש
   * - ``queryPlanner``
     - תוכנית בלבד, ללא הרצה
     - לבדיקת אינדקסים (בטוח)
   * - ``executionStats``
     - כולל סטטיסטיקות ביצוע
     - ניתוח ביצועים מלא
   * - ``allPlansExecution``
     - כל התוכניות שנבחנו
     - Debug מתקדם בלבד

Privacy / PII
-------------

.. important::
   **נרמול שאילתות מונע דליפת מידע אישי (PII)**

הפונקציה ``_normalize_query_shape`` מחליפה את כל הערכים בפלייסהולדרים:

- ערכים פשוטים → ``<value>``
- מערכים → ``<N items>``
- null → ``<null>``

**דוגמה:**

.. code-block:: python

   # Query מקורי (לא מוצג)
   {"email": "john@example.com", "status": {"$in": ["active", "pending"]}}

   # Query מנורמל (מה שמוצג בדשבורד)
   {"email": "<value>", "status": {"$in": ["<2 items>"]}}

.. warning::
   **אל תתעד או תציג דוגמאות עם נתוני אמת/PII בדוחות או בלוגים.**

Persistence
-----------

Collection
~~~~~~~~~~

שם: ``slow_queries_log``

TTL Index
~~~~~~~~~

מחיקה אוטומטית אחרי **7 ימים**:

.. code-block:: javascript

   db.slow_queries_log.createIndex(
     {"timestamp": 1},
     {expireAfterSeconds: 604800, name: "ttl_cleanup"}
   )

אינדקסים נוספים
~~~~~~~~~~~~~~~~

.. code-block:: javascript

   // חיפוש מהיר לפי collection + זמן
   db.slow_queries_log.createIndex(
     {"collection": 1, "timestamp": -1},
     {name: "collection_timestamp"}
   )

   // חיפוש לפי דפוס שאילתה
   db.slow_queries_log.createIndex(
     {"query_id": 1},
     {name: "query_pattern"}
   )

Metrics (Prometheus)
--------------------

מטריקות זמינות כאשר ``PROFILER_METRICS_ENABLED=true``:

.. list-table::
   :header-rows: 1

   * - Metric
     - Type
     - תיאור
   * - ``mongodb_slow_queries_total``
     - Counter
     - מספר שאילתות איטיות לפי collection ו-operation
   * - ``mongodb_query_duration_seconds``
     - Histogram
     - התפלגות זמני שאילתות
   * - ``mongodb_collscan_detected_total``
     - Counter
     - מספר COLLSCAN שזוהו
   * - ``query_profiler_buffer_size``
     - Gauge
     - מספר שאילתות בבאפר הזיכרון

Environment Variables
---------------------

ראו את הטבלה המלאה ב-:doc:`../environment-variables`.

.. list-table::
   :header-rows: 1
   :widths: 30 50 20

   * - משתנה
     - תיאור
     - ברירת מחדל
   * - ``PROFILER_ENABLED``
     - הפעלת Query Performance Profiler
     - ``true``
   * - ``PROFILER_SLOW_THRESHOLD_MS``
     - סף זמן (ms) להגדרת "שאילתה איטית"
     - ``100``
   * - ``PROFILER_MAX_BUFFER_SIZE``
     - מספר שאילתות בזיכרון
     - ``1000``
   * - ``PROFILER_AUTH_TOKEN``
     - טוקן גישה (Header ``X-Profiler-Token``)
     - (ריק)
   * - ``PROFILER_ALLOWED_IPS``
     - Allowlist של IPs (CSV)
     - (ריק)
   * - ``PROFILER_RATE_LIMIT``
     - מגבלת בקשות לדקה
     - ``60``
   * - ``PROFILER_METRICS_ENABLED``
     - הפעלת מטריקות Prometheus
     - ``true``

המלצות אופטימיזציה נפוצות
--------------------------

.. list-table::
   :header-rows: 1

   * - בעיה
     - סימפטום
     - המלצה
   * - 🔴 COLLSCAN
     - ``stage: "COLLSCAN"``
     - צור אינדקס על שדות הסינון
   * - 🟠 Sort בזיכרון
     - ``stage: "SORT"``
     - הוסף שדה מיון לאינדקס
   * - 🟡 יחס יעילות נמוך
     - ``docsExamined >> nReturned``
     - שפר selectivity של האינדקס
   * - 🔴 $lookup ללא אינדקס
     - ``nestedLoopJoin``
     - צור אינדקס על ה-foreign field
   * - 🟠 $sort משתמש בדיסק
     - ``usedDisk: true``
     - הוסף $match לפני ה-$sort

קישורים נוספים
---------------

- :doc:`../environment-variables` – טבלת משתני סביבה מלאה
- :doc:`observability_dashboard` – דשבורד Observability
- :doc:`background-jobs-monitor` – מוניטור Jobs
- `MongoDB Explain Documentation <https://www.mongodb.com/docs/manual/reference/command/explain/>`_
- `MongoDB Index Strategies <https://www.mongodb.com/docs/manual/applications/indexes/>`_
