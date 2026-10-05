זרימת גיבוי ושחזור (Backup Flow)
===================================
:summary: זרימת הגיבוי והשחזור מקצה לקצה: סוגי הגיבויים, יצירת גיבוי מלא, שחזור, העלאה ל-Google Drive, ניהול הגיבויים הקיימים, וייבוא ZIP חיצוני.

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

העלאה ל-Google Drive אינה גיבוי שנשמר ברשימת הגיבויים של הבוט, ולכן אינה בטבלה. ה-ZIP שנבנה לה ב-``create_full_backup_zip_bytes`` נושא ``metadata.json`` עם ``backup_type`` בצורה ``drive_manual_<קטגוריה>`` — ראו :ref:`backup-flow-drive`.

מבנה ה-ZIP של גיבוי ריפו
~~~~~~~~~~~~~~~~~~~~~~~~~

‏``github_repo_zip`` אינו ארכיון שהבוט בונה בעצמו. הוא ה-zipball הרשמי של GitHub — שכל תוכנו יושב תחת תיקייה אחת בשם ``owner-repo-sha`` — ואליו מתווסף ``metadata.json`` **בשורש הארכיון**::

   metadata.json
   owner-repo-6dfaac9/README.md
   owner-repo-6dfaac9/src/main.py

**השחזור לריפו סופר תיקיות בלבד.** קובץ בשורש אינו מכיל ``/``, ולכן אינו משתתף בספירה: נשארת תיקייה אחת, היא נחתכת, והתוכן נוחת בשורש הריפו. ``metadata.json`` עולה לריפו יחד עם התוכן — כך זה תמיד היה, וקובץ בשם הזה בשורש אינו מפריע.

**והמחיר של הכלל הזה, שהוא מכוון:** ZIP שאינו גיבוי — למשל ``README.md`` בשורש לצד ``src/`` — יאבד רובד, ו-``src/main.py`` ייכתב כ-``main.py``. המסך שמבקש את הקובץ מתריע על כך לפני ההעלאה, ב-``RESTORE_ZIP_PROMPT`` שב-``github_menu_handler.py``.

.. warning::

   ‏``detect_zip_common_root`` **אינה מתאימה למסלול הזה**, ואין לאחד ביניהם. היא מבטלת את זיהוי השורש ברגע שיש קובץ בשורש — כלל נכון לייבוא ZIP, שמונע חיתוך שגוי של ארכיון כמו ``README.md`` לצד ``src/`` — אבל כאן ``metadata.json`` מפעיל אותו, והריפו כולו נפרס בתוך תיקייה בשם ``owner-repo-sha``. האיחוד הזה כבר נעשה פעם אחת ושבר את השחזור.

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

.. _backup-flow-drive:

גיבוי ל-Google Drive
---------------------

לבוט ולוובאפ יש חיבור Drive נפרד, ולכל אחד תזמון ומתזמן משלו — ראו :ref:`drive-owner`. הפונקציות שמוזכרות כאן מתועדות ב-:doc:`/services/google_drive_service`.

**בבוט** (``handlers/drive/menu.py``, עם ``drive_owner.BOT``):

- **התחברות** — ב-Device Flow: ``start_device_authorization`` מחזיר קוד שהמשתמש מקליד בדף של גוגל, והבוט בודק אם האישור הגיע (``poll_device_token``) בשלוש דרכים: בדיקה ברקע, הכפתור ``drive_poll_once``, והודעה שהמשתמש שולח בצ'אט בזמן ההמתנה (``handle_text``). בשלושתן החיבור מוצג כ"הושלם" רק אחרי שהטוקנים נשמרו (``_save_auth_tokens``).
- **גיבוי ידני** — בחירת קטגוריה ואישור (``drive_simple_confirm``). בקטגוריה ``zip`` עולים קבצי ה-ZIP השמורים בבוט שעוד לא הועלו (``upload_all_saved_zip_backups``); בקטגוריה ``all`` נבנה ZIP מלא (``create_full_backup_zip_bytes``) ועולה (``upload_bytes``) לתת-התיקייה של הקטגוריה (``compute_subpath``), בשם מ-``compute_friendly_name``.
- **תזמון** — ``drive_set_schedule:<key>`` שומר בהעדפות של הבוט את התזמון (``schedule``) ואת הקטגוריה (``schedule_category``), ויוצר job ב-job queue של הבוט (``_ensure_schedule_job``). כל הרצה קוראת ל-``perform_scheduled_backup``, שמעלה לפי הקטגוריה: ``zip``, ‏``by_repo`` (ZIP לכל ריפו, ``create_repo_grouped_zip_bytes``), או ZIP אחד ל-``all`` / ``large`` / ``other``. אחרי עלייה מחדש ה-job ``drive_reschedule`` ב-``main.py`` משחזר את ה-jobs של מי שיש לו תזמון פעיל (``get_users_with_active_drive_schedule``).

**בוובאפ** (עם ``drive_owner.WEBAPP``):

- **התחברות** — בהפניה לגוגל (``webapp/drive_auth.py``), ראו :ref:`drive-webapp-connect`.
- **מה עולה** — הגיבוי האישי המלא (``PersonalBackupService.export_user_data``), כ-ZIP אחד לתיקיית היעד (``upload_bytes`` בלי תת-תיקייה), ב-``_perform_drive_backup`` שב-``webapp/backup_scheduler.py``.
- **"גבה עכשיו"** — ``POST /api/drive/backup-now`` מסמן ``manual_backup_status`` כ-``running``, רק במסמך של משתמש מחובר, ומריץ את הגיבוי ברקע. הדף קורא את המצב מ-``GET /api/drive/backup-status``.
- **תזמון** — ``POST /api/drive/schedule`` שומר ``schedule_key`` ו-``schedule_next_at``. ה-thread של ``webapp/backup_scheduler.py`` סורק כל ``SCAN_INTERVAL_SECONDS``, תופס אטומית משתמש שהגיע זמנו (``_drive_claim_filter``, עם אינדקס משלו) ומריץ את הגיבוי.

גיבוי ידני של "הכל" בבוט:

.. mermaid::

   sequenceDiagram
       participant U as משתמש
       participant M as GoogleDriveMenuHandler
       participant GDS as google_drive_service
       participant GD as Google Drive API

       U->>M: drive_sel_all, ואז drive_simple_confirm
       M->>GDS: get_drive_service(owner=BOT)
       M->>GDS: create_full_backup_zip_bytes(user_id, "all")
       M->>GDS: upload_bytes(..., sub_path=compute_subpath("all"), owner=BOT)
       GDS->>GD: files().create() ו-next_chunk()
       GD-->>GDS: file id
       GDS-->>M: file id, או None בכשל
       M->>U: הודעת הצלחה, או הודעת כשל

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
- אין שמירה מקומית כגיבוי חלופי. בקטגוריות שבונות את ה-ZIP בזיכרון (``all``, ‏``by_repo``, ‏``large``, ‏``other``, וגם הגיבוי של הוובאפ) מה שלא עלה לא נשמר במקום אחר. בקטגוריה ``zip`` (קבצי גיבוי) מועלים ZIPים שכבר שמורים בבוט (``backup_manager``), והם נשארים במקומם. ב-``uploaded_backup_ids`` נרשם ZIP שעלה, וגם ZIP שלא הועלה כי קובץ עם אותו תוכן (לפי md5) כבר נמצא בתיקיית ה-``zip`` ב-Drive (``_upload_all_saved_zip_backups_detailed``). ZIP שההעלאה שלו נכשלה לא נרשם, ולכן בפעם הבאה שהקטגוריה מועלית — ידנית או בתזמון — הוא מועלה שוב, אלא אם נמצא בתיקייה קובץ עם אותו תוכן.
- בבוט, בגיבוי ידני: המשתמש מקבל הודעת כשל, ואין ניסיון חוזר.
- בבוט, בגיבוי מתוזמן: נשלח ``drive_scheduled_backup_result`` עם ``ok`` שקר. כשאי אפשר לבנות שירות Drive מהטוקנים השמורים, המשתמש מקבל בקשה להתחבר מחדש (``drive_scheduled_backup_auth_required``). ההרצה הבאה היא במועד הבא של התזמון.
- בוובאפ: נשלח ``webapp_drive_backup_failed``. ב"גבה עכשיו" המצב הופך ל-``error``; גיבוי מתוזמן מנוסה שוב בסריקה הבאה (``_retry_next_at``).
- העלאה שנכשלה נרשמת בלוג בשורת ``drive_call_failed`` (``_log_drive_call_failed`` ב-``services/google_drive_service.py``), עם הפעולה שנכשלה וסטטוס ה-HTTP.

**גיבוי פגום:**
- בדיקת תקינות ZIP לפני שחזור
- אם פגום, המשתמש מקבל הודעת שגיאה

קישורים
--------

- :doc:`/api/services.backup_service`
- :doc:`/api/backup_menu_handler`
- :doc:`/services/google_drive_service`
- :doc:`/runbooks/github_backup_restore`
