Troubleshooting Guide
=====================

שגיאות נפוצות
-------------

``ModuleNotFoundError: No module named 'telegram'``
  - התקן תלויות: ``pip install -r requirements.txt``

``ServerSelectionTimeoutError: No servers available``
  - בדוק שה‑MongoDB רץ
  - אמת את ``MONGODB_URL`` ב‑.env
  - אם Atlas – בדוק Network Access (IP Allowlist)

``Telegram API Error: Conflict: terminated by other getUpdates``
  - יש instance נוסף שרץ: ``pkill -f "python main.py"`` והמתן 30 שניות

``Message is not modified``
  - עטוף עריכה ב‑wrapper שמתעלם משגיאה זו בלבד

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
