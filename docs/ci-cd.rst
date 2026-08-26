CI/CD Guide
===========
:summary: מדריך ה-CI/CD: החוקים הקשיחים, הסטטוסים הנדרשים ב-PR, ריכוז ה-workflows, הבדיקות המומלצות ובניית התיעוד.

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
- **JS Tests (node)** – טסטי הצד-לקוח שב-``tests/*.test.js``. כל קובץ הוא סקריפט עצמאי שמריץ את עצמו ויוצא עם קוד שגיאה בכשל, בלי רץ טסטים חיצוני. ``repo-history.test.js`` מדולג במפורש: הוא כתוב בסגנון ``describe``/``it`` ואין בפרויקט רץ שמספק אותם. **אינו סטטוס נדרש** – הכשל מופיע ב-PR אך אינו חוסם מיזוג.
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
