זרימת גיבוי ושחזור (Backup Flow)
===================================

סקירה כללית
------------

מערכת הגיבויים מאפשרת:
- יצירת גיבוי מלא של כל קבצי המשתמש
- שחזור מגיבוי
- ניהול גיבויים (הורדה, מחיקה, דירוג)
- גיבויים אוטומטיים ל-Google Drive

סוגי גיבויים
-------------

.. list-table:: סוגי גיבויים
   :header-rows: 1
   :widths: 20 30 50

   * - סוג
     - מזהה
     - תיאור
   * - Full Backup
     - ``full_backup``
     - גיבוי מלא של כל הקבצים
   * - GitHub Repo Backup
     - ``github_repo_zip``
     - גיבוי של repository מ-GitHub
   * - Google Drive Backup
     - ``google_drive_backup``
     - גיבוי אוטומטי ל-Google Drive

יצירת גיבוי מלא
----------------

.. mermaid::

   sequenceDiagram
       participant U as User
       participant B as Bot
       participant H as Backup Handler
       participant BS as BackupService
       participant DB as MongoDB
       participant ZIP as ZIP Creator

       U->>B: 📦 גיבוי ושחזור → יצירת גיבוי
       B->>H: handle_create_backup()
       H->>DB: שליפת כל הקבצים של המשתמש
       DB-->>H: files[]
       
       H->>BS: create_backup(user_id, files)
       BS->>ZIP: יצירת ZIP
       loop לכל קובץ
         ZIP->>ZIP: הוספת קובץ ל-ZIP
         ZIP->>ZIP: הוספת metadata
       end
       
       ZIP->>ZIP: הוספת metadata.json
       ZIP-->>BS: zip_bytes
       BS->>DB: שמירת metadata גיבוי
       DB-->>BS: backup_id
       BS-->>H: backup_info
       H->>U: הורדת קובץ ZIP

**מבנה metadata.json:**

.. code-block:: json

   {
     "version": "1.0",
     "created_at": "2025-01-15T10:30:00Z",
     "user_id": 123456789,
     "total_files": 150,
     "total_size": 5242880,
     "files": [
       {
         "file_name": "example.py",
         "programming_language": "python",
         "code": "...",
         "note": "Example file",
         "tags": ["example"],
         "version": 3,
         "created_at": "2025-01-10T08:00:00Z",
         "updated_at": "2025-01-12T14:30:00Z"
       }
     ]
   }

שחזור מגיבוי
--------------

.. mermaid::

   sequenceDiagram
       participant U as User
       participant B as Bot
       participant H as Backup Handler
       participant BS as BackupService
       participant ZIP as ZIP Extractor
       participant DB as MongoDB

       U->>B: 📦 גיבוי ושחזור → שחזור מגיבוי
       B->>H: handle_restore_backup()
       H->>U: רשימת גיבויים זמינים
       U->>H: בחירת גיבוי
       
       H->>BS: get_backup(backup_id)
       BS->>DB: שליפת metadata
       DB-->>BS: backup_metadata
       BS->>ZIP: פתיחת ZIP
       ZIP->>ZIP: קריאת metadata.json
       ZIP->>ZIP: חילוץ קבצים
       ZIP-->>BS: files[]
       
       BS->>BS: בדיקת כפילויות
       loop לכל קובץ
         alt קובץ קיים
           BS->>U: "החלף {filename}? (כן/לא/דלג)"
           U->>BS: החלטה
         end
         BS->>DB: שמירת קובץ
       end
       
       BS-->>H: restore_result
       H->>U: "שוחזרו {count} קבצים"

גיבוי ל-Google Drive
---------------------

.. mermaid::

   sequenceDiagram
       participant U as User
       participant B as Bot
       participant H as Backup Handler
       participant BS as BackupService
       participant GDS as GoogleDriveService
       participant GD as Google Drive API

       U->>B: ☁️ Google Drive → גיבוי ידני
       B->>H: handle_google_drive_backup()
       H->>BS: create_backup(user_id)
       BS-->>H: zip_bytes
       
       H->>GDS: upload_backup(zip_bytes, user_id)
       GDS->>GD: files().create()
       GD-->>GDS: file_id
       GDS->>DB: שמירת metadata גיבוי Drive
       DB-->>GDS: success
       GDS-->>H: backup_url
       H->>U: "גיבוי הועלה ל-Google Drive"

**גיבויים אוטומטיים:**

.. code-block:: python

   # תזמון גיבוי אוטומטי
   SCHEDULED_BACKUP_INTERVALS = {
       'daily': timedelta(days=1),
       'weekly': timedelta(weeks=1),
       'monthly': timedelta(days=30)
   }
   
   # Job scheduler
   @scheduled_job(interval='daily')
   async def auto_backup_to_drive():
       users = await db.get_users_with_drive_enabled()
       for user in users:
           backup = await backup_service.create_backup(user.user_id)
           await google_drive_service.upload_backup(backup, user.user_id)

ניהול גיבויים
--------------

**רשימת גיבויים:**

.. code-block:: python

   backups = await db.get_user_backups(user_id, limit=10, offset=0)
   
   # כל גיבוי כולל:
   {
       'backup_id': ObjectId(...),
       'user_id': 123456789,
       'backup_type': 'full_backup',
       'created_at': datetime(...),
       'file_count': 150,
       'total_size': 5242880,
       'version': '1.0',
       'rating': '🏆 מצוין',  # אופציונלי
       'note': 'גיבוי לפני שינוי גדול',  # אופציונלי
       'repo': 'owner/repo'  # רק ל-github_repo_zip
   }

**פעולות:**

- **הורדה:** ``handle_download_backup(backup_id)``
- **מחיקה:** ``handle_delete_backup(backup_id)``
- **דירוג:** ``handle_rate_backup(backup_id, rating)``
- **הוספת הערה:** ``handle_add_backup_note(backup_id, note)``

**מחיקה מרובה:**

.. code-block:: python

   # בחירת מספר גיבויים
   selected_backups = [backup_id1, backup_id2, ...]
   
   # אישור מחיקה
   await db.delete_backups(selected_backups)
   
   # לוג event
   emit_event("backups_deleted", 
              severity="info",
              user_id=user_id,
              count=len(selected_backups))

ייבוא ZIP חיצוני
-----------------

.. code-block:: python

   async def handle_import_zip(update, context):
       # קבלת קובץ ZIP
       zip_file = await context.bot.get_file(update.message.document.file_id)
       
       # פתיחת ZIP
       with zipfile.ZipFile(zip_file, 'r') as zip_ref:
           # קריאת metadata
           metadata = json.loads(zip_ref.read('metadata.json'))
           
           # זיהוי repository (אם קיים)
           repo = metadata.get('repo') or _detect_repo_from_structure(zip_ref)
           
           # חילוץ קבצים
           for file_info in zip_ref.infolist():
               if file_info.filename.endswith('.py'):
                   code = zip_ref.read(file_info.filename).decode('utf-8')
                   await db.save_file(
                       user_id=user_id,
                       file_name=file_info.filename,
                       code=code,
                       tags=[repo] if repo else []
                   )

Edge Cases
----------

**גיבוי ריק (אין קבצים):**
- נוצר ZIP עם metadata.json בלבד
- המשתמש מקבל הודעה

**שגיאת יצירת ZIP:**
- המשתמש מקבל הודעת שגיאה
- האירוע נרשם ב-Observability

**גיבוי גדול מאוד (>100MB):**
- מוצע להשתמש ב-Google Drive
- או חלוקה למספר גיבויים

**שחזור עם כפילויות:**
- המשתמש מקבל תפריט לכל קובץ
- יכול לבחור: החלף/דלג/שנה שם

**שגיאת Google Drive:**
- הגיבוי נשמר מקומית
- המשתמש מקבל הודעה
- ניסיון חוזר מתוזמן

**גיבוי פגום:**
- בדיקת תקינות ZIP לפני שחזור
- אם פגום, המשתמש מקבל הודעת שגיאה

קישורים
--------

- :doc:`/api/services.backup_service`
- :doc:`/api/backup_menu_handler`
- :doc:`/services/google_drive_service`
- :doc:`/runbooks/github_backup_restore`
