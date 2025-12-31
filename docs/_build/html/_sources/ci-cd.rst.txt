CI/CD Guide
===========

חוקים קשיחים
-------------

- אין ``git clean/reset`` ב‑CI
- אין ``sudo``
- טסטים ירוצו בסביבות מבודדות; IO רק תחת ``/tmp``
- התיעוד נכשל על אזהרות (``fail_on_warning: true``)

סטטוסים נדרשים
---------------

- 🔍 Code Quality & Security
- Unit Tests (3.11)
- Unit Tests (3.12)

ריכוז CI (Overview)
--------------------

- **Code Quality & Security** – בדיקות סטטיות ואבטחה
- **Unit Tests (3.11/3.12)** – טסטי יחידה במטריצת גרסאות
- **Performance Tests** – טסטי ביצועים (ברירת מחדל: הכל; Draft + ``perf-light``: רק קלים). דוחות זמני ריצה נשמרים כארטיפקטים.

קישורים מהירים:

- Actions (Performance): ``https://github.com/<OWNER>/<REPO>/actions/workflows/performance-tests.yml``
- ריצת ה‑PR: בתגובות ה‑PR מתווסף קישור אוטומטי ל‑Run ול‑Artifact.

בדיקות מומלצות
---------------

.. code-block:: bash

   pytest
   pytest --cov=. --cov-report=html

בנייה של התיעוד
----------------

.. code-block:: bash

   cd docs
   sphinx-build -b html . _build/html -W --keep-going

קישורים
-------

- :doc:`testing`
- :doc:`architecture`
- :doc:`environment-variables`
