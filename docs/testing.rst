Testing Guide
=============

🚀 Quickstart לטסטים
--------------------

1. הגדרת משתני סביבה (בזמן הרצה):

.. code-block:: bash

   export DISABLE_ACTIVITY_REPORTER=1
   export DISABLE_DB=1
   export BOT_TOKEN=x
   export MONGODB_URL='mongodb://localhost:27017/test'

2. התקנת תלויות טסטים וכיסוי:

.. code-block:: bash

   pip install -U pytest pytest-asyncio pytest-cov

3. הרצות שימושיות:

.. code-block:: bash

   # כל הטסטים במצב שקט
   pytest -q

   # בדיקת קובץ/טסט ספציפי
   pytest tests/test_bot_handlers_show_command_more.py::test_show_command_renders_html_and_escapes_code_and_buttons_id -q

הנחיות קריטיות
---------------

- כל IO בטסטים יתבצע תחת ``tmp_path`` בלבד.
- מחיקות יתבצעו רק תחת ``/tmp`` באמצעות wrapper בטוח.
- מבודדים את תלות ``python-telegram-bot`` באמצעות Stubs כדי להימנע מקריאות אמתיות.

טעינת Stubs לטלגרם
-------------------

כדי להריץ טסטים ללא ``python-telegram-bot``, קיימים stubs ב-``tests/_telegram_stubs.py`` והם נטענים אוטומטית דרך ``tests/conftest.py``:

.. code-block:: python

   # tests/conftest.py
   import os
   os.environ.setdefault('DISABLE_ACTIVITY_REPORTER', '1')
   os.environ.setdefault('DISABLE_DB', '1')
   os.environ.setdefault('BOT_TOKEN', 'x')
   os.environ.setdefault('MONGODB_URL', 'mongodb://localhost:27017/test')
   import tests._telegram_stubs  # noqa

דוגמת שימוש ב‑tmp_path
----------------------

.. code-block:: python

   def test_file_operations(tmp_path):
       test_file = tmp_path / "test.py"
       test_file.write_text("print('hello')")
       assert test_file.exists()

מחיקה בטוחה
------------

.. code-block:: python

   from pathlib import Path
   import shutil

   def safe_rmtree(path: Path, allow_under: Path) -> None:
       p = path.resolve()
       base = allow_under.resolve()
       if not str(p).startswith(str(base)) or p in (Path('/'), base.parent, Path.cwd()):
           raise RuntimeError(f"Refusing to delete unsafe path: {p}")
       shutil.rmtree(p)

רישום Blueprint בסביבת טסטים
------------------------------

במהלך הרצת בדיקות (pytest), האפליקציה מבטיחה שרישום ה‑Blueprint של ``collections_api`` יבוצע תמיד — גם אם הייבוא נכשל או אם הקובץ ``config`` חסר.

מה קורה בפועל:

- אם המודול נטען בהצלחה: ה‑Blueprint נרשם כרגיל תחת ``/api/collections`` באמצעות ``collections_bp`` (או ``bp``).
- אם הייבוא נכשל או אין ``bp``: נרשם Blueprint דיאגנוסטי שמונע שגיאות 404 ומחזיר JSON עם סטטוס 503, למשל::

    {"ok": false, "error": "collections_api_unavailable", "diagnostic": true}

- בפרודקשן: ההתנהגות לא משתנה — חריגים נרשמים ללוג בלבד, ואין Blueprint דמה.

דוגמה לקוד שמבטיח רישום בסביבת pytest (חלק מ‑``webapp/app.py``):

.. code-block:: python

   import os, sys
   _is_pytest = (
       bool(os.getenv("PYTEST_CURRENT_TEST"))
       or ("pytest" in sys.modules)
       or os.getenv("PYTEST") == "1"
       or os.getenv("PYTEST_RUNNING") == "1"
   )
   if _is_pytest:
       enabled = True  # הפיצ'ר נכפה ל-True בזמן טסטים


כיסוי בדיקות (pytest-cov)
--------------------------

- הפרויקט מגדיר ``pytest-cov`` ב-``pytest.ini``. אם חסר, התקינו: ``pip install pytest-cov``.
- דוחות:

.. code-block:: bash

   pytest --cov=. --cov-report=term-missing --cov-report=xml

CI נתמך
-------

- ה‑PR חייב לעבור סטטוסים: "🔍 Code Quality & Security", "🧪 Unit Tests (3.11)", "🧪 Unit Tests (3.12)".

בדיקות ביצועים (Performance)
-----------------------------

- מרקרים:

  .. code-block:: ini

     [pytest]
     markers =
         performance: בדיקות ביצועים
         heavy: טסטים כבדים (מדולגים כשמבקשים רק קלים)

- הרצות מקומיות:

  .. code-block:: bash

     # הכל
     pytest -q -m performance

     # רק קלים
     ONLY_LIGHT_PERF=1 pytest -q -m performance

- CI:
  - ברירת מחדל מריץ הכל.
  - PR Draft + תווית ``perf-light`` מריץ רק קלים.
  - זמני ריצה נשמרים כארטיפקטים: ``durations.json``, ``durations-summary.json``.

- דוחות/מדידות:

  .. code-block:: bash

     pytest -m performance --durations=0 --json-report --json-report-file=durations.json
     cat durations.json | jq '.summary.durations' > durations-summary.json

קישורים
-------

- :doc:`ci-cd`
- :doc:`ai-guidelines`
