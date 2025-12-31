בדיקות ביצועים (Performance Tests)
===================================

מטרה
-----
להריץ בדיקות ביצועים בצורה בטוחה וגמישה: ברירת מחדל מריצים את כולן; ב‑PR Draft עם תווית מתאימה מריצים רק "קלים".

סימון טסטים
-----------

הגדר מרקרים ב‑pytest:

.. code-block:: ini

   [pytest]
   markers =
       performance: בדיקות ביצועים
       heavy: טסטים כבדים (מדולגים במצב "רק קלים")

דוגמאות סימון:

.. code-block:: python

   import pytest

   # קלים (ברירת מחדל לטסטי ביצועים)
   pytestmark = [pytest.mark.performance]

   # כבדים
   # pytestmark = [pytest.mark.performance, pytest.mark.heavy]

הרצה מקומית
------------

.. code-block:: bash

   # הכל (כולל כבדים שדורשים opt-in)
   RUN_PERF=1 pytest -q -m performance

   # רק קלים
   ONLY_LIGHT_PERF=1 pytest -q -m performance

הערות:

- חלק מהטסטים הכבדים מוגדרים כ־opt‑in באמצעות ``RUN_PERF=1`` כדי למנוע ריצות ארוכות/רגישות כברירת מחדל מקומית.
- ב‑CI ברירת המחדל של Job ה‑Performance מגדירה ``RUN_PERF=1`` כך שהכול ירוץ, ואילו במצב draft עם תווית ``perf-light`` ירוצו רק הקלים.

CI / GitHub Actions
-------------------

- ברירת מחדל: מריץ את כל ה‑performance.
- PR Draft עם תווית ``perf-light``: מריץ רק קלים (מגדיר ``ONLY_LIGHT_PERF=1``).
- זמני ריצה נשמרים כארטיפקטים: ``durations.json``, ``durations-summary.json``.

דוחות וזמני ריצה
-----------------

.. code-block:: bash

   pytest -m performance --durations=0 --json-report --json-report-file=durations.json
   cat durations.json | jq '.summary.durations' > durations-summary.json

טיפים
-----

- השתמשו ב‑``--durations=20`` כדי לזהות טסטים איטיים.
- סמנו ``heavy`` לטסטים ארוכים במיוחד, I/O כבד, או "מובילי זמן".
