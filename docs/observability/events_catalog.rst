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

בדיקה ידנית:

- ``push_test_result`` / ``push_test_local_error`` / ``push_test_worker_error`` — תוצאות ``POST /api/push/test``.

Repo Analyzer
-------------

- ``repo_analysis_start`` / ``repo_analysis_parsed`` / ``repo_analysis_done``
- ``repo_analysis_error`` — כשל בניתוח ריפו.

Business
--------

- ``business_metric`` — אירוע ביזנס כללי (למשל ``file_saved``/``search``/``github_sync``).

.. note::
   עדיף לציין מזהי משאבים עקביים (``resource:{type,id}``) ולשמור על ``msg_he`` קצר וברור.
