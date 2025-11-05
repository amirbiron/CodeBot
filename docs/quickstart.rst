התחלה מהירה - מפתחים
======================

מטרה
-----
שלושה צעדים כדי להריץ מקומית במהירות.

שלב 1: התקנה
--------------

.. code-block:: bash

   git clone https://github.com/amirbiron/CodeBot.git
   cd CodeBot
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements/production.txt

שלב 2: הגדרת .env
------------------

.. code-block:: bash

   cp .env.example .env
   # ערוך והוסף:
   # - BOT_TOKEN (מ‑BotFather)
   # - MONGODB_URL (מקומי או Atlas)

שלב 3: הרצה
------------

.. code-block:: bash

   # הרצת הבוט
   python main.py

   # אופציונלי: הרצת ה‑WebApp בחלון נפרד
   cd webapp && python app.py

מה הלאה?
---------

- :doc:`architecture` – להבין את המערכת
- :doc:`environment-variables` – משתני סביבה
- :doc:`api/index` – תיעוד API
- :doc:`contributing` – איך לתרום
- :doc:`webapp/overview` – אפליקציית Web (אופציונלי)
