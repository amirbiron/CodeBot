סקריפטים שימושיים
==================

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
- משמש להפעלה מקומית או ב-Render/Heroku כאשר אין Supervisor חיצוני.

``scripts/start_with_worker.sh``
--------------------------------

- מפעיל את הבוט Python (``python main.py``) ובמידת הצורך גם Worker מבוסס Node לטיפול ב-Web Push.
- קורא קובץ ``.env.worker`` (לא מנוהל ב-git) כדי לטעון מפתחות VAPID פרטיים רק לתהליך ה-Worker.
- מגדיר ``PUSH_DELIVERY_URL`` מקומי אם ה-Worker רץ על אותה מכונה וממתין ל-healthcheck קצר כדי למנוע race conditions.
