WebApp API Reference
====================

Endpoints
---------

.. list-table:: Endpoints
   :header-rows: 1

   * - Endpoint
     - Method
     - תיאור
     - דורש אימות
     - Request Body
     - Response
   * - ``/``
     - GET
     - דף הבית
     - ❌
     - -
     - HTML
   * - ``/login``
     - GET
     - דף התחברות (Telegram Widget)
     - ❌
     - -
     - HTML
   * - ``/auth/telegram``
     - POST
     - אימות Telegram (hash verify)
     - ❌
     - ``{id, first_name, ...}``
     - ``{"success": true}``
   * - ``/logout``
     - GET
     - התנתקות
     - ✅
     - -
     - Redirect
   * - ``/dashboard``
     - GET
     - דשבורד
     - ✅
     - -
     - HTML
   * - ``/files``
     - GET
     - רשימת קבצים (סינון, חיפוש ודפדוף)
     - ✅
     - Query: ``?q=...&lang=...&category=...&sort=created_at_desc&cursor=...&repo=...``
     - HTML
   * - ``/file/<id>``
     - GET
     - צפייה בקובץ
     - ✅
     - -
     - HTML
   * - ``/download/<id>``
     - GET
     - הורדת קובץ
     - ✅
     - -
     - File Download
   * - ``/html/<id>``
     - GET
     - תצוגת HTML בטוחה
     - ✅
     - -
     - HTML (iframe)
   * - ``/md/<id>``
     - GET
     - תצוגת Markdown
     - ✅
     - -
     - HTML (rendered)
   * - ``/api/sticky-notes/reminders/summary``
     - GET
     - סיכום מינימלי לבועה הקבועה (האם יש פתקים ממתינים + מונה)
     - ✅
     - -
     - ``{"ok": true, "has_due": true, "count_due": 3, "next": {"note_id": "...", "file_id": "...", "remind_at": "..."}}``
   * - ``/api/sticky-notes/reminders/list``
     - GET
     - רשימת פתקים ממתינים עם תצוגה מקדימה (6 מילים) וקישור לעוגן
     - ✅
     - Query: ``?limit=20``
     - ``{"ok": true, "count": 3, "items": [{"note_id": "...", "file_id": "...", "preview": "...", "anchor_id": "h2-intro"}]}``
   * - ``/api/sticky-notes/reminders/ack``
     - POST
     - סימון תזכורת כ־acknowledged (המשתמש פתח)
     - ✅
     - ``{"note_id": "..."}``
     - ``{"ok": true}``
   * - ``/api/sticky-notes/note/<note_id>/reminder``
     - POST
     - קביעת תזכורת לפתק (קיצורי זמן/תאריך שעה)
     - ✅
     - ``{"preset": "1h"|"3h"|"24h"|"1w"|"today-21"|"tomorrow-09", "tz": "Asia/Jerusalem"}`` או ``{"at": "2025-11-15T09:00", "tz": "Asia/Jerusalem"}``
     - ``{"ok": true, "remind_at": "2025-11-15T07:00:00+00:00"}``
   * - ``/api/sticky-notes/note/<note_id>/snooze``
     - POST
     - דחיית תזכורת ב‑X דקות
     - ✅
     - ``{"minutes": 60}``
     - ``{"ok": true, "remind_at": "..."}``
   * - ``/api/welcome/ack``
     - POST
     - סימון הדגל ``has_seen_welcome_modal`` והסתרת מודאל ה־Welcome לצמיתות
     - ✅
     - -
     - ``{"ok": true}``
   * - ``/api/shared/save``
     - POST
     - שמירת שיתוף פנימי כקובץ Markdown תחת חשבון המשתמש
     - ✅
     - ``{"share_id": "string", "file_name": "optional override"}``
     - ``{"ok": true, "file_id": "...", "file_name": "...", "version": 1}``
   * - ``/api/stats``
     - GET
     - סטטיסטיקות
     - ✅
     - -
     - JSON

Authentication Flow
-------------------

.. mermaid::

   sequenceDiagram
       participant U as User
       participant W as WebApp
       participant T as Telegram
       U->>W: GET /login
       W-->>U: Login page with Telegram Widget
       U->>T: Click "Login"
       T->>W: POST /auth/telegram (user data + hash)
       W->>W: Verify hash with BOT_TOKEN
       W-->>U: Set session cookie
       U->>W: GET /dashboard
       W-->>U: Dashboard (authenticated)

Response Schema Example
-----------------------

.. code-block:: json

   {
     "total_files": 156,
     "languages": {
       "python": 45,
       "javascript": 32,
       "java": 20
     },
     "recent_files": [
       {
         "id": "507f1f77bcf86cd799439011",
         "file_name": "example.py",
         "language": "python",
         "created_at": "2025-10-10T10:30:00Z"
       }
     ]
   }

Errors
------

.. code-block:: json

   {"error": "Authentication required", "redirect": "/login"}

.. code-block:: json

   {"error": "File not found", "file_id": "507f1f77bcf86cd799439011"}

שגיאות נפוצות – ``POST /api/shared/save``
-----------------------------------------

.. code-block:: json

   {"error": "Missing share_id"}

.. code-block:: json

   {"error": "Share not found", "share_id": "abcd1234"}

.. code-block:: json

   {"error": "Invalid file name"}

קישורים
-------

- :doc:`overview`
- :doc:`/architecture`

מסנן ושדות קלט ל-``/files``
----------------------------

טבלת פרמטרים
^^^^^^^^^^^^^

.. list-table:: ``/files`` parameters
   :header-rows: 1

   * - פרמטר
     - סוג
     - ברירת מחדל
     - תיאור
   * - ``q``
     - string
     - -
     - מחרוזת חיפוש (טקסט חופשי)
   * - ``lang``
     - string
     - -
     - סינון לפי שפת תכנות (``python``, ``js`` וכו')
   * - ``category``
     - string
     - -
     - קטגוריית קובץ/תיוג לוגי
   * - ``sort``
     - string
     - ``created_at_desc``
     - סדר מיון (``created_at_desc``/``created_at_asc``)
   * - ``cursor``
     - string
     - -
     - קורסור לדפדוף מבוסס זמן+``_id`` (ראו :doc:`/database/cursor-pagination`)
   * - ``repo``
     - string
     - -
     - סינון לפי ריפו/מקור אם רלוונטי

דוגמאות בקשה
^^^^^^^^^^^^^

.. code-block:: sh

   # חיפוש בסיסי
   curl -isS "https://<host>/files?q=pagination&lang=python"

   # דף שני עם קורסור
   curl -isS "https://<host>/files?cursor=<TOKEN>"

דוגמאות תגובה
^^^^^^^^^^^^^^

.. code-block:: html

   <!-- HTML מקוצר לצורך דוגמה -->
   <div class="files-list">
     <div class="file">
       <a href="/file/507f1f77bcf86cd799439011">example.py</a>
       <span class="lang">python</span>
       <time datetime="2025-10-10T10:30:00Z">2025-10-10</time>
     </div>
   </div>
