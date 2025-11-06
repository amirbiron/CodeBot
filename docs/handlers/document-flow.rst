זרימת הטיפול במסמכים (Document Flow)
=====================================

מפה ותפקידים
-------------
- ``CodeKeeperBot`` משמש כ‑Facade ומפנה ל‑``handlers/documents.py`` (``DocumentHandler``).
- פונקציות עיקריות:
  - ``_handle_github_restore_zip_to_repo`` – שחזור ZIP לריפו קיים
  - ``_handle_github_create_repo_from_zip`` – יצירת ריפו חדש מקובץ ZIP
  - ``_handle_zip_import`` – יבוא ZIP פנימי ושחזור קבצים
  - ``_handle_zip_create`` – יצירת ZIP מרשימת קבצים שנאספת
  - ``_handle_textual_file`` – נרמול, זיהוי קידוד, ושמירת קובץ טקסט

זרימת טיפול בקובץ
------------------
.. mermaid::

   sequenceDiagram
       participant U as User
       participant B as Bot
       participant H as DocumentHandler
       participant GH as GitHub
       participant DB as MongoDB

       U->>B: שולח קובץ
       B->>H: handle_document()
       H->>H: בדיקת upload_mode
       alt github_restore_zip_to_repo
         H->>GH: Restore ZIP to repo (commit)
       else github_create_repo_from_zip
         H->>GH: Create repo + upload tree
       else zip_import
         H->>DB: Restore from internal ZIP backup
       else zip_create
         H->>H: צבירת קבצים ל‑bundle
       else textual file
         H->>DB: save_snippet/save_large_file
       end

מצבי upload_mode
-----------------
- ``github_restore_zip_to_repo``
- ``github_create_repo_from_zip``
- ``zip_import``
- ``zip_create``
- ``github`` או ``waiting_for_github_upload`` – העלאה ישירה דרך Handler ה‑GitHub

תלויות והזרקות
---------------
נדרשות להזנת הבנאי של ``DocumentHandler``:
- ``notify_admins`` – הודעות ניהוליות
- ``log_user_activity`` – רישום פעילות משתמש
- ``emit_event`` – אירועי Observability
- ``errors_total`` – מונה שגיאות Prometheus
- ``encodings_to_try`` – רשימת קידודים לניסיון

Best Practices
--------------
- לשמור state ב‑``context.user_data`` היכן שנדרש.
- להכיל הודעות HTML בטוחות בלבד.
- להקפיד על מגבלות: גודל קבצים, קצב GitHub API.
- בכל הוספת מסלול חדש: לעדכן תיעוד וטסטים רלוונטיים (למשל ``tests/test_main_file_events.py``).

ראו גם
------
- :doc:`/architecture`
- :doc:`/handlers/index`
- :doc:`/webapp/overview`
