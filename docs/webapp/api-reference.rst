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
     - רשימת קבצים (סינון וחיפוש)
     - ✅
     - Query: ``?search=...&lang=...``
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

קישורים
-------

- :doc:`overview`
- :doc:`/architecture`
