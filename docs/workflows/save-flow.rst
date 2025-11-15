זרימת שמירת קוד (Save Flow)
==============================

סקירה כללית
------------

זרימת השמירה מאפשרת למשתמשים לשמור קטעי קוד בבוט דרך מספר מסלולים:
- הדבקת קוד ישירה
- העלאת קובץ (עד 20MB)
- מצב איסוף ארוך (מספר הודעות עם ``/done``)

מצבי שמירה
-----------

.. list-table:: מצבי שמירה
   :header-rows: 1
   :widths: 20 30 50

   * - מצב
     - טריגר
     - תיאור
   * - ``GET_CODE``
     - ``➕ הוסף קוד חדש``
     - מצב המתנה לקוד
   * - ``GET_FILENAME``
     - לאחר קבלת קוד
     - מצב המתנה לשם קובץ
   * - ``GET_NOTE``
     - לאחר קבלת שם
     - מצב המתנה להערה (אופציונלי)
   * - ``LONG_COLLECT``
     - ``/long`` או קוד >300KB
     - מצב איסוף מספר הודעות
   * - ``WAIT_ADD_CODE_MODE``
     - במצב איסוף ארוך
     - מצב המתנה להוספת קוד נוסף

זרימת עבודה בסיסית
-------------------

.. mermaid::

   sequenceDiagram
       participant U as User
       participant B as Bot
       participant H as SaveFlow Handler
       participant CS as CodeService
       participant DB as MongoDB

       U->>B: ➕ הוסף קוד חדש
       B->>H: start_save_flow()
       H->>H: בדיקת מצב (GET_CODE)
       H->>U: "שלח את הקוד שלך"
       
       U->>H: קוד (הודעה/קובץ)
       H->>H: בדיקת גודל
       alt קוד > 300KB
         H->>H: מעבר ל-LONG_COLLECT
         H->>H: _schedule_long_collect_timeout()
         H->>U: "מצב איסוף ארוך. שלח עוד קוד או /done"
       else קוד רגיל
         H->>H: נרמול קוד (normalize_code)
         H->>H: זיהוי secrets (_detect_secrets)
         alt נמצאו secrets
           H->>U: "אזהרה: נמצאו סודות בקוד"
         end
         H->>H: מעבר ל-GET_FILENAME
         H->>U: "מה שם הקובץ?"
       end
       
       U->>H: שם קובץ
       H->>H: בדיקת כפילויות
       alt קובץ קיים
         H->>U: תפריט: החלף/שנה שם/ביטול
       else קובץ חדש
         H->>H: מעבר ל-GET_NOTE
         H->>U: "הוסף הערה (אופציונלי) או /skip"
       end
       
       U->>H: הערה או /skip
       H->>CS: process_code(code, filename, language)
       CS->>CS: זיהוי שפה (detect_language)
       CS->>CS: ניתוח קוד (analyze_code)
       CS->>DB: save_snippet()
       DB-->>CS: file_id
       CS-->>H: success
       H->>U: "נשמר בהצלחה: {filename}"

מצב איסוף ארוך (LONG_COLLECT)
-------------------------------

מצב זה מאפשר איסוף קוד במספר הודעות:

.. code-block:: python

   # הגדרות
   LONG_COLLECT_MAX_BYTES = 300 * 1024  # 300KB
   LONG_COLLECT_TIMEOUT_SECONDS = 15 * 60  # 15 דקות

**זרימה:**

1. משתמש שולח ``/long`` או קוד >300KB
2. הבוט עובר למצב ``LONG_COLLECT``
3. כל הודעה נוספת מצטרפת ל-``context.user_data['code_parts']``
4. טיימאאוט של 15 דקות ללא פעילות מבטל את המצב
5. ``/done`` מסיים את האיסוף ומעביר ל-``GET_FILENAME``

**טיפול בטיימאאוט:**

.. code-block:: python

   def _schedule_long_collect_timeout(update, context):
       jid = f"long_collect_timeout:{update.effective_user.id}"
       job = context.job_queue.run_once(
           long_collect_timeout_job,
           when=LONG_COLLECT_TIMEOUT_SECONDS,
           data={'chat_id': ..., 'user_id': ...},
           name=jid,
           job_kwargs={'id': jid, 'replace_existing': True}
       )
       context.user_data['long_collect_job'] = job

זיהוי סודות (Secrets Detection)
---------------------------------

המערכת מזהה סודות בקוד לפני שמירה:

.. code-block:: python

   patterns = [
       r"ghp_[A-Za-z0-9]{36,}",  # GitHub Personal Access Token
       r"github_pat_[A-Za-z0-9_]{30,}",  # GitHub Fine-grained Token
       r"AIza[0-9A-Za-z\-_]{35}",  # Google API Key
       r"sk_(live|test)_[0-9A-Za-z]{20,}",  # Stripe Key
       r"xox[abprs]-[0-9A-Za-z\-]{10,}",  # Slack Token
       r"AWS_ACCESS_KEY_ID\s*=\s*[A-Z0-9]{16,20}",
       r"AWS_SECRET_ACCESS_KEY\s*=\s*[A-Za-z0-9/+=]{30,}",
       r"-----BEGIN (RSA |EC |)PRIVATE KEY-----",
       r"(?i)(api|secret|token|key)[\s:=\"]{1,20}[A-Za-z0-9_\-]{16,}"
   ]

**התנהגות:**
- אם נמצאו סודות, המשתמש מקבל אזהרה
- השמירה ממשיכה (לא נחסמת)
- המשתמש יכול לבחור לבטל

טיפול בכפילויות
-----------------

כאשר קובץ עם אותו שם כבר קיים:

.. code-block:: python

   # בדיקת קיום
   existing = await db.get_file_by_name(user_id, filename)
   
   if existing:
       # תפריט החלפה
       keyboard = [
           [InlineKeyboardButton("🔄 החלף", callback_data=f"replace:{file_id}")],
           [InlineKeyboardButton("📝 שנה שם", callback_data="rename")],
           [InlineKeyboardButton("❌ ביטול", callback_data="cancel")]
       ]

נרמול קוד
----------

כל קוד עובר נרמול לפני שמירה:

.. code-block:: python

   from utils import normalize_code
   
   normalized = normalize_code(code)
   # הסרת תווים נסתרים
   # נרמול שורות ריקות
   # טיפול בקידודים שונים

Edge Cases
----------

**קוד ריק:**
- נדחה עם הודעת שגיאה

**קובץ גדול מאוד (>20MB):**
- נדחה עם הודעת שגיאה
- מוצע להשתמש ב-GitHub או Google Drive

**טיימאאוט במצב LONG_COLLECT:**
- המצב מתבטל אוטומטית
- המשתמש מקבל הודעה
- כל הקוד שנאסף נמחק

**שגיאת שמירה ב-DB:**
- המשתמש מקבל הודעת שגיאה
- האירוע נרשם ב-Observability
- מונה שגיאות Prometheus מתעדכן

קישורים
--------

- :doc:`/handlers/document-flow`
- :doc:`/api/code_processor`
- :doc:`/database/index`
