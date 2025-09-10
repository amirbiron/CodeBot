מדריך למפתחים – נקודות מפתח
=============================

מצב נוכחי
----------
- RTD (latest) ירוק; Sphinx ללא אזהרות כפולות (fail_on_warning: true).
- docs/conf.py מעודכן עם autodoc_mock_imports (cairosvg, aiohttp, textstat, langdetect, pytest, search_engine, code_processor, integrations).
- כפילויות מסומנות עם :noindex: בעמודי סקירה (api, database, handlers, services, configuration).
- examples.rst מוחרג עד שיוחזר ל-toctree.
- CI: סטטוסים נדרשים: "🔍 Code Quality & Security", "🧪 Unit Tests (3.11)", "🧪 Unit Tests (3.12)".
- CI רץ גם על שינויי .cursorrules.

תיקונים שבוצעו
---------------
- Telegram: עטיפות בטוחות ל-edit_message_* כדי להתעלם מ-"Message is not modified".
- GitHub – "📥 הורד קובץ מריפו": הוסר UI של מחיקה במצב הורדה בלבד.

הנחיות פיתוח
------------
- Sphinx/RTD: לא להריץ קוד בטופ-לבל ב-imports; להשתמש ב-:noindex: כשיש כפילות.
- .cursorrules: לשמור כללי בטיחות מחיקה; לא להתעלם ממנו ב-CI.
- Telegram: להשתמש ב-TelegramUtils.safe_edit_message_text / safe_edit_message_reply_markup לכל עריכת הודעה.
- "📥 הורד קובץ מריפו": browse_action=download; לא להציג מחיקה; איפוס multi_mode/safe_delete.

Roadmap קצר
-----------
- להחיל wrapper גם ב-github_menu_handler.py, handlers/drive/menu.py, large_files_handler.py.
- להשתמש גם ב-safe_edit_message_reply_markup במקומות מתאימים.
- להחזיר examples.rst ל-toctree ולהסיר מה-exclude כשמוכנים.
- להוסיף pre-commit (ruff/black/isort/doc8) ולציין ב-README.

פקודות שימושיות
----------------
- Build תיעוד: ``make -C docs html`` או ``sphinx-build -b html docs docs/_build/html``
- בדיקות: ``pytest -v`` (CI מריץ 3.11/3.12)
- עדכון ענף PR: "Update branch" או ``git merge origin/main`` ואז push