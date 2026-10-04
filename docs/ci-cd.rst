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
- Unit Tests md-heavy (3.11)
- Unit Tests md-heavy (3.12)

שמות הסטטוסים של ``Unit Tests`` נבנים מהמטריצה של הג'וב ``unit-tests`` ב-``.github/workflows/ci.yml`` (``label`` ו-``python-version``). אותם שמות כתובים גם ב-``.github/pull_request_template.md``, ב-``.github/CONTRIBUTING.md`` וב-``.github/agents/my-agent.agent.md``, ו-``tests/test_required_checks_are_listed.py`` משווה את כל הרשימות האלה, וגם את הרשימה כאן, למטריצה.

**סטטוס חדש אינו חוסם מיזוג עד שמסמנים אותו כבדיקת חובה** בכלל שמגן על ``main`` בהגדרות של GitHub (Require status checks to pass before merging). GitHub מציע לבחירה רק בדיקה שעברה בהצלחה בריפו בשבעת הימים האחרונים (GitHub Docs, "Troubleshooting required status checks"), ולכן מסמנים אותה אחרי שה-CI של ה-PR שהוסיף אותה עבר.

ריכוז CI (Overview)
--------------------

- **Code Quality & Security** – בדיקות סטטיות ואבטחה
- **Unit Tests (3.11/3.12)** ו-**Unit Tests md-heavy (3.11/3.12)** – טסטי היחידה, בשני מסלולים לכל גרסת פייתון שרצים במקביל. ``Unit Tests`` מריץ את כל הטסטים חוץ מאלה שמסומנים ``md_heavy``, ו-``Unit Tests md-heavy`` מריץ רק אותם: טסטי פרסר ה-Markdown הכבדים (ראו :doc:`testing`). כל מסלול מדווח סטטוס חובה משלו, והמסלול ``md-heavy`` אינו מרים את MongoDB ואת Redis (``services`` של ``unit-tests``).
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
