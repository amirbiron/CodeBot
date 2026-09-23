Bulk actions (בחירה מרובה)
============================
:summary: דף זה מתאר את יכולות הבחירה המרובה והפעולות הקבוצתיות בממשק הווב.

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

- **המזהים מזהים גרסה, והסימון הוא של קובץ** — בדיוק כמו במחיקה המרובה שלמטה. השרת מתרגם כל מזהה לשם הקובץ שלו ומסמן את **כל** הגרסאות הפעילות שלו, עם אותו ``favorited_at``. קודם לכן הסימון סינן לפי המזהה עצמו ונגע בגרסה אחת.
- ``updated`` נספר ב\ **קבצים** — זה מה שהממשק מציג ("N קבצים"). שני מזהים של אותו קובץ נספרים פעם אחת, וקובץ שכל גרסאותיו בסל אינו נספר ואינו מסומן.
- המימוש המשותף לשני הראוטים: ``_bulk_set_favorite`` ב-``webapp/app.py``.

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

- מסיר את הסימון מ\ **כל** הגרסאות הפעילות של כל קובץ. רשימת המועדפים מכניסה קובץ אם **איזושהי** גרסה פעילה שלו מסומנת, ולכן הסרה מגרסה אחת בלבד השאירה את הקובץ ברשימה.
- ``updated`` נספר בקבצים, כמו ב-``bulk-favorite``.

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
     "ttl_days": 30
   }

- ``ttl_days`` אופציונלי. אם לא יסופק, השרת ישתמש בברירת המחדל מ-ENV ``RECYCLE_TTL_DAYS`` (ברירת מחדל ``30``).
- **המזהים מזהים גרסה, והמחיקה היא של קובץ.** עמוד הקבצים מקבץ את הגרסאות לפי שם ומוסר את ה-``_id`` של הגרסה האחרונה בלבד, ולכן השרת מתרגם כל מזהה לשם הקובץ שלו ומוריד לסל את **כל** גרסאותיו. קודם לכן המחיקה סיננה לפי המזהה עצמו, ולכן הורידה גרסה אחת והקובץ חזר לרשימה ברענון.

תגובה (200)::

   {
       "success": true,
       "deleted": 2,
       "versions": 7,
       "skipped_already_deleted": 0,
       "requested": 2,
       "message": "הקבצים הועברו לסל המחזור ל-30 ימים"
   }

- ``deleted`` נספר ב\ **קבצים** — זה מה שהממשק מציג למשתמש. ``versions`` הוא מספר מסמכי הגרסה שהושפעו, וקובץ אחד בן שבע גרסאות הוא ``deleted: 1, versions: 7``.
- ``skipped_already_deleted`` הוא מספר הקבצים שכל גרסאותיהם כבר היו בסל.

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

בהוספה ובהסרה ממועדפים יש שלוש תשובות נוספות:

- 400 ``Invalid request body`` — הגוף אינו אובייקט JSON. ו-400 ``Invalid file id`` — מזהה שאינו מחרוזת, או שאינו ``ObjectId`` תקין.
- 404 ``Some files not found`` — גם כשאחד המזהים שייך למשתמש אחר. לא מסומן אף קובץ.
- 409 ``Files changed, refresh and retry`` — הקבצים נמחקו בין התרגום לשם לבין הכתיבה, והכתיבה לא נגעה באף מסמך.

הערות למפתחים
--------------

- מגבלת 100 קבצים לפעולה נאכפת בשרת.
- מחיקה רכה: שדות ``is_active=False``, ``deleted_at``, ``deleted_expires_at``.
- ברירת מחדל ל-TTL: ``RECYCLE_TTL_DAYS`` (ENV, ברירת מחדל ``30``) — **אותו ערך לכל מסלולי המחיקה**, בבוט ובווב. ניתן לדרוס בבקשה באמצעות ``ttl_days``.
- השאילתה עצמה מוגדרת פעם אחת ב-``file_deletion.py`` שבשורש הריפו, ומשמשת גם את הראוטים של הווב וגם את שכבת ה-DB של הבוט. הוובאפ מריץ אותה על חיבור מונגו משלו, ולכן היא מקבלת את ה-collection כפרמטר במקום להחזיק חיבור.
