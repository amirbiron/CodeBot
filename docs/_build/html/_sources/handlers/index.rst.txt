Handlers
========

תיעוד של כל ה-handlers בפרויקט.

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