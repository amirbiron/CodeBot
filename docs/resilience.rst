Resilience לשירותים חיצוניים
=============================
:summary: שכבת Retry ו-Circuit Breaker לקריאות חוץ. היא חלה על קריאות שעוברות דרך http_sync.py ו-http_async.py; שירותים שקוראים ישירות ל-requests, httpx או aiohttp אינם מכוסים עדיין.

למה שכבה מרוכזת?
-----------------
מודול ``resilience.py`` מרכז מדיניות אחת של Retry + Circuit Breaker לקריאות חוץ.
התוצאה: פחות רעשים זמניים, ניטור ברור יותר, ויכולת להבין בזמן אמת מתי שירות חוץ "שורף" אותנו.

.. note::

   הכיסוי אינו מלא. המדיניות חלה על קריאות שעוברות דרך ``http_sync.py`` ו-``http_async.py`` בלבד.
   שירותים שקוראים ישירות ל-``requests``, ל-``httpx`` או ל-``aiohttp`` אינם עוברים דרכה —
   למשל ``services/embedding_service.py`` (``httpx.AsyncClient``) ו-``services/observability_dashboard.py``
   (``requests.post``). ``services/rules_evaluator.py`` דווקא **מעדיף** את המסלול המכוסה
   (``from http_sync import request``) ונופל ל-``requests.post`` רק אם הייבוא נכשל.
   המיגרציה של השאר עדיין פתוחה.

איך זה עובד?
------------
- RetryPolicy: כמה ניסיונות חוזרים, ו‑Backoff אקספוננציאלי עם ``jitter`` למניעת "עדר".
- CircuitBreaker: פתיחה/half-open/סגירה לפי כשלים רצופים וחלונות הצלחה.
- כל הקביעות נשלטות דרך ENV, ללא שינוי קוד.

דיאגרמת טיפול בשגיאות
---------------------

התרשים הבא מציג את הזרימה המלאה של טיפול בשגיאות ושחזור:

.. mermaid::

   graph TD
       E[Error Occurs] --> ET{Error Type}

       ET -->|Database| DBE[DB Error Handler]
       ET -->|API| APE[API Error Handler]
       ET -->|Timeout| TE[Timeout Handler]
       ET -->|Unknown| UE[Generic Handler]

       DBE --> RT1{Retry?}
       RT1 -->|Yes| RTC1[Retry with Backoff]
       RT1 -->|No| FO1[Failover to Cache]

       APE --> RT2{Rate Limited?}
       RT2 -->|Yes| BK[Activate Backoff]
       RT2 -->|No| RTC2[Retry Request]

       TE --> CX[Cancel Operation]
       CX --> NF[Notify User]

       UE --> LOG[Log Error]
       LOG --> ALT[Alert Admin]

       RTC1 --> SR{Success?}
       RTC2 --> SR
       FO1 --> SR
       BK --> SR

       SR -->|Yes| RES[Return Result]
       SR -->|No| ERR[Return Error]

**סוגי שגיאות והטיפול:**

- **Database Errors**: ניסיון חוזר עם Backoff, או Failover ל-Cache
- **API Errors**: בדיקת Rate Limit, הפעלת Backoff או Retry
- **Timeout Errors**: ביטול הפעולה והודעה למשתמש
- **Unknown Errors**: לוגים + התראה לאדמין

**עקרונות מרכזיים:**

1. זיהוי סוג השגיאה לטיפול מותאם
2. Retry עם Backoff אקספוננציאלי למניעת עומס
3. Failover אוטומטי לשירותי גיבוי (Cache)
4. התראות לאדמין בשגיאות קריטיות

קונפיגורציה חשובה (ENV)
------------------------

.. list-table:: ENV
   :header-rows: 1

   * - משתנה
     - ברירת מחדל
     - מה הוא עושה
   * - ``HTTP_RESILIENCE_MAX_ATTEMPTS``
     - ``3``
     - ניסיונות חזרה לפני שמפסיקים
   * - ``HTTP_RESILIENCE_BACKOFF_BASE``
     - ``0.25``
     - זמן ההמתנה הראשון (שניות) לפני כניסה לאקספוננט
   * - ``HTTP_RESILIENCE_BACKOFF_MAX``
     - ``8.0``
     - תקרת ההמתנה בין ניסיונות
   * - ``HTTP_RESILIENCE_JITTER``
     - ``0.5``
     - רעש אקראי (שניות) לכל המתנה
   * - ``CIRCUIT_BREAKER_FAILURE_THRESHOLD``
     - ``5``
     - כמה כשלונות לפני פתיחת Circuit
   * - ``CIRCUIT_BREAKER_RECOVERY_SECONDS``
     - ``30``
     - כמה זמן ממתינים עד ניסיון half-open
   * - ``CIRCUIT_BREAKER_HALF_OPEN_SUCCESS``
     - ``1``
     - כמה הצלחות רצופות נדרשות כדי לסגור Circuit
   * - ``CIRCUIT_BREAKER_SUCCESS_WINDOW``
     - ``20``
     - חלון לחישוב אחוזי הצלחה

טיפ
----
אם שירות חוץ מתחיל להחזיר 429, ניתן זמנית להגדיל ``CIRCUIT_BREAKER_RECOVERY_SECONDS`` כדי למנוע עומס חוזר.

שימוש בקוד
----------
כברירת מחדל, כל הקריאות דרך ``http_sync.request`` ו‑``http_async.request`` עובדות עם המדיניות הזו. ניתן להעביר
שמות שירות/נתיב לקבלת מטריקות נקיות.

.. code-block:: python

   from http_sync import request

   resp = request(
       "GET",
       "https://status.github.com/api",
       service="github",
       endpoint="status_api",
   )

ראו גם
------
- :doc:`/metrics`
- :doc:`/observability`
- :doc:`/api/http_sync`
- :doc:`/api/http_async`
