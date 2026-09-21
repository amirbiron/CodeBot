קטלוג אירועים קנוניים
======================
:summary: הקטלוג הקנוני של שמות האירועים — GitHub, שיתוף ווב, התראות, Repo Analyzer ואירועי ביזנס — עם הכלל לשמות ב-snake_case ובלי PII.

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

Repo Analyzer
-------------

- ``repo_analysis_start`` / ``repo_analysis_parsed`` / ``repo_analysis_done``
- ``repo_analysis_error`` — כשל בניתוח ריפו.

Business
--------

- ``business_metric`` — אירוע ביזנס כללי (למשל ``file_saved``/``search``/``github_sync``).

.. note::
   עדיף לציין מזהי משאבים עקביים (``resource:{type,id}``) ולשמור על ``msg_he`` קצר וברור.
