סקריפטים שימושיים
==================
:summary: תיקיית scripts/ מכילה כלים חד-פעמיים ותהליכי תחזוקה. לפני ההרצה ודאו שסביבת ה-DB היא סביבת ניסוי/פיתוח ושיש גיבוי עדכני.

תיקיית ``scripts/`` מכילה כלים חד-פעמיים ותהליכי תחזוקה. לפני ההרצה ודאו שסביבת ה-DB היא סביבת ניסוי/פיתוח ושיש גיבוי עדכני.

.. contents::
   :local:
   :depth: 2

``scripts/cleanup_repo_tags.py``
--------------------------------

- מנקה תגיות ``repo:*`` כפולות בקולקציית ``code_snippets`` וממזג אותן לתג בודד עדכני.
- אופציונלית: ``--clear-index`` מוחק את כל תגיות ה-``repo:*`` עבור קבצים בשם ``index.html`` (מונע רעש מהייצוא האוטומטי).
- מבצע backfill לשדות ``is_favorite`` ו-``favorited_at`` במסמכים שאין בהם ערך.

דוגמת הרצה::

   python scripts/cleanup_repo_tags.py --user-id 123456 --apply

משתני סביבה: ``MONGODB_URL`` (חובה), ``DATABASE_NAME`` (ברירת מחדל ``code_keeper_bot``).

``scripts/migrate_reminder_acked_status.py``
--------------------------------------------

- מיישר תזכורות פתקים שאושרו לפני שהמצב הסופי ``acked`` היה קיים: מסמך עם ``ack_at`` מלא שעדיין ב-``pending`` או ``snoozed`` מקבל ``status="acked"``. הכיוון היחיד הוא מ"אושר" ל"אושר", ולכן הרצה חוזרת בטוחה.
- כמו שאר סקריפטי המיגרציה: **בלי דגל הוא רק מדווח**; ``--apply`` כותב. הפלט מתחיל בשם מסד הנתונים שנפתר ובמספר המסמכים באוסף, כדי ש-``DATABASE_NAME`` שגוי ייראה לפני ההודעה "אין מה לעדכן".
- האימות אחרי הכתיבה סופר מחדש מהמסד, ורק מסמכים שאושרו לפני תחילת הריצה — אישור שנחת באמצע (למשל מפוד ישן בזמן דיפלוי) אינו כשל של הריצה הזו.

דוגמת הרצה::

   python scripts/migrate_reminder_acked_status.py           # דיווח בלבד
   python scripts/migrate_reminder_acked_status.py --apply   # כותב

``scripts/dev_seed.py``
-----------------------

- זורע סניפטים מתוך ``SNIPPETS.md`` אל ספריית הסניפטים (idempotent).
- בודק שה-DB מקומי כדי למנוע טעויות; ניתן לעקוף עם ``--force`` או ``ALLOW_SEED_NON_LOCAL=1``.
- משייך סניפטים למשתמש המוגדר בקובץ (user_id=0) ומסמן אותם כמאושרים.

דוגמת הרצה::

   # עבודה מול DB מקומי
   MONGODB_URL="mongodb://localhost:27017/code_keeper_bot" python scripts/dev_seed.py

scripts/import_snippets_from_markdown.py
----------------------------------------

- מייבא סניפטים מקובץ או URL (כולל GitHub/Gist) באמצעות ניתוח Markdown.
- ניתן לבצע ``--dry-run`` כדי לראות כמה סניפטים ייווצרו ללא כתיבה.
- ברירת המחדל מאשרת אוטומטית את הסניפטים החדשים; ניתן לבטל עם ``--no-approve``.

דוגמת הרצה::

   scripts/import_snippets_from_markdown.py --source docs/new-snippets.md --user-id 42 --username "Ops Bot"

``scripts/measure_md_parse_cost.py``
------------------------------------

- מודד כמה זיכרון מוסיף פרסור מסמך אחד לכל בית קלט — **שיא** ה-RSS בזמן הפרסור מעל הבסיס שלפניו (הגבוה מבין ה-RSS ושיא-העבר של התהליך, כדי שזיכרון שהייבוא כבר הגיע אליו ושחרר לא ייזקף לפרסור) — **לשני הפרסרים**: ``services.md_parser``, שעליו נמדד הקבוע ושכלי ה-Markdown של PR 5 יריץ, ו-``services.rst_parser``, שהכלי הציבורי ``codekeeper_docs_get_section`` מריץ היום. כל פרסור בתהליך נקי משלו, בשלוש צורות לכל פרסר: הקורפוס האמיתי של הריפו, המסמך הצפוף ביותר בו משוכפל עד ``MAX_FILE_SIZE_FOR_DISPLAY``, וצורה עוינת (Markdown: שורות-תבליט בודדות; RST: כותרת בת תו אחד בכל שורה). ל-RST נמדד גם מסלול ה-outline של ``codekeeper_get_repo_file`` — המסמך הצפוף ביותר משוכפל עד ``RANGE_READ_MAX_BYTES`` עם תקרת הסקשנים ``MAX_SYMBOLS`` — כי זו ההחזקה הגדולה ביותר של חוט קריאה היום.
- זה המקור של ``_PARSE_RSS_PER_INPUT_BYTE`` ב-``mcp_server/server.py``, שממנו נגזר רוחב מאגר הקריאות של ה-MCP. מריצים אותו מחדש כשמשנים את ``md_parser`` או את ``rst_parser`` (ובכלל זה החלפת גרסת ``markdown-it-py``), או כשנוסף מסמך צפוף במיוחד, ומעדכנים את הקבוע לפי "המסמך הצפוף ביותר שהכלי מגיש" — לא לפי הגבול העוין, שאותו הקבוע במפורש אינו מכסה.
- לא נוגע במסד ולא בריפו: הקבצים הזמניים נכתבים לתיקייה זמנית של המערכת. קובץ שאינו UTF-8 מדולג עם שורת ``skipped`` ב-stderr, ובלי אף קובץ בגודל ``MIN_DOC_BYTES`` ומעלה הסקריפט יוצא עם הודעה שאומרת זאת. הטסטים שלו: ``tests/test_measure_md_parse_cost_script.py``.

דוגמת הרצה::

   python scripts/measure_md_parse_cost.py

scripts/migrate_workspace_collections.py
----------------------------------------

- מייצר אוסף "שולחן עבודה" לכל משתמש שחסר לו אחד כזה (idempotent).
- נשען על ``CollectionsManager`` ומייבא ``get_db`` בזמן ריצה כדי למנוע תלות מעגלית.
- מדפיס סיכום בסיום (כמה משתמשים נבדקו וכמה אוספים נוצרו).

``scripts/run_log_aggregator.py``
---------------------------------

- מפעיל את ``monitoring.log_analyzer.LogEventAggregator`` על stdin ומנתח לוגים בזמן אמת.
- צורך קובצי חתימות וקונפיגורציית התראות: ``ERROR_SIGNATURES_PATH`` (ברירת מחדל ``config/error_signatures.yml``) ו-``ALERTS_GROUPING_CONFIG`` (ברירת מחדל ``config/alerts.yml``).
- תומך בטעינה מחודשת מחזורית של חתימות דרך ``LOG_AGG_RELOAD_SECONDS`` ובמצב debug שמדפיס התאמות עם ``LOG_AGG_ECHO=1``.

שימוש אופייני::

   tail -F logs/app.log | LOG_AGG_ECHO=1 python scripts/run_log_aggregator.py

``scripts/start_webapp.sh``
---------------------------

- מעטפת ל-Gunicorn עבור `webapp/` עם הפקת ``ASSET_VERSION`` אוטומטית והפעלת warmup best-effort ל-``/healthz``.
- מכבד ``PORT`` (ברירת מחדל 5000), ``WEBAPP_WSGI_APP`` ופרמטרי warmup (``WEBAPP_ENABLE_WARMUP`` / ``WEBAPP_WARMUP_URL`` / ``WEBAPP_WARMUP_MAX_ATTEMPTS`` / ``WEBAPP_WARMUP_DELAY_SECONDS``).
- ברירת המחדל היא worker יחיד עם ``gevent``; ניתן לשלוט ב-``WEB_CONCURRENCY``/``WEBAPP_GUNICORN_WORKERS``, ``WEBAPP_GUNICORN_WORKER_CLASS``, ``WEBAPP_GUNICORN_WORKER_CONNECTIONS`` (ל-``gevent``) ו-``WEBAPP_GUNICORN_THREADS`` (ל-``gthread``).
- משמש להפעלה מקומית או ב-Render/Heroku כאשר אין Supervisor חיצוני.

``scripts/start_with_worker.sh``
--------------------------------

- מפעיל את הבוט Python (``python main.py``) ובמידת הצורך גם Worker מבוסס Node לטיפול ב-Web Push.
- קורא קובץ ``.env.worker`` (לא מנוהל ב-git) כדי לטעון מפתחות VAPID פרטיים רק לתהליך ה-Worker.
- מגדיר ``PUSH_DELIVERY_URL`` מקומי אם ה-Worker רץ על אותה מכונה וממתין ל-healthcheck קצר כדי למנוע race conditions.

``scripts/run_all.sh``
----------------------

- מריץ **שני תהליכים באותו קונטיינר**: ה-WebApp (Gunicorn דרך ``scripts/start_webapp.sh``) וגם שירות ``AI Explain`` (AioHTTP דרך ``python -m services.webserver``).
- מגדיר ברירת מחדל ל-``OBS_AI_EXPLAIN_URL`` ל-``http://127.0.0.1:<internal_port>/api/ai/explain`` כאשר המשתנה לא הוגדר, כדי שהדשבורד יפנה פנימה.
- אמינות: אם אחד מהתהליכים נסגר/נופל, הסקריפט עוצר גם את השני ויוצא עם קוד שגיאה (כדי שהקונטיינר לא ימשיך “חצי עובד”).

משתני סביבה שימושיים:

- ``OBS_AI_EXPLAIN_INTERNAL_PORT`` (ברירת מחדל: ``11000``)
- ``OBS_AI_EXPLAIN_INTERNAL_HOST`` (ברירת מחדל: ``127.0.0.1``)
- ``OBS_AI_EXPLAIN_RUN_LOCAL_SERVICE`` (ברירת מחדל: ``true``)
- ``WEBAPP_START_SCRIPT`` (ברירת מחדל: ``scripts/start_webapp.sh``)
