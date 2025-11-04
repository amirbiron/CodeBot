ארכיטקטורה
===========

סקירה כללית
------------

המערכת מורכבת מבוט Telegram, שכבת שירותים (services), שכבת נתונים (MongoDB) ואפליקציית Web.
הזרימה העיקרית: Handlers → Services → Database.

תרשים רכיבים (תמציתי)
----------------------

.. mermaid::

   graph TD
     A[Telegram Bot] --> B[Handlers]
     B --> C[Services]
     C --> D[(MongoDB)]
     C --> E[GitHub API]
     C --> F[Google Drive API]
     A --> G[WebApp]
     G --> D

מבנה תיקיות
-----------

::

   handlers/        → Telegram handlers
   services/        → Business logic
   database/        → MongoDB models & manager
   webapp/          → Flask web app
   tests/           → Unit/Integration tests
   docs/            → Sphinx documentation

זרימות מרכזיות
---------------

שמירת קובץ (תמצית):

.. mermaid::

   sequenceDiagram
     participant U as User
     participant B as Bot
     participant H as Handler
     participant S as Service
     participant DB as MongoDB
     U->>B: /save file.py
     B->>H: save_command()
     H->>U: "שלח את הקוד"
     U->>H: code content
     H->>S: process_code(code)
     S->>DB: save_snippet()
     DB-->>S: {id}
     S-->>H: success
     H-->>U: "נשמר בהצלחה"

קישורים
-------

- :doc:`webapp/overview`
- :doc:`database/index`
- :doc:`api/index`
- :doc:`ai-guidelines`

תשתית HTTP – סשן aiohttp משותף
--------------------------------

- בכל הרכיבים הא-סינכרוניים (בוט/שירותים) נעשה שימוש ב‑``aiohttp.ClientSession`` משותף דרך ``http_async.get_session()``.
- פרמטרים נשלטים דרך ENV: ``AIOHTTP_TIMEOUT_TOTAL``, ``AIOHTTP_POOL_LIMIT``, ``AIOHTTP_LIMIT_PER_HOST``.
- כיבוי מתבצע אוטומטית ב‑atexit; ניתן לסגור ידנית עם ``await http_async.close_session()`` ב‑teardown.
- לולאת asyncio: בפרודקשן יש לולאה יחידה. בטסטים/ריסטארט חם, אם נוצרת לולאה חדשה ונתקלתם ב‑“attached to a different loop”, סגרו את הסשן ואז קבלו חדש.
- הנחיה: אל תפתחו ``ClientSession`` ישירות בקוד היישום; השתמשו רק ב‑``http_async.get_session()``.
