קטלוג אירועים קנוניים
======================
:summary: הקטלוג הקנוני של שמות האירועים — GitHub, שיתוף ווב, התראות, Google Drive, Repo Analyzer ואירועי ביזנס — עם הכלל לשמות ב-snake_case ובלי PII.

.. admonition:: עיקרון
   :class: tip

   שמרו על שמות אירועים ב-``snake_case``; הימנעו מ-PII. השתמשו ב-``resource`` ו-``attributes``.

GitHub
------

- ``github_rate_limit_check`` — בדיקת Rate Limit.
- ``github_upload_start`` — התחלת תהליך העלאה.
- ``github_upload_saved_error`` — שגיאה בשמירת קובץ שהועלה.
- ``github_upload_direct_error`` — שגיאה בהעלאה ישירה.
- ``github_import_repo_error`` — שגיאה בייבוא ריפו.
- ``github_sync`` — סנכרון קבצים מוצלח.

.. code-block:: json

   {"event":"github_upload_saved_error","severity":"error","request_id":"a3f2c891","repo":"owner/repo","error":"Rate limit exceeded"}

DB
--

- ``db_get_latest_version_error`` — שגיאה בשליפת גרסה אחרונה.
- ``db_save_code_snippet_error`` — שגיאה בשמירת קטע קוד.
- ``db_delete_file_error`` — שגיאה במחיקה.
- ``db_mcp_uploads_index_missing`` — אינדקס של התנהגות על ``mcp_uploads`` — ה-TTL על ``expires_at`` או הייחודי על ``upload_id``, לפי ``index_name`` — אינו במצב המבוקש. בלי ה-TTL העלאות שלא נצרכו אינן נמחקות לעולם, ולכן שער המוכנות של שירות ה-MCP עונה ``503 upload_storage_unavailable`` על כל העלאה עד שהוא מאומת. נשלח מ-``DatabaseManager._create_mcp_uploads_indexes`` בכל עלייה ובכל ניסיון בנייה של השער; הסיבה הטכנית נרשמת לפניו באירוע של ``safe_create_index``. ראו :ref:`mcp-uploads`.
- ``db_recycle_bin_ttl_index_missing`` — אינדקס ה-TTL שמרוקן את סל המיחזור אינו במצב המבוקש בקולקציה שב-``collection``. בלעדיו פריטים בסל אינם נמחקים לעולם, והעמוד ``/trash`` ממשיך להציג "נמחק סופית ב-" על תאריכים שעברו. נשלח מ-``DatabaseManager._create_recycle_bin_ttl_indexes`` בכל עלייה ובפקודה ``/recycle_backfill``; הסיבה הטכנית נרשמת לפניו באירוע של ``safe_create_index``. המצב הנוכחי נראה בעמוד ``/admin/verify-indexes``, בסעיף ``recycle_bin_ttl``.

.. code-block:: json

   {"event":"db_get_latest_version_error","severity":"error","request_id":"a3f2c891","error":"not found"}

Web/Share
---------

- ``share_view_error`` — שגיאה בטעינת עמוד שיתוף.
- ``share_view_not_found`` — שיתוף לא נמצא.
- ``internal_web_started`` — שירות פנימי הועלה.

.. code-block:: json

   {"event":"share_view_error","severity":"error","request_id":"a3f2c891","share_id":"abc","error":"invalid"}

Alerts
------

- ``alert_received`` — התקבלה התראה מה-Alertmanager.
- ``alerts_parse_error`` — כשל בפענוח ההתראה.

Web Push
--------

מנוי ותפעול:

- ``push_subscribed`` / ``push_unsubscribed`` — דפדפן נרשם למנוי או הוסר ממנו.
- ``push_subscriptions_cleanup`` / ``push_subscriptions_delete_all`` — ניקוי מנויים מעמוד ההגדרות.
- ``push_deleted_dead_endpoints`` — מנויים שהוסרו אחרי ``404``/``410`` משירות הפוש.
- ``sw_push_report`` — דיווח מה-Service Worker על שלב בטיפול בהתראה.

שליחה של תזכורות פתקים:

- ``push_send_attempt`` — ניסיון שליחה של תזכורת שהגיע זמנה.
- ``push_send_error`` — כשל בשליחה למנוי. נרשם עם ``endpoint_hash`` ולא עם ה-endpoint עצמו, שהוא מזהה מכשיר.
- ``push_send_no_subscriptions`` — למשתמש אין מנוי פעיל.
- ``push_send_missing_vapid_private`` — המסלול המקומי נבחר בלי מפתח VAPID פרטי.

שליחה של אירועי כתיבה מה-MCP:

- ``push_event_send_attempt`` — ניסיון שליחה של אירוע שנרשם על ידי שירות ה-MCP.
- ``push_event_unknown_kind`` — האירוע נושא ``kind`` שגרסת ה-WebApp הזו אינה יודעת לבנות ממנו התראה. הוא מכובה ואינו נשלח, כדי שלא ייבחר בכל סבב מכאן והלאה.
- ``push_event_delivery_exhausted`` — המסירה נכשלה עד תקרת הניסיונות, והאירוע עבר למצב סופי בלי שנשלח. עולה על כשל שאינו ``404``/``410`` — כלומר כזה שאינו מוחק את המנוי ולכן חוזר על עצמו בכל סבב.

בדיקה ידנית:

- ``push_test_result`` / ``push_test_local_error`` / ``push_test_worker_error`` — תוצאות ``POST /api/push/test``.

Jobs
----

- ``job_started`` — הרצת Job התחילה.
- ``job_completed`` — הרצה הסתיימה בהצלחה.
- ``job_failed`` — הרצה נכשלה.
- ``job_skipped`` — הרצה דולגה (מושבת, או כבר רץ).
- ``job_stuck`` — הרצה עברה את סף הזמן ועדיין ``running``.
- ``job_runs_reconciled`` — הרצות שנשארו ממחזיק מנעול קודם נסגרו בעלייה.
  אירוע מסכם אחד לכל פיוס: ``count`` הוא המניין המלא, ‏``job_ids_sample``
  הוא מדגם ולא הרשימה כולה. ראו :doc:`background-jobs-monitor`.
  כשלא נמצא מה לסגור נרשמת שורת לוג באותו שם עם ``count`` אפס — ולא נשלח
  אירוע — כדי ש"רץ ולא מצא כלום" ייראה שונה מ"לא רץ".
- ``jobs_orphan_reconcile_skipped`` — הפיוס לא רץ כלל. ‏``reason`` אומר למה:
  ``no_lock`` (התהליך אינו מחזיק זמן רכישת מנעול, למשל תחת ``LOCK_FAIL_OPEN``)
  או ``no_db`` (אוסף ``job_runs`` לא זמין).
- ``jobs_orphan_reconcile_timed_out`` — הפיוס נחתך אחרי ``RECONCILE_TIMEOUT_SECS``
  (‏``services/job_orphan_reconciler.py``). מה שלא נסגר ממתין לעלייה הבאה.
- ``jobs_orphan_reconcile_failed`` — הפיוס נפל על חריגה; ה-traceback בלוג.
- ``job_run_reconcile_skipped`` — הרצה **אחת** לא נסגרה כי הסטטוס שלה השתנה
  בין השליפה לעדכון (סיימה בעצמה). נספרת ב-``skipped`` של האירוע המסכם.
  השמות ברמת הג'וב פותחים במזהה הג'וב, ``jobs_orphan_reconcile``; השם ברמת
  ההרצה הבודדת פותח ב-``job_run`` — כדי שחיפוש על אחד לא יתפוס את השני בטעות.

דוגמה לאירוע המסכם ``job_runs_reconciled``:

.. code-block:: json

   {"event":"job_runs_reconciled","severity":"warn","count":3,"skipped":0,"truncated":false,"job_ids_sample":["cache_warming","drive_sync"]}

.. _drive-events:

Google Drive
------------

לבוט ולוובאפ יש חיבור Drive נפרד (ראו :ref:`drive-owner`).

חיבור, ניתוק ותזמון בוובאפ (``webapp/drive_auth.py``, ‏``webapp/drive_backup_api.py``):

- ``webapp_drive_connected`` — החיבור של הוובאפ נשמר, אחרי חזרה תקינה מגוגל.
- ``webapp_drive_disconnected`` — החיבור של הוובאפ נמחק. החיבור של הבוט לא משתנה.
- ``webapp_drive_schedule_set`` — נקבע תזמון גיבוי לוובאפ (``schedule``).
- ``webapp_drive_auth_failed`` — חיבור לא התחיל, כי ה-state לא נשמר במסד (``reason``: ``state_store_failed``). המשתמש מקבל שגיאה ולא נשלח לגוגל.
- ``webapp_drive_callback_rejected`` — חזרה מגוגל שנדחתה. ``reason`` אומר למה, ו-``user_id`` מצורף כשיש משתמש ב-session. ‏state, ‏code, טוקנים וגוף התשובה של גוגל לא נרשמים — ``tests/test_webapp_drive_oauth_state.py`` בודק את זה אחרי כל טסט בקובץ.

הסיבות ב-``webapp_drive_callback_rejected`` (הרשימה מושווית לקוד ב-``tests/test_webapp_drive_oauth_state.py``):

.. drive-rejection-reasons:start

- ``session_missing`` — אין משתמש מחובר ב-session.
- ``state_missing`` — החזרה הגיעה בלי state.
- ``state_check_failed`` — שגיאת מסד בבדיקת ה-state.
- ``state_not_found_or_expired`` — ה-state לא שייך למשתמש הזה, כבר נוצל, או שפג תוקפו.
- ``google_error`` — גוגל החזיר שגיאה. הקוד שלה ב-``google_error``, או ``unrecognized`` כשהוא לא בצורה של קוד OAuth.
- ``code_missing`` — החזרה הגיעה בלי code.
- ``token_exchange_failed`` — החלפת ה-code בטוקנים נכשלה: ``error_type`` כשלא הגענו לגוגל, או ``http_status`` ו-``google_error`` כשגוגל ענה בשגיאה.
- ``token_response_invalid`` — תשובת הטוקנים אינה אובייקט JSON: לא JSON בכלל, או JSON שאינו אובייקט (``http_status``).
- ``no_access_token`` — בתשובת הטוקנים אין ``access_token``.
- ``save_failed`` — שמירת הטוקנים במסד נכשלה.

.. drive-rejection-reasons:end

.. code-block:: json

   {"event":"webapp_drive_callback_rejected","severity":"warn","reason":"token_exchange_failed","user_id":123456789,"http_status":400,"google_error":"invalid_grant"}

גיבוי בוובאפ (``webapp/backup_scheduler.py``):

- ``webapp_drive_backup_failed`` — גיבוי Drive של הוובאפ, מתוזמן או "גבה עכשיו", לא הועלה. ``reason``: ``upload_failed`` כשההעלאה לא החזירה מזהה קובץ — הסיבה בשורת הלוג ``drive_call_failed`` של ``services/google_drive_service.py`` — או ``exception``, עם ``error_type``. ברמת ``warn``: גיבוי מתוזמן שנכשל מנוסה שוב בסריקה הבאה (``_retry_next_at``), ואירוע ``error`` היה חוזר כל כמה דקות על חיבור שבוטל.

התפריט והגיבוי המתוזמן בבוט (``handlers/drive/menu.py``, ‏``main.py``):

- ``drive_handler_ready`` — ה-handler של תפריט ה-Drive (``GoogleDriveMenuHandler``) נוצר ונשמר ב-``bot_data`` בעליית הבוט.
- ``drive_schedule_job_set`` — נוצר job של גיבוי מתוזמן למשתמש (``_ensure_schedule_job``): ``key`` התזמון, ``interval_s`` המרווח, ``first_s`` השניות עד ההרצה הראשונה ו-``planned_next`` מועד ההרצה.
- ``drive_schedule_job_persistent_fallback`` — יצירת ה-job ב-jobstore הקבוע נכשלה (``error``), והוא נוצר בזיכרון בלבד. job כזה לא שורד עלייה מחדש, ו-``drive_reschedule`` מחזיר אותו.
- ``drive_schedule_job_setup_failed`` — יצירת ה-job נכשלה (``key``, ``error``).
- ``drive_schedule_job_cancelled`` — המשתמש כיבה את התזמון בתפריט.
- ``drive_schedule_job_missing`` — למשתמש יש תזמון פעיל בהעדפות ואין לו job בזיכרון, וה-job נוצר מחדש (``ensure_schedule_job_if_missing``).
- ``drive_reschedule_jobs_run`` — סיכום הרצה של ``drive_reschedule`` ב-``main.py``, שמשחזר את ה-jobs של התזמונים הפעילים: ``scanned``, ‏``total`` (עם תזמון תקף), ‏``recreated``, ‏``skipped``.
- ``drive_reschedule_handler_restored`` — ה-handler חסר ב-``bot_data`` ושוחזר מהעותק שעל ה-application (``source``).
- ``drive_scheduled_backup_start`` — גיבוי מתוזמן התחיל.
- ``drive_scheduled_backup_result`` — תוצאת הגיבוי המתוזמן (``ok``), ברמת ``warn`` כשהוא נכשל.
- ``drive_scheduled_backup_auth_required`` — הגיבוי המתוזמן נכשל, ואי אפשר לבנות שירות Drive מהטוקנים השמורים; המשתמש קיבל בקשה להתחבר מחדש.
- ``drive_scheduled_backup_update_prefs`` — נשלח אחרי כל גיבוי מתוזמן, עם הזמנים שנשלחו לשמירה בהעדפות של הבוט (``next_at``, ``last_at``, ``last_full_at``). התוצאה של השמירה עצמה לא נבדקת שם, ולכן האירוע אינו ראיה שהזמנים נשמרו.
- ``drive_scheduled_backup_update_prefs_failed`` — חריגה בבלוק שמעדכן את הזמנים (``error``).
- ``drive_scheduled_backup_error`` — חריגה לא צפויה בהרצת הגיבוי המתוזמן (``error``); ה-traceback בלוג.

שגיאות מסד בחיבור ובהעדפות, של שני השירותים (``database/repository.py``):

- ``db_save_drive_tokens_error`` / ``db_get_drive_tokens_error`` / ``db_delete_drive_tokens_error`` / ``db_save_drive_prefs_error`` / ``db_get_drive_prefs_error`` — ``owner`` אומר של איזה שירות החיבור (``bot`` או ``webapp``).
- ``db_get_users_with_active_drive_schedule_error`` — שגיאת מסד בשליפת המשתמשים שיש להם תזמון פעיל. השליפה היא של התזמון של הבוט בלבד.

Repo Analyzer
-------------

- ``repo_analysis_start`` / ``repo_analysis_parsed`` / ``repo_analysis_done``
- ``repo_analysis_error`` — כשל בניתוח ריפו.

Business
--------

- ``business_metric`` — אירוע ביזנס כללי (למשל ``file_saved``/``search``/``github_sync``).

.. note::
   עדיף לציין מזהי משאבים עקביים (``resource:{type,id}``) ולשמור על ``msg_he`` קצר וברור.
