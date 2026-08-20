What's New
==========
:summary: יומן השינויים של הבוט וה-WebApp לפי תאריך — מה נוסף, מה השתנה ומה תוקן בכל עדכון, עם קישורים ל-Issues הרלוונטיים.

2026-01-29
----------
- feat: תיוג פריטים ב"אוספים שלי" עם תגיות אימוג'י, עורך תגיות, סינון/מיון ובחירה מרובה.
- feat: נוספו endpoints ל־metadata ול־עדכון תגיות + אירועי observability.
- docs: עודכן ``user/my_collections`` עם תיאור תיוג, סינון וייצוא/ייבוא.

2025-12-11
----------
- docs: עמוד חדש ``webapp/theming_and_css`` כולל טבלת טוקנים, שכבות, בדיקות, דוגמאות קוד ותרשימי SVG עבור Classic ו‑High Contrast.
- docs: עודכן ``index.rst`` עם קטגוריה "Frontend > Theming" וקישורים מ-``development.rst`` ו-README.
- docs: נוספו קישורים הדדיים ל‑``css_refactor_plan.md`` (FEATURE_SUGGESTIONS + WebApp) ול‑``webapp_theme_palettes.md``.

2025-11-11
----------
- docs: עמוד חדש "web 🌐 ממשקי משתמשים" עם זרימות בוט, שדות חובה, חיווי מצב וממשק אדמין.
- docs: עדכון "webapp/snippet-library" לגרסה המשודרגת – איחוד Curated+DB, הגבלות דפדוף, Deferred Highlight, ושיפורי אדמין.
- docs: מדריך קצר לסוכני AI להפעלה דרך הבוט וה‑WebApp בשני הפיצ'רים.

2025-11-06
----------
- docs: WebApp Onboarding – דף חדש עם זרימה, קישורים ו‑JS לדגל `has_seen_welcome_modal`.
- docs: WebApp API Reference – נוספו `POST /api/welcome/ack` ו‑`POST /api/shared/save` כולל קלט/פלט ושגיאות.
- docs: Observability – דף "Tracing Hotspots" עם תרשימי Mermaid, טבלת כיסוי ודוגמאות `@traced`.
- docs: Log‑based Alerts – פרק "טקסונומיית שגיאות וחתימות", "תצוגה ב‑ChatOps" ו‑`classify_error()`.
- docs: Resilience – דף חדש למדיניות Retry + Circuit Breaker עם טבלת ENV ודוגמת שימוש.
- docs: Architecture – הופרדה אחריות למסמכים (`DocumentHandler`) + HOWTO חדש `handlers/document-flow`.
- docs: Runbooks – צ'קליסט Incident חדש.

קישורים ל‑Issues רלוונטיים: `#1198`, `#1239`.

2025-11-05
----------
- docs: הרחבת דף הבית – נוספו Bookmarks, Collections, Sticky Notes, Favorites, Reminders ל"סקירה כללית" ו"תכונות עיקריות", כולל הבהרה ש‑WebApp בלבד.
- docs: הרחבת `webapp/overview` – הוספת פירוט (CodeMirror, Markdown מתקדם, Bulk Actions, Status) וקישורי :doc: לעמודים רלוונטיים; תיקון קישורים מוחלטים למניעת אזהרות RTD.
- docs: עדכון `examples` – שימוש ב‑`create_application` ו‑`app.run_polling()` במקום API ישן.
- docs: תיקון `installation` – קישור ריפו ל‑`https://github.com/amirbiron/CodeBot.git`.
- docs: `quickstart` – קישור ל‑`webapp/overview` בסעיף "מה הלאה?".

2025-10-30
----------
- fix: תמיכה בגרירה לסידור פריטים באוספים במגע (נייד/טאבלט). גרירה מתבצעת מהידית ``⋮⋮`` והסדר נשמר אוטומטית. בדסקטופ אין שינוי.

2025-10-29
----------
- נוסף סשן ``aiohttp`` משותף דרך ``http_async.get_session`` + כיבוי אוטומטי ב‑atexit.
- תיעוד עודכן: Configuration (Async HTTP), Architecture (תשתית HTTP), Troubleshooting (לולאות asyncio), ו‑API Reference (``http_async``).

2025-10-15
----------
- נוספו עמודים: Caching, Indexing, Cursor Pagination, Static Checklist.
- הורחב WebApp API Reference עבור `/files`.
- נוספה טבלת ENV מרוכזת.
- הורחב Troubleshooting עם Gotchas.
- נוסף מדריך כותבי תיעוד.
- הוגדרה מדיניות עוגנים יציבים.
