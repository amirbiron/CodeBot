Quickstart לתרומה
=================

מטרה
-----
דף קצר שמאפשר להתחיל לתרום במהירות ובבטחה.

צעדי הכנה
---------

.. code-block:: bash

   git clone https://github.com/amirbiron/CodeBot.git
   cd CodeBot
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements/production.txt

סביבת פיתוח
------------

- צרו ``.env`` מקובץ דוגמה והשלימו שדות בסיסיים:

.. code-block:: bash

   cp .env.example .env
   # הוסיפו לפחות:
   # BOT_TOKEN, MONGODB_URL

הרצת טסטים
-----------

.. code-block:: bash

   export DISABLE_ACTIVITY_REPORTER=1
   export DISABLE_DB=1
   export BOT_TOKEN=x
   export MONGODB_URL='mongodb://localhost:27017/test'

   pytest -q

על ה‑Stubs
----------

- בקובץ ``tests/_telegram_stubs.py`` יש סטאבים ל‑``python-telegram-bot`` כדי להריץ טסטים מהר ובמבודד.
- הסטאבים נטענים אוטומטית דרך ``tests/conftest.py``.

קישורים
-------

- :doc:`index`
- :doc:`testing`
- :doc:`contributing`
