# V_NOTES – נקודות מפתח וצעדים להמשך

## מצב נוכחי
- RTD (latest): ירוק; Sphinx נקי ללא אזהרות כפולות; `fail_on_warning: true`.
- `docs/conf.py`: עודכן `autodoc_mock_imports` (cairosvg, aiohttp, textstat, langdetect, pytest, search_engine, code_processor, integrations).
- כפילויות Sphinx: מסומנות עם `:noindex:` בעמודי סקירה (api, database, handlers, services, configuration). `examples.rst` מוחרג עד שיוחזר ל־toctree.
- CI: סטטוסים נדרשים תואמים בדיוק –
  - "🔍 Code Quality & Security"
  - "🧪 Unit Tests (3.11)"
  - "🧪 Unit Tests (3.12)"
- CI רץ גם על שינויי `.cursorrules` (הוסר paths-ignore).

## תיקונים שבוצעו
- Telegram: עטיפות בטוחות ל־`edit_message_*` למניעת "Message is not modified".
- GitHub "📥 הורד קובץ מריפו": הוסר UI של מחיקה במצב הורדה בלבד.

## הנחיות/כללים (תמצית)
- Sphinx/RTD: לא להריץ קוד בטופ־לבל ב־imports; להשתמש ב־`:noindex:` כשיש כפילות.
- `.cursorrules`: לשמור כללי בטיחות מחיקה; לא להתעלם מהקובץ ב־CI.
- Telegram: להשתמש ב־`TelegramUtils.safe_edit_message_text/reply_markup` לכל עריכת הודעה.
- "📥 הורד קובץ מריפו": `browse_action=download`; לא להציג מחיקה; איפוס `multi_mode/safe_delete`.

## צעדים הבאים (Roadmap קצר)
- להחיל את ה־wrapper גם ב־`github_menu_handler.py`, `handlers/drive/menu.py`, `large_files_handler.py`.
- להשתמש גם ב־`safe_edit_message_reply_markup` היכן שרק המקלדת משתנה.
- להשיב `docs/examples.rst` ל־toctree ולהסיר מה־exclude כשמוכנים.
- להוסיף pre-commit (ruff/black/isort/doc8) ולציין ב־README.

## פקודות שימושיות
- Build תיעוד מקומי: `make -C docs html` (או `sphinx-build -b html docs docs/_build/html`).
- בדיקות: `pytest -v` (CI מריץ 3.11/3.12).
- עדכון ענף PR: "Update branch" או `git merge origin/main` → push.

## קישורים מהירים
- Required checks: Settings → Branches → Branch protection → Required status checks.
- RTD Builds: project "codebot" → Builds (לוגים).