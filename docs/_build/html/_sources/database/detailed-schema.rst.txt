מבנה נתונים מפורט (Detailed Database Schema)
==============================================

סקירה כללית
------------

מסמך זה מתאר בפירוט את כל האוספים, השדות, האילוצים והאינדקסים במסד הנתונים.

אוסף: code_snippets
--------------------

**תיאור:** אחסון קטעי קוד של משתמשים

**שדות:**

.. list-table:: שדות code_snippets
   :header-rows: 1
   :widths: 15 15 20 50

   * - שדה
     - סוג
     - חובה
     - תיאור
   * - ``_id``
     - ObjectId
     - כן
     - מזהה ייחודי
   * - ``user_id``
     - int
     - כן
     - מזהה משתמש Telegram
   * - ``file_name``
     - string
     - כן
     - שם הקובץ (עד 255 תווים)
   * - ``code``
     - string
     - כן
     - תוכן הקוד
   * - ``programming_language``
     - string
     - כן
     - שפת התכנות (auto-detected)
   * - ``is_favorite``
     - bool
     - לא
     - האם הקובץ במועדפים (ברירת מחדל: false)
   * - ``favorited_at``
     - datetime
     - לא
     - תאריך הוספה למועדפים
   * - ``description``
     - string
     - לא
     - תיאור/הערה על הקובץ
   * - ``tags``
     - array[string]
     - לא
     - תגיות (ברירת מחדל: [])
   * - ``version``
     - int
     - לא
     - מספר גרסה (ברירת מחדל: 1)
   * - ``created_at``
     - datetime
     - לא
     - תאריך יצירה (auto-set)
   * - ``updated_at``
     - datetime
     - לא
     - תאריך עדכון אחרון (auto-set)
   * - ``is_active``
     - bool
     - לא
     - האם הקובץ פעיל (ברירת מחדל: true)
   * - ``deleted_at``
     - datetime
     - לא
     - תאריך מחיקה (soft delete)
   * - ``deleted_expires_at``
     - datetime
     - לא
     - תאריך תפוגה למחיקה סופית

**אילוצים:**
- ``user_id`` + ``file_name`` + ``version`` ייחודיים יחד
- ``file_name`` לא יכול להיות ריק
- ``code`` לא יכול להיות ריק
- ``tags`` חייב להיות array (אפילו ריק)

**אינדקסים:**

.. code-block:: javascript

   // אינדקס ראשי - חיפוש לפי משתמש ותאריך
   db.code_snippets.createIndex(
       { "user_id": 1, "created_at": -1 },
       { name: "user_created_idx" }
   )
   
   // אינדקס שפה - סינון לפי שפת תכנות
   db.code_snippets.createIndex(
       { "programming_language": 1 },
       { name: "language_idx" }
   )
   
   // אינדקס Full-Text - חיפוש בתוכן
   db.code_snippets.createIndex(
       { "file_name": "text", "code": "text", "description": "text" },
       { name: "text_search_idx" }
   )
   
   // אינדקס תגיות - סינון לפי תגיות
   db.code_snippets.createIndex(
       { "tags": 1 },
       { name: "tags_idx" }
   )
   
   // אינדקס מחיקה - סינון קבצים פעילים
   db.code_snippets.createIndex(
       { "is_active": 1, "deleted_at": 1 },
       { name: "active_idx" }
   )
   
   // אינדקס מועדפים
   db.code_snippets.createIndex(
       { "user_id": 1, "is_favorite": 1, "favorited_at": -1 },
       { name: "favorites_idx" }
   )

אוסף: large_files
------------------

**תיאור:** אחסון קבצים גדולים (>4096 תווים)

**שדות:**

.. list-table:: שדות large_files
   :header-rows: 1
   :widths: 15 15 20 50

   * - שדה
     - סוג
     - חובה
     - תיאור
   * - ``_id``
     - ObjectId
     - כן
     - מזהה ייחודי
   * - ``user_id``
     - int
     - כן
     - מזהה משתמש Telegram
   * - ``file_name``
     - string
     - כן
     - שם הקובץ
   * - ``content``
     - string
     - כן
     - תוכן הקובץ
   * - ``programming_language``
     - string
     - כן
     - שפת התכנות
   * - ``file_size``
     - int
     - כן
     - גודל הקובץ בבייטים (auto-calculated)
   * - ``lines_count``
     - int
     - כן
     - מספר שורות (auto-calculated)
   * - ``description``
     - string
     - לא
     - תיאור
   * - ``tags``
     - array[string]
     - לא
     - תגיות
   * - ``created_at``
     - datetime
     - לא
     - תאריך יצירה
   * - ``updated_at``
     - datetime
     - לא
     - תאריך עדכון
   * - ``is_active``
     - bool
     - לא
     - האם פעיל
   * - ``deleted_at``
     - datetime
     - לא
     - תאריך מחיקה
   * - ``deleted_expires_at``
     - datetime
     - לא
     - תאריך תפוגה

**הבדלים מ-code_snippets:**
- אין ``version`` (גרסאות נשמרות ב-``file_versions``)
- אין ``is_favorite`` (מועדפים נשמרים ב-``favorites`` collection)
- ``file_size`` ו-``lines_count`` מחושבים אוטומטית

**אינדקסים:**

.. code-block:: javascript

   db.large_files.createIndex(
       { "user_id": 1, "created_at": -1 },
       { name: "user_created_idx" }
   )
   
   db.large_files.createIndex(
       { "programming_language": 1 },
       { name: "language_idx" }
   )
   
   db.large_files.createIndex(
       { "file_size": -1 },
       { name: "size_idx" }
   )

אוסף: users
------------

**תיאור:** פרופילי משתמשים

**שדות:**

.. list-table:: שדות users
   :header-rows: 1
   :widths: 15 15 20 50

   * - שדה
     - סוג
     - חובה
     - תיאור
   * - ``_id``
     - ObjectId
     - כן
     - מזהה ייחודי
   * - ``user_id``
     - int
     - כן
     - מזהה משתמש Telegram (unique)
   * - ``username``
     - string
     - לא
     - שם משתמש Telegram
   * - ``first_name``
     - string
     - לא
     - שם פרטי
   * - ``last_name``
     - string
     - לא
     - שם משפחה
   * - ``created_at``
     - datetime
     - לא
     - תאריך יצירת פרופיל
   * - ``last_active``
     - datetime
     - לא
     - פעילות אחרונה
   * - ``settings``
     - object
     - לא
     - הגדרות משתמש
   * - ``stats``
     - object
     - לא
     - סטטיסטיקות שימוש

**מבנה settings:**

.. code-block:: javascript

   {
     "language": "he",  // שפת ממשק
     "notifications": true,  // התראות
     "github_backoff_enabled": false,  // GitHub backoff
     "github_backoff_until": null  // תאריך סיום backoff
   }

**מבנה stats:**

.. code-block:: javascript

   {
     "total_files": 150,  // סה"כ קבצים
     "total_searches": 45,  // סה"כ חיפושים
     "total_backups": 5  // סה"כ גיבויים
   }

**אינדקסים:**

.. code-block:: javascript

   db.users.createIndex(
       { "user_id": 1 },
       { unique: true, name: "user_id_unique_idx" }
   )
   
   db.users.createIndex(
       { "username": 1 },
       { name: "username_idx" }
   )

אוסף: bookmarks
----------------

**תיאור:** סימניות משתמשים (WebApp)

**שדות:**

.. list-table:: שדות bookmarks
   :header-rows: 1
   :widths: 15 15 20 50

   * - שדה
     - סוג
     - חובה
     - תיאור
   * - ``_id``
     - ObjectId
     - כן
     - מזהה ייחודי
   * - ``user_id``
     - int
     - כן
     - מזהה משתמש
   * - ``file_id``
     - ObjectId
     - כן
     - מזהה קובץ
   * - ``line_number``
     - int
     - לא
     - מספר שורה (אם לא anchor)
   * - ``anchor_id``
     - string
     - לא
     - מזהה עוגן (Markdown/HTML)
   * - ``color``
     - string
     - לא
     - צבע סימנייה (yellow/red/green/blue/purple)
   * - ``annotation``
     - string
     - לא
     - הערה אישית
   * - ``created_at``
     - datetime
     - לא
     - תאריך יצירה

**אילוצים:**
- ``line_number`` או ``anchor_id`` חייב להיות מוגדר (לא שניהם)
- ``color`` חייב להיות אחד מהצבעים הנתמכים
- עד 50 סימניות לקובץ
- עד 500 סימניות למשתמש

**אינדקסים:**

.. code-block:: javascript

   db.bookmarks.createIndex(
       { "user_id": 1, "file_id": 1 },
       { name: "user_file_idx" }
   )
   
   db.bookmarks.createIndex(
       { "file_id": 1, "line_number": 1 },
       { name: "file_line_idx" }
   )

אוסף: collections
------------------

**תיאור:** אוספי קבצים (WebApp)

**שדות:**

.. list-table:: שדות collections
   :header-rows: 1
   :widths: 15 15 20 50

   * - שדה
     - סוג
     - חובה
     - תיאור
   * - ``_id``
     - ObjectId
     - כן
     - מזהה ייחודי
   * - ``user_id``
     - int
     - כן
     - מזהה משתמש
   * - ``name``
     - string
     - כן
     - שם האוסף
   * - ``description``
     - string
     - לא
     - תיאור
   * - ``icon``
     - string
     - לא
     - אייקון
   * - ``color``
     - string
     - לא
     - צבע
   * - ``is_favorite``
     - bool
     - לא
     - האם מועדף
   * - ``items``
     - array
     - לא
     - פריטי האוסף
   * - ``created_at``
     - datetime
     - לא
     - תאריך יצירה
   * - ``updated_at``
     - datetime
     - לא
     - תאריך עדכון

**מבנה items:**

.. code-block:: javascript

   [
     {
       "file_id": ObjectId("..."),
       "order": 0,  // סדר מותאם
       "note": "הערה על הפריט"
     }
   ]

**אינדקסים:**

.. code-block:: javascript

   db.collections.createIndex(
       { "user_id": 1, "created_at": -1 },
       { name: "user_created_idx" }
   )

אוסף: backups
--------------

**תיאור:** metadata של גיבויים

**שדות:**

.. list-table:: שדות backups
   :header-rows: 1
   :widths: 15 15 20 50

   * - שדה
     - סוג
     - חובה
     - תיאור
   * - ``_id``
     - ObjectId
     - כן
     - מזהה ייחודי
   * - ``user_id``
     - int
     - כן
     - מזהה משתמש
   * - ``backup_type``
     - string
     - כן
     - סוג גיבוי (full_backup/github_repo_zip/google_drive_backup)
   * - ``created_at``
     - datetime
     - כן
     - תאריך יצירה
   * - ``file_count``
     - int
     - כן
     - מספר קבצים
   * - ``total_size``
     - int
     - כן
     - גודל כולל בבייטים
   * - ``version``
     - string
     - לא
     - גרסת metadata
   * - ``rating``
     - string
     - לא
     - דירוג (🏆 מצוין/👍 טוב/🤷 סביר)
   * - ``note``
     - string
     - לא
     - הערה
   * - ``repo``
     - string
     - לא
     - repository (רק ל-github_repo_zip)

**אינדקסים:**

.. code-block:: javascript

   db.backups.createIndex(
       { "user_id": 1, "created_at": -1 },
       { name: "user_created_idx" }
   )
   
   db.backups.createIndex(
       { "backup_type": 1 },
       { name: "type_idx" }
   )

יחסים בין אוספים
------------------

.. mermaid::

   erDiagram
       users ||--o{ code_snippets : "has"
       users ||--o{ large_files : "has"
       users ||--o{ bookmarks : "has"
       users ||--o{ collections : "has"
       users ||--o{ backups : "has"
       code_snippets ||--o{ bookmarks : "referenced_by"
       code_snippets ||--o{ collections : "referenced_by"
       large_files ||--o{ bookmarks : "referenced_by"
       large_files ||--o{ collections : "referenced_by"

**הערות:**
- ``bookmarks.file_id`` יכול להצביע על ``code_snippets._id`` או ``large_files._id``
- ``collections.items[].file_id`` יכול להצביע על ``code_snippets._id`` או ``large_files._id``
- אין Foreign Key constraints ב-MongoDB - יש לבדוק תקינות בקוד

Best Practices
--------------

1. **תמיד לסנן לפי user_id** - בידוד נתונים בין משתמשים
2. **שימוש ב-is_active** - לא למחוק פיזית, רק soft delete
3. **אינדקסים** - להוסיף אינדקסים לפי שאילתות נפוצות
4. **Validation** - לוודא תקינות נתונים לפני שמירה
5. **Timestamps** - תמיד לעדכן ``updated_at`` בעדכון

קישורים
--------

- :doc:`/database/index`
- :doc:`/database/indexing`
- :doc:`/database/cursor-pagination`
- :doc:`/api/database.repository`
