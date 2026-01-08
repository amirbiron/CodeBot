Handlers
========

תיעוד של כל ה-handlers בפרויקט.

זרימת פקודה בסיסית
------------------

התרשים הבא מציג את הזרימה הכללית של פקודה מהמשתמש ועד לתגובה:

.. mermaid::

   graph LR
       A[User Command] --> B{Permission Check}
       B -->|Authorized| C[Validate Args]
       B -->|Denied| D[Error Response]
       C --> E[Metrics Collection]
       E --> F[Execute Command]
       F --> G[Format Response]
       G --> H[Send to User]
       F --> I[Log Metrics]
       I --> J{Alert Check}
       J -->|Threshold Exceeded| K[Trigger Alert]
       J -->|Normal| L[Store Metrics]

**שלבי הזרימה:**

1. **Permission Check**: בדיקת הרשאות המשתמש לפקודה
2. **Validate Args**: אימות הפרמטרים שהועברו
3. **Metrics Collection**: איסוף מטריקות לפני ביצוע
4. **Execute Command**: הרצת הפקודה בפועל
5. **Log Metrics**: רישום המטריקות לניטור
6. **Alert Check**: בדיקה האם יש לשלוח התראה

ארכיטקטורת Handlers
--------------------

התרשים הבא מציג את הקשר בין ה-Handlers השונים לשירותים:

.. mermaid::

   graph TB
       subgraph "Bot Interface"
           U[User Input] --> DP[Dispatcher]
       end

       subgraph "Command Handlers"
           DP --> SH[/status Handler]
           DP --> EH[/errors Handler]
           DP --> LH[/latency Handler]
           DP --> RH[/rate_limit Handler]
           DP --> TH[/triage Handler]
           DP --> DH[/dashboard Handler]
       end

       subgraph "Services Layer"
           SH --> HS[Health Service]
           EH --> MS[Metrics Service]
           LH --> MS
           RH --> GS[GitHub Service]
           TH --> IS[Investigation Service]
           DH --> AS[Aggregation Service]
       end

       subgraph "Data Layer"
           HS --> DB[(Database)]
           MS --> DB
           MS --> RC[(Redis)]
           GS --> GA[GitHub API]
           IS --> DB
           IS --> ES[Elastic/Logs]
           AS --> DB
       end

**הסבר השכבות:**

- **Bot Interface**: קבלת קלט מהמשתמש וניתוב לפקודה המתאימה
- **Command Handlers**: טיפול בפקודות ספציפיות (status, errors, latency וכו')
- **Services Layer**: שירותי הליבה שמבצעים את הלוגיקה העסקית
- **Data Layer**: שכבת הנתונים - DB, Cache, APIs חיצוניים

.. seealso::

   - ארכיטקטורה כללית: :doc:`/architecture`
   - Services: :doc:`/services/index`
   - Resilience: :doc:`/resilience`

Show Command
------------

.. toctree::
   :maxdepth: 1

   show

Drive Menu
----------

.. toctree::
   :maxdepth: 1

   drive_menu

File View Handler
-----------------

.. automodule:: handlers.file_view
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

Pagination Handler
------------------

.. automodule:: handlers.pagination
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

Save Flow Handler
-----------------

.. automodule:: handlers.save_flow
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

States Handler
--------------

.. automodule:: handlers.states
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

GitHub Handlers
---------------

החבילה ``handlers.github`` מרכזת את כל הפקודות, התפריטים ומסכי
השיתוף/העלאה מול GitHub. קובץ ``__init__.py`` מחזיק תיעוד והגדרות
משותפות (קבועים, Enums והפניות לאירועים), בעוד שהמודולים הפנימיים
מטפלים בכל שלב בזרימת המשתמש – החל משליחת תפריט הבחירה ועד העלאת ZIP
או ענף מלא. השתמשו בחבילה זו כשאתם צריכים להריץ Callback ספציפי
באופן ידני מתוך טסטים או בוטי תחזוקה.

.. automodule:: handlers.github
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

GitHub Menu Bridge
------------------

`handlers.github.menu` הוא שכבת תאימות דקה שמייצאת את
``GitHubMenuHandler`` מהמודול ההיסטורי ``github_menu_handler``. כך ניתן
לעדכן את הנתיבים בקוד החדש מבלי לשבור תלות קיימת בסקריפטים ו‑tests.
המודול דואג שקריאה מ-``handlers.github.menu`` או
``services.github_service.get_handler`` תחזיר את אותו Handler מרכזי
שמטפל בכל תפריטי ה-GitHub בבוט.

.. automodule:: handlers.github.menu
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex:

Document Flow
-------------

.. toctree::
   :maxdepth: 1

   document-flow

Drive Utilities
---------------

חבילת Google Drive עושה שימוש בעזרי תזמון שמנרמלים נתונים ישנים מול
מבנה ההעדפות החדש ב-UI. המודול ``handlers.drive.utils`` מספק פונקציה
יחידה, ``extract_schedule_key``, שמחלצת את מפתח התזמון (``schedule`` /
``schedule_key``) מתוך מילוני העדפות ורסטיליים. חשוב להשתמש בה לפני
שמחשבנים גיבוי אוטומטי כדי להימנע ממצב בו משתמש ותיק נשאר עם ערך ריק.

.. automodule:: handlers.drive.utils
   :members:
   :undoc-members:
   :show-inheritance:
   :noindex: