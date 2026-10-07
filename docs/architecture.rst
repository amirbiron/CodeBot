ארכיטקטורה
===========
:summary: המערכת מורכבת מבוט Telegram, שכבת שירותים (services), שכבת נתונים (MongoDB) ואפליקציית Web. הזרימה העיקרית: Handlers → Services → Database. בעמוד גם תשתיות משותפות: סשן ה-HTTP, וה-CSS של ה-WebApp ומחלקות Bootstrap.

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

.. _webapp-css-no-bootstrap:

תשתית CSS ב-WebApp – בלי Bootstrap
------------------------------------

ה-WebApp לא טוען את Bootstrap — לא את ה-CSS שלו ולא את ה-JS שלו. כל קובץ CSS וכל ספרייה חיצונית שנטענים בכל עמוד רשומים ב-`webapp/templates/base.html <https://github.com/amirbiron/CodeBot/blob/main/webapp/templates/base.html>`__, ו-Bootstrap לא ביניהם. הדבר היחיד מבית Bootstrap שנטען הוא Bootstrap Icons, שהיא ספריית אייקונים בלבד, בלי מחלקות העיצוב של Bootstrap. היא נטענת רק בדפים של דפדפן הריפו, דרך `webapp/templates/repo/base_repo.html <https://github.com/amirbiron/CodeBot/blob/main/webapp/templates/repo/base_repo.html>`__.

ובכל זאת, בתבניות יש מחלקות ומאפיינים בשמות של Bootstrap 5, כמו ``me-2`` או ``data-bs-toggle``. מחלקה כזו עובדת רק אם ה-CSS של האפליקציה מגדיר אותה בעצמו. אם לא — היא לא עושה כלום, גם אם בקריאת התבנית נראה שהיא אמורה לעבוד.

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - מחלקה
     - הייעוד שלה ב-Bootstrap
     - מה קורה ב-CodeBot
   * - ``d-none``
     - הסתרה (``display: none``)
     - **לא מוגדרת.** האלמנט נשאר גלוי, וגם הוספה או הסרה שלה מ-JS לא משנות את מה שרואים.
   * - ``row``, ``col-*`` (למשל ``col-md-5``)
     - עמודות של גריד
     - **לא מוגדרות,** ו-div-ים שמסומנים בהן נערמים זה מתחת לזה, כמו בלי מחלקה בכלל. חריג: ``global_search.css`` מעצב כמה מחלקות ``col-*``, אבל רק בתוך ``.search-and-filters``.
   * - ``d-flex``, ``justify-content-*``, ``align-items-*``, ``gap-*``
     - flex ויישור
     - **לא מוגדרות.**
   * - מחלקות הריווח, למשל ``mb-3``, ``me-2``, ``py-4``
     - ריווח (margin ו-padding)
     - **לא מוגדרות.**
   * - ``text-muted``, ``text-center``, ``text-danger``, וצבעי הרקע ``bg-primary``, ``bg-success`` וכו'
     - צבע ויישור של טקסט, צבע רקע
     - **לא מוגדרות.**
   * - ``btn``, ``btn-primary``, ``btn-secondary``, ``badge``, ``alert``, ``container``
     - רכיבים ופריסה
     - **מוגדרות באפליקציה,** בבלוק ה-``<style>`` של ``base.html``, בעיצוב של האפליקציה ולא של Bootstrap. אבל לא כל מחלקת ``btn-*`` של Bootstrap: למשל ``btn-outline-primary``, ``btn-warning`` ו-``btn-light`` לא מוגדרות בשום מקום.
   * - ``modal``, ``fade``, ``show``, ``modal-dialog``, ``data-bs-toggle="modal"``, ``data-bs-dismiss="modal"``
     - חלון מודאל (CSS ו-JS)
     - **עובד דרך תחליף.** ה-CSS של ``.modal`` יושב ב-``smooth-scroll.css`` (ראו :doc:`webapp/smooth-scrolling`), וה-JS בפונקציה ``bootstrapModalPolyfill`` שב-``base.html``. היא מגדירה ``window.bootstrap.Modal`` מצומצם — ``show``, ``hide`` ו-``getInstance`` — ומטפלת בלחיצות על ``data-bs-toggle="modal"`` ועל ``data-bs-dismiss="modal"``. שאר ה-API של המודאל של Bootstrap לא קיים.

**כללים מעשיים כשעורכים תבנית:**

- **כדי להסתיר אלמנט:** המאפיין ``hidden`` (או ``el.hidden = true`` ב-JS), או ``el.style.display = 'none'`` — ולא ``d-none``. שימו לב ש-``hidden`` מפסיד לכל ``display`` שה-CSS של האלמנט קובע, ולכן לרכיב כזה צריך כלל ``[hidden]`` משלו. ההסבר המלא בהערה שבראש `webapp/static/css/note-boards.css <https://github.com/amirbiron/CodeBot/blob/main/webapp/static/css/note-boards.css>`__.
- **כדי לסדר בעמודות או ב-flex:** כלל CSS של הדף או של הרכיב, כמו ``.paste-input-grid`` ב-``compare_paste.html`` או ``.file-selection-grid`` ב-``compare_files.html`` — ולא ``row``, ``col-*`` או ``d-flex``.
- **לפני שמשתמשים במחלקה בשם של Bootstrap:** ``grep`` על השם ב-``webapp/static/css/``, ב-``base.html`` וב-CSS של הדף עצמו. לא מצאתם הגדרה — המחלקה לא עושה כלום. זה נכון גם כשתבנית קיימת כבר משתמשת בה, ולכן אל תעתיקו ממנה כדוגמה.
- **אייקונים:** Font Awesome (``fas fa-*``) נטען ב-``base.html``, ולכן זמין בכל עמוד שיורש ממנו. Bootstrap Icons (``bi bi-*``) זמין רק בדפים של דפדפן הריפו.
- כל שינוי CSS ב-WebApp עובר גם דרך :doc:`webapp/theming_and_css`.

הייעוד של המחלקות בטבלה הוא לפי Bootstrap 5.3: `scss/_utilities.scss <https://github.com/twbs/bootstrap/blob/v5.3.3/scss/_utilities.scss>`__ (מחלקות העזר), `Grid <https://getbootstrap.com/docs/5.3/layout/grid/>`__ ו-`Modal <https://getbootstrap.com/docs/5.3/components/modal/>`__. השמות ``me-*`` ו-``data-bs-*`` הם של Bootstrap 5, לפי `מדריך המעבר ל-v5 <https://getbootstrap.com/docs/5.0/migration/>`__.

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
