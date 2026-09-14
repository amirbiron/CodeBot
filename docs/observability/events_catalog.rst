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
- ``alert_telegram_below_min_severity`` — התראה לא נשלחה לטלגרם כי חומרתה נמוכה מ-``ALERT_TELEGRAM_MIN_SEVERITY``.
- ``alert_telegram_suppressed`` — התראה לא נשלחה לטלגרם כי שמה מופיע ב-``ALERT_TELEGRAM_SUPPRESS_ALERTS``.

Jobs
----

- ``job_started`` / ``job_completed`` / ``job_failed`` / ``job_skipped`` — מחזור החיים של הרצת Job.
- ``job_stuck`` — הרצה נשארה ב-``running`` מעבר לסף.
- ``job_missed`` — ל-Job מתוזמן לא נרשמה אף ריצה בחלון שהוגדר לו. משלים את
  השניים שמעליו, שמכסים רק הרצות שכבר התחילו. שני דיוקים חשובים: ריצה
  ש**נכשלה** נחשבת כריצה (כשל כבר מכוסה ב-``job_failed``, וכאן נבדקת
  אי-התחלה בלבד), ומה שנבדק הוא היעדר **רשומה** ב-``job_runs`` — כתיבה
  שנכשלה נרשמת ללוג ואינה מפילה את ההרצה, ולכן ריצה שקרתה ורשומתה לא
  נשמרה תיראה כאן כהיעדר.
- ``daily_report_sent`` — דוח הבוקר היומי נשלח.

.. code-block:: json

   {"event":"job_missed","severity":"error","job_id":"daily_morning_report","hours":26}

Repo Analyzer
-------------

- ``repo_analysis_start`` / ``repo_analysis_parsed`` / ``repo_analysis_done``
- ``repo_analysis_error`` — כשל בניתוח ריפו.

Business
--------

- ``business_metric`` — אירוע ביזנס כללי (למשל ``file_saved``/``search``/``github_sync``).

.. note::
   עדיף לציין מזהי משאבים עקביים (``resource:{type,id}``) ולשמור על ``msg_he`` קצר וברור.
