What's New
==========

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
