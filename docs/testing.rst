Testing Guide
=============
:summary: Quickstart להרצת טסטים, ההנחיות הקריטיות, טעינת ה-stubs לטלגרם, עבודה עם tmp_path ומתכון מחיקה מוגבל ל-allowlist, ו-mocking של HTTP.

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
       if not (p == base or base in p.parents) or p in (Path('/'), base.parent, Path.cwd()):
           raise RuntimeError(f"Refusing to delete unsafe path: {p}")
       shutil.rmtree(p)

Mocking HTTP ב‑github_menu_handler
----------------------------------

בגלל שינוי התשתית ל‑HTTP במודול ``github_menu_handler`` הוגדר שכבת shim יציבה לטסטים:

- ``gh.requests.get`` – ממשק GET שניתן לבצע עליו monkeypatch בקלות.
- ``gh.http_request`` – שכבת עטיפה לכל הבקשות; ב‑GET היא קוראת ל‑``gh.requests.get`` וב‑non‑GET קוראת ישירות ל‑``gh._http_sync_request``.

הנחיות מעשיות:

- עבור הורדות/GET (למשל zipball): עדיף לבצע monkeypatch על ``gh.requests.get`` במקום על ``requests.get`` הגלובלי.
- עבור קריאות non‑GET (POST/PUT/DELETE): בצעו monkeypatch על ``gh._http_sync_request``.
- אין יציאה לרשת בזמן טסטים – תמיד למקבש (monkeypatch) את הקריאות.

דוגמה – Mock ל‑GET דרך ה‑shim:

.. code-block:: python

   import github_menu_handler as gh

   def test_zip_download(monkeypatch):
       class _Resp:
           headers = {"Content-Length": "10"}
           def raise_for_status(self):
               pass
           def iter_content(self, chunk_size=131072):
               yield b"1234567890"

       def fake_get(url, **kwargs):
           return _Resp()

       monkeypatch.setattr(gh.requests, "get", fake_get)
       # המשך הקריאה לפונקציה שבפועל מבצעת את ההורדה…

דוגמה – Mock ל‑non‑GET דרך ``_http_sync_request``:

.. code-block:: python

   import github_menu_handler as gh

   def test_non_get(monkeypatch):
       sentinel = object()

       def fake_req(method, url, **kw):
           assert method == "POST"
           return sentinel

       monkeypatch.setattr(gh, "_http_sync_request", fake_req)
       assert gh.http_request("POST", "https://example.com", data=b"x") is sentinel

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


בדיקות מול מונגו אמיתי
------------------------

רוב הבדיקות בריפו רצות מול stub בפייתון טהור, וזה נכון: הן מהירות, אין להן תלות חיצונית, והן מכסות ניתוב, ולידציה, סדר פעולות וקודי שגיאה.

אבל יש דברים שסטאב **לא יכול** לבדוק — לא כי הוא חלש, אלא כי הם אינם בקוד אלא בהתנהגות של המסד:

- **אילוץ ייחודיות** — אינדקס ייחודי-חלקי כמו ``one_default_per_user`` הוא מה שסוגר מרוץ בין שתי בקשות מקבילות. רק המסד יכול לדחות, ו-``create_index`` שהחזיר בלי לזרוק אינו ראיה שהאינדקס נוצר.
- **האם אינדקס בשימוש** — רק ``explain`` עונה. סטאב מחזיר תוצאה נכונה גם כששאילתה סורקת את כל האוסף.
- **סמנטיקה של BSON** — ``datetime`` נקטם למילישניות, ובלי ``tz_aware=True`` הוא חוזר נאיבי. השוואה בין נאיבי ל-aware זורקת ``TypeError``, ואם היא עטופה ב-``except`` — הבדיקה שנשענת עליה מפסיקה לרוץ בשקט.
- **צינורות aggregation** — סטאב שנכתב ביד מבין רק את הצורה שנכתבה בו, ולכן שגיאת תחביר אמיתית עוברת אצלו.

הבדיקות האלה חיות ב-``tests/test_note_boards_mongo.py``. הן **מדלגות** כשאין ``MONGODB_URL`` או כשהשרת אינו נגיש, כך שהרצה מקומית רגילה נשארת מהירה, ורצות באמת ב-CI — הג'וב ``Unit Tests`` מרים ``mongo:6.0`` כשירות ומגדיר ``MONGODB_URL``.

להרצה מקומית מול שרת אמיתי:

.. code-block:: bash

   MONGODB_URL='mongodb://127.0.0.1:27017' pytest tests/test_note_boards_mongo.py -v

.. warning::
   כל הרצה יוצרת מסד עם שם ייחודי משלה (תחילית ``codebot_notes_it_``), וה-teardown מוודא שהשם תואם לתחילית **לפני** ``drop_database``. אל תכוונו את ``MONGODB_URL`` למסד שיש בו נתונים אמיתיים.

כיסוי בדיקות (pytest-cov)
--------------------------

- הפרויקט מגדיר ``pytest-cov`` ב-``pytest.ini``. אם חסר, התקינו: ``pip install pytest-cov``.
- דוחות:

.. code-block:: bash

   pytest --cov=. --cov-report=term-missing --cov-report=xml

CI נתמך
-------

- ה‑PR חייב לעבור סטטוסים: "🔍 Code Quality & Security", "Unit Tests (3.11)", "Unit Tests (3.12)".

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

העמוד הזה הוא נקודת הכניסה לטסטים, ולכן הוא מפנה גם לעמודים שנוגעים בטסטים מזוויות אחרות. עד כה הם הצביעו לכאן ולא להפך, כך שמי שהגיע לכאן ראשון לא ידע שהם קיימים.

- :doc:`troubleshooting` – שגיאות ייבוא בזמן טסטים, בעיות event loop של asyncio, וכלים לדיבוג מהיר.
- :doc:`performance-tests` – ``pytest -m performance``: איך להריץ בבטחה, מה מסומן כקל ומה כבד, ואיפה נשמרים זמני הריצה.
- :doc:`testing-rate-limit-examples` – קטעי דוגמה לכתיבת טסטים ל-Rate Limiting מול Redis.
- :doc:`ci-cd` – אילו ג'ובים רצים על PR, ומה הסטטוסים הנדרשים.
- :doc:`ai-guidelines` – ההנחיות לסוכנים שעובדים בריפו; בפרק הטסטים: ``tmp_path`` בלבד לכל IO, ו-``safe_rmtree`` למחיקות.
