מבנה נתונים מפורט (Detailed Database Schema)
==============================================
:summary: מסמך זה מתאר בפירוט את כל האוספים, השדות, האילוצים והאינדקסים במסד הנתונים.

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
     - מספר גרסה (ברירת מחדל: 1). **ייחודי לכל** ``(user_id, file_name)``, **בלי קשר ל-**\ ``is_active``: מחיקה רכה משאירה את המסמכים במסד והם יכולים לחזור בשחזור מהסל, ולכן חישוב הגרסה הבאה סופר גם אותם
   * - ``created_at``
     - datetime
     - לא
     - תאריך יצירת **הקובץ**, לא של השורה. כל גרסה היא מסמך נפרד, וגרסה חדשה יורשת את הערך מהגרסה הקודמת
   * - ``updated_at``
     - datetime
     - לא
     - תאריך השינוי האחרון **בקובץ עצמו** — בתוכן, בתיאור או בשם. בקובץ שמעולם לא נערך הוא זהה ל-``created_at``. הקו הוא בין שדה של הקובץ לבין סימון עליו: נעיצה, מועדפים, תיוג, מחיקה רכה ושחזור מהסל אינם משנים את הקובץ אלא רק תווית שעליו, ולכן **אינם** נוגעים ב-``updated_at``. לשלושה מהם יש שדה משלהם (``pinned_at``, ``favorited_at``, ``deleted_at``); לתיוג אין, כי אף מסך אינו מציג מתי תגית נוספה
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
     - תאריך יצירת הקובץ. שמירה חוזרת מוחקת את המסמך ומכניסה חדש, והערך עובר אליו
   * - ``updated_at``
     - datetime
     - לא
     - תאריך עדכון. בקובץ שמעולם לא נשמר מחדש הוא זהה ל-``created_at``
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

אוסף: sticky_notes
-------------------

**תיאור:** פתקים דביקים. פתק שייך ל**יעד אחד בדיוק** — קובץ, לוח, או קובץ בריפו ממורר (הזוג ``repo_name`` + ``repo_path`` יחד).

.. list-table:: שדות sticky_notes (חלקי)
   :header-rows: 1
   :widths: 18 14 16 52

   * - שדה
     - סוג
     - חובה
     - תיאור
   * - ``user_id``
     - int
     - כן
     - בעל הפתק. נמצא בכל שאילתה.
   * - ``file_id``
     - str
     - מותנה
     - הקובץ שאליו הפתק צמוד. ריק בפתקי לוח ובפתקי ריפו.
   * - ``board_id``
     - str
     - מותנה
     - הלוח שעליו הפתק יושב. ריק בפתקי קובץ ובפתקי ריפו.
   * - ``repo_name``
     - str
     - מותנה
     - הריפו הממורר. קיים רק בפתקי ריפו, ותמיד יחד עם ``repo_path``.
   * - ``repo_path``
     - str
     - מותנה
     - נתיב הקובץ בעץ הריפו, מנורמל לצורת ``repo_files`` (לוכסנים קדימה, בלי ``/`` מוביל). קיים רק בפתקי ריפו.
   * - ``scope_id``
     - str
     - לא
     - מפתח פילוח לפי שם הקובץ. קיים רק בפתקי קובץ.
   * - ``mode``
     - str
     - לא
     - ``surface`` (נע עם הלוח) או ``screen`` (צמוד למסך). נכתב רק בפתקי לוח; בפתקי קובץ המצב עדיין נגזר מ-``anchor_id``.
   * - ``content``
     - str
     - כן
     - עד 20,000 תווים. התקרה מוגדרת פעם אחת ב-``sticky_notes_target.MAX_NOTE_CHARS`` ומיובאת משם ל-webapp, ל-MCP ולתבניות.
   * - ``position_x`` / ``position_y``
     - int
     - כן
     - מיקום. בפתק לוח הקואורדינטות יחסיות למשטח, ולא למסמך.
   * - ``width`` / ``height``
     - int
     - כן
     - גודל.

.. important::
   **האילוץ "בדיוק אחד" נאכף ב-**\ ``sticky_notes_target.build_note_target``, שכל מסלולי הכתיבה עוברים דרכו. הכלל טרנרי (קובץ/לוח/ריפו) ותכונתי: ``TARGET_FIELDS`` ממפה כל סוג לשדות שמותר לו לשאת, וכל שדה זר נדחה. אין ``$jsonSchema`` validator ברמת מונגו, כי אין בריפו תשתית migrations שתחזיק אותו — במקומו ``scripts/migrate_note_boards.py`` מדפיס דוח הפרות, והרצה חוזרת שלו היא הבדיקה.

**אינדקסים:** ``(user_id, file_id)``, ``(user_id, file_id, created_at)``, ``(user_id, scope_id)``, ``(user_id, board_id)``, ``(user_id, repo_name, repo_path)``, ``(updated_at)``. שני אינדקסי שם ייחודיים-חלקיים: ``one_title_per_board_v2`` (מסונן על ``board_id`` קיים) ו-``one_title_per_repo_file_v1`` (מסונן על ``repo_path`` קיים).

אוסף: note_boards
------------------

**תיאור:** לוחות פתקים. משטח שעליו יושבים פתקים שאינם צמודים לקובץ.

.. list-table:: שדות note_boards
   :header-rows: 1
   :widths: 18 14 16 52

   * - שדה
     - סוג
     - חובה
     - תיאור
   * - ``_id``
     - ObjectId
     - כן
     - מזהה הלוח. יציב — ולכן אין צורך ב-``scope_id`` לפתקי לוח.
   * - ``user_id``
     - int
     - כן
     - בעל הלוח.
   * - ``name``
     - str
     - כן
     - שם הלוח. ניתן לשינוי, כולל בלוח ברירת המחדל.
   * - ``is_default``
     - bool
     - כן
     - לוח ברירת המחדל. **הזיהוי הוא לפי השדה הזה ולא לפי השם**, כי השם ניתן לשינוי.
   * - ``order``
     - int
     - כן
     - סדר תצוגה.
   * - ``created_at`` / ``updated_at``
     - datetime
     - כן
     - חותמות זמן.

**אינדקסים:** ``(user_id, order)``, ו-``(user_id)`` **ייחודי-חלקי** על ``is_default: true``.

.. note::
   האינדקס הייחודי-החלקי הוא מה שסוגר את המרוץ שבו שתי בקשות מקבילות מגלות שאין לוח ברירת מחדל ושתיהן יוצרות. הגנת קוד לבדה אינה מספיקה שם — המסד חייב לדחות, והקוד קורא שוב ומחזיר את הלוח שנוצר.

יחסים בין אוספים
------------------

**דיאגרמת יחסים בסיסית:**

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

סכמת מערכת Observability - התראות ומטריקות
-------------------------------------------

הדיאגרמה הבאה מציגה את מבנה הנתונים עבור מערכת המוניטור וההתראות:

.. mermaid::

   erDiagram
       METRICS ||--o{ ALERTS : triggers
       METRICS {
           string request_id PK
           datetime timestamp
           string metric_type
           string operation
           string status
           float value
           json metadata
           string user_id FK
           string error_code
       }

       ALERTS ||--o{ ALERT_ACTIONS : has
       ALERTS {
           string alert_id PK
           datetime timestamp
           string severity
           string alert_type
           string title
           text description
           array affected_services
           json metrics_snapshot
           datetime resolved_at
       }

       ALERT_ACTIONS {
           int id PK
           string alert_id FK
           string action_type
           text suggestion
           string runbook_url
       }

       CODE_DUPLICATES ||--|| FILES : references
       CODE_DUPLICATES {
           string duplicate_id PK
           datetime detection_time
           string file1
           int file1_start_line
           int file1_end_line
           string file2
           int file2_start_line
           int file2_end_line
           float similarity_score
           string detection_method
       }

       METRICS_AGGREGATES ||--|| METRICS : summarizes
       METRICS_AGGREGATES {
           int id PK
           datetime period_start
           datetime period_end
           string operation
           int total_requests
           int success_count
           int error_count
           float avg_latency_ms
           float p95_latency_ms
       }

**הסבר הטבלאות:**

- **METRICS**: מטריקות גולמיות לכל בקשה (latency, status, errors)
- **ALERTS**: התראות שנוצרו על סמך ניתוח המטריקות
- **ALERT_ACTIONS**: פעולות מומלצות לכל התראה (suggestions, runbooks)
- **CODE_DUPLICATES**: זיהוי קוד כפול בין קבצים
- **METRICS_AGGREGATES**: אגרגציות תקופתיות של המטריקות

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
