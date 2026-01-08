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

תרשים ארכיטקטורה מפורט
-----------------------

התרשים הבא מציג את הארכיטקטורה המלאה של המערכת, כולל כל השכבות והקשרים ביניהן:

.. mermaid::

   graph TB
       subgraph "Telegram Interface"
           U[User] --> TB[Telegram Bot]
       end

       subgraph "Command Processing Layer"
           TB --> CR[Command Router]
           CR --> PH[Permission Handler]
           PH --> CH[Command Handlers]
       end

       subgraph "Core Services"
           CH --> MC[Metrics Collector]
           CH --> GH[GitHub API Handler]
           CH --> CD[Code Analyzer]
           MC --> MS[Metrics Storage]
           MC --> MA[Metrics Analyzer]
       end

       subgraph "Storage Layer"
           MS --> PG[(PostgreSQL)]
           MS --> RD[(Redis Cache)]
           CD --> FS[File System]
       end

       subgraph "Monitoring & Alerts"
           MA --> AM[Alert Manager]
           AM --> NS[Notification Service]
           MA --> PE[Prometheus Exporter]
           PE --> GD[Grafana Dashboards]
       end

       NS -->|Alert| TB

**הסבר השכבות:**

- **Telegram Interface**: ממשק המשתמש דרך הבוט
- **Command Processing Layer**: ניתוב פקודות, בדיקת הרשאות וטיפול בפקודות
- **Core Services**: שירותי הליבה - איסוף מטריקות, GitHub API, ניתוח קוד
- **Storage Layer**: שכבת האחסון - PostgreSQL, Redis Cache, File System
- **Monitoring & Alerts**: ניטור והתראות - Prometheus, Grafana, Alert Manager

.. seealso::

   - תיקיית handlers: :doc:`handlers/index`
   - תיקיית services: :doc:`services/index`
   - תיקיית database: :doc:`database/index`

מבנה תיקיות
-----------

:::

   handlers/        → Telegram handlers
   services/        → Business logic
   database/        → MongoDB models & manager
   webapp/          → Flask web app
   tests/           → Unit/Integration tests
   docs/            → Sphinx documentation

מקורות נוספים
--------------

.. toctree::
   :maxdepth: 1

   architecture/clean-architecture

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
- :doc:`handlers/document-flow`
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

הפרדת אחריות – DocumentHandler
--------------------------------
הטיפול במסמכים עבר למחלקה ייעודית: ``handlers/documents.py`` (``DocumentHandler``) המשמשת כ‑Facade למסלולי קבצים:

- GitHub: ``_handle_github_restore_zip_to_repo`` / ``_handle_github_create_repo_from_zip`` / העלאה ישירה
- ZIP: ``_handle_zip_import`` / ``_handle_zip_create`` (איסוף קבצים ל‑bundle)
- קבצים טקסטואליים: ``_handle_textual_file`` (נורמליזציה, זיהוי קידוד, שמירה)

תלויות מוזרקות לבנאי:

- ``notify_admins``
- ``log_user_activity``
- ``emit_event`` (Observability)
- ``errors_total`` (מונה שגיאות ל‑Prometheus)
- ``encodings_to_try`` (סט קידודים דינמי)

ראו גם: :doc:`handlers/document-flow` לפרטי זרימה, מצבי ``upload_mode`` ונקודות הרחבה.
