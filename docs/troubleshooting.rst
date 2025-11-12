Troubleshooting Guide
=====================

שגיאות נפוצות
--------------

``ModuleNotFoundError: No module named 'telegram'``
  - התקן תלויות: ``pip install -r requirements/production.txt``

``ServerSelectionTimeoutError: No servers available``
  - בדוק שה‑MongoDB רץ
  - אמת את ``MONGODB_URL`` ב‑.env
  - אם Atlas – בדוק Network Access (IP Allowlist)

``Telegram API Error: Conflict: terminated by other getUpdates``
  - יש instance נוסף שרץ: ``pkill -f "python main.py"`` והמתן 30 שניות

``Message is not modified``
  - עטוף עריכה ב‑wrapper שמתעלם משגיאה זו בלבד

ImportError בזמן טסטים (telegram / ConversationHandler / filters)
-----------------------------------------------------------------

- ודאו שה‑stubs נטענים אוטומטית דרך ``tests/conftest.py``:

.. code-block:: python

   import tests._telegram_stubs  # noqa

שגיאות parse_mode
------------------

- שמרו אחידות: העדיפו ``ParseMode=HTML`` עבור הודעות מעוצבות, והימנעו מערבוב עם Markdown באותן הודעות.

``ETag לא מתעדכן / תמיד 200``
  - ודא שה‑``ETag`` מחושב על גרסת התוכן בלבד (לא על שדות משתנים)
  - צירוף ``ETag`` ו‑``Last-Modified`` גם בתשובת ``200`` וגם ב‑``304``
  - ראו :doc:`/webapp/caching`

שגיאות asyncio: "attached to a different loop" / "Event loop is closed"
--------------------------------------------------------------------------------

- מקור נפוץ: סשן aiohttp משותף שנוצר בלולאה אחת ומשתמשים בו אחרי שהלולאה נסגרה או הוחלפה (בטסטים/ריסטארט חם).
- פתרון מהיר: סגרו את הסשן וקבלו חדש לפני השימוש הבא::

   import http_async
   await http_async.close_session()
   session = http_async.get_session()

- בפרויקט קיימים שני פיקסצ'רים אוטומטיים ב-``conftest.py`` שמבצעים את הסגירה הזו עבורך:
  - ``_reset_http_async_session_between_tests`` – מריץ ``await close_session()`` לפני ואחרי כל טסט אסינכרוני.
  - ``_ensure_http_async_session_closed_for_sync_tests`` – עוטף טסטים סינכרוניים שמריצים ``asyncio.run`` ודואג לקרוא ל-``close_session()`` גם שם (כולל יצירת event loop זמני לפי הצורך).
  ודא שהפיקסצ'רים נשארים פעילים (אל תעקוף אותם עם ``usefixtures`` ידני).
- טסטים שמייצרים ``CodeImageGenerator`` לשימוש ב-Playwright/WeasyPrint חייבים לקרוא ``gen.cleanup()`` בסוף כדי לעצור את ה-Runner הפנימי; אחרת תראה את אותה שגיאה של ``Runner.run()``.

``Timezone naive/aware גורם להשוואות שגויות``
  - ודא ש‑``created_at`` ו‑``updated_at`` הם timezone-aware ב‑UTC
  - השוו שניות שלמות (ללא microseconds) מול ``If-Modified-Since``

``שאילתא איטית / COLLSCAN``
  - חסר אינדקס מתאים. בדוק :doc:`/database/indexing` והוסף אינדקס מרוכב
  - אמת ב‑``explain('executionStats')`` שהשלב הוא ``IXSCAN`` ולא ``COLLSCAN``

``דפדוף מדלג/כפול פריטים``
  - ודא מיון יציב לפי ``created_at`` ו‑``_id`` יחד
  - השתמשו בתבנית הקורסור מ‑:doc:`/database/cursor-pagination`

``SRI mismatch בטעינת משאב מ‑CDN``
  - חשבו hash מחדש עם ``openssl dgst -sha384 -binary | base64``
  - עדכנו את ערך ``integrity=...`` וודאו ``crossorigin="anonymous"``
  - ראו :doc:`/webapp/static-checklist`

דיבוג מהיר
----------

.. code-block:: bash

   LOG_LEVEL=DEBUG python main.py

בדיקת חיבור MongoDB
--------------------

.. code-block:: python

   from database.manager import DatabaseManager
   db = DatabaseManager()
   print('Connected!' if db.test_connection() else 'Failed')

קישורים
-------

- :doc:`ci-cd`
- :doc:`testing`
