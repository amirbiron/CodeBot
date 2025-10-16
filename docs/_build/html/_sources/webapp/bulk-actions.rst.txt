Bulk actions (בחירה מרובה)
============================

דף זה מתאר את יכולות הבחירה המרובה והפעולות הקבוצתיות בממשק הווב.

סקירה
-----
- בחירה מרובה בקבצים מתוך עמוד ``/files`` (צ'קבוקסים על כל כרטיס).
- קיצורי דרך: ``Shift`` לבחירת טווח, ``Ctrl/Cmd + A`` לבחירת הכל, ``Escape`` לניקוי בחירה.
- מגבלת בטיחות: עד 100 קבצים לפעולה.
- אבטחה: כל פעולה פועלת רק על קבצים של המשתמש הנוכחי לפי ``user_id``.

.. note::
   "מחיקה רכה" (Soft delete) מעבירה קבצים לסל המחזור עם תוקף שחזור (TTL). "מחיקה סופית" (Hard delete) אינה זמינה עדיין ותתווסף בעתיד.

Endpoints
---------

``POST /api/files/bulk-favorite``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

בקשה::

   POST /api/files/bulk-favorite
   Content-Type: application/json

   {
     "file_ids": ["6540f2...a7", "6540f2...b8"]
   }

תגובה (200)::

   {
       "success": true,
       "updated": 2
   }

``POST /api/files/bulk-unfavorite``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

בקשה::

   POST /api/files/bulk-unfavorite
   Content-Type: application/json

   {
     "file_ids": ["6540f2...a7", "6540f2...b8"]
   }

תגובה (200)::

   {
       "success": true,
       "updated": 2
   }

``POST /api/files/bulk-tag``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

בקשה::

   POST /api/files/bulk-tag
   Content-Type: application/json

   {
     "file_ids": ["6540f2...a7","6540f2...b8"],
     "tags": ["important", "utils"]
   }

תגובה (200)::

   {
       "success": true,
       "updated": 2
   }

``POST /api/files/create-zip``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

בקשה::

   POST /api/files/create-zip
   Content-Type: application/json

   {
     "file_ids": ["6540f2...a7","6540f2...b8"]
   }

תגובה: קובץ ``application/zip`` להורדה ישירה.

``POST /api/files/bulk-delete`` (Soft Delete)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

בקשה::

   POST /api/files/bulk-delete
   Content-Type: application/json

   {
     "file_ids": ["6540f2...a7","6540f2...b8"],
     "ttl_days": 7
   }

- ``ttl_days`` אופציונלי. אם לא יסופק, השרת ישתמש בברירת המחדל מ-ENV ``RECYCLE_TTL_DAYS``; אם אינה מוגדרת, ערך ברירת המחדל הוא ``7``.

תגובה (200)::

   {
       "success": true,
       "deleted": 2,
       "message": "הקבצים הועברו לסל המחזור ל-7 ימים"
   }

``POST /api/files/create-share-link``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

בקשה::

   POST /api/files/create-share-link
   Content-Type: application/json

   {
     "file_ids": ["6540f2...a7","6540f2...b8"]
   }

תגובה (200)::

   {
       "success": true,
       "share_url": "https://.../shared/<token>",
       "expires_at": "2025-10-15T12:00:00Z",
       "token": "<token>"
   }

שגיאות נפוצות
--------------

- 400: ``{"success": false, "error": "No files selected"}``
- 404: ``{"success": false, "error": "Some files not found"}``

הערות למפתחים
--------------

- מגבלת 100 קבצים לפעולה נאכפת בשרת.
- מחיקה רכה: שדות ``is_active=False``, ``deleted_at``, ``deleted_expires_at``.
- ברירת מחדל ל-TTL: ``RECYCLE_TTL_DAYS`` (ENV) עם fallback ל-``7``. ניתן לדרוס בבקשה באמצעות ``ttl_days``.
