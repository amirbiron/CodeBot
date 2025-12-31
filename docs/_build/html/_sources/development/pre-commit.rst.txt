Pre-commit Hooks
================

מטרה
-----
להבטיח איכות קוד עקבית לפני קומיט/PR.

התקנה והרצה
------------

.. code-block:: bash

   pip install -r requirements/development.txt
   pre-commit install
   pre-commit run --all-files

Hooks פעילים (עיקריים)
-----------------------
- Black, isort, Flake8, MyPy, Bandit

טיפים לפתרון בעיות
-------------------
- הריצו את ``pre-commit run --all-files`` פעם אחת אחרי ההתקנה.
- אם hook שינה קבצים – בצעו add+commit מחדש.
- לפעמים נדרש ``pip install -U pip`` כדי לפתור תלות ישנה.
