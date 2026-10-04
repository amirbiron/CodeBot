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
- **בייטים מול תווים** — ``$substrBytes`` ו-``$strLenBytes`` מודדים בבייטים, ``$substrCP`` ו-``$strLenCP`` בתווים, ו-``$regexFind`` מחזיר ``idx`` **בתווים**. על טקסט עברי ערבוב היחידות חותך באמצע אות ומונגו זורקת. אף סטאב בריפו אינו מדגמן את זה — ``tests/_fake_mongo.py`` אפילו אין בו ``aggregate``.

הבדיקות האלה חיות בקבצים נפרדים, וכל אחד מהם נשען על **משתנה סביבה** משלו:

- ``tests/test_note_boards_mongo.py`` — ``MONGODB_URL``, דרך ``pytestmark`` שנבדק פעם אחת בטעינת המודול.
- ``tests/test_profiler_projection_mongo.py`` — ``MONGODB_URL``, גם הוא דרך ``pytestmark``, ובנוסף **שער גרסה** בפיקסצ'ר (ראו למטה).
- ``tests/test_snippet_hebrew_offsets_mongo.py`` — ``NOTE_FONTS_TEST_MONGO_URI``, דרך הפיקסצ'ר ``wired_mongo`` שב-``tests/conftest.py``. אותו פיקסצ'ר משרת גם את שאר הבדיקות שמריצות את הראוטים של הוובאפ מול מסד אמיתי.
- ``tests/test_recycle_bin_ttl_index_mongo.py`` — ``NOTE_FONTS_TEST_MONGO_URI``, ואם הוא ריק ``MONGODB_URL``. ה-``pytestmark`` בודק רק שיש כתובת, והנגישות נבדקת פעם אחת בפיקסצ'ר ``mongo_client``, שמדלג **רק** על ``ServerSelectionTimeoutError`` (גם מארח שאינו נפתר נופל לשם) — אימות שגוי או ``mongodb+srv://`` שאינו נפתר נכשלים ואינם מדלגים. בודק מה השרת עושה עם הבקשה ליצור את אינדקס ה-TTL של סל המיחזור. את המחיקה עצמה הוא אינו בודק: תהליך ה-TTL של השרת רץ פעם בדקה (`TTL Indexes <https://www.mongodb.com/docs/manual/core/index-ttl/>`_), ובדיקה שממתינה לו הייתה נוגעת בתקרת ה-``timeout`` שב-``pytest.ini``.

**המשתנה הנפרד אינו כפילות מיותרת.** ``tests/conftest.py`` עושה ``os.environ.setdefault('MONGODB_URL', …)`` בטעינה, כלומר המשתנה הזה **תמיד** מוגדר בבדיקות — לערך דמה. פיקסצ'ר שהיה נופל אליו היה מחכה 30 שניות לכתובת שאין מאחוריה שרת, בכל בדיקה, ואז נכשל — ו-``--maxfail=1`` היה עוצר את כל החבילה.

כולם **מדלגים** כשהמשתנה שלהם ריק או כשהשרת אינו נגיש, כך שהרצה מקומית רגילה נשארת מהירה. **שרת שכן נגיש אבל בגרסה נמוכה מדי הוא מקרה אחר לגמרי** — שם הבדיקה נכשלת ואינה מדלגת, ראו את הפסקה על גרסת השרת למטה.

.. warning::
   **ב-CI של ה-PR הן אינן רצות.** הג'וב ``Unit Tests`` ב-``.github/workflows/ci.yml`` אמנם מרים ``mongo:8.0`` כשירות, אבל הוא ``runs-on: ubuntu-latest`` **בלי** ``container:``, והשירות מוגדר **בלי** ``ports:``. לפי `תיעוד GitHub Actions <https://docs.github.com/en/actions/using-containerized-services/about-service-containers>`_, גישה לפי שם השירות עובדת רק כשהג'וב עצמו רץ בקונטיינר; אחרת צריך למפות פורטים ולפנות ל-``127.0.0.1:<port>``. בלי זה המארח ``mongodb`` אינו נפתר כלל (``[Errno -3] Temporary failure in name resolution``), והבדיקות מדלגות בשקט.

   התיקון הוא ``ports:`` על השירות ומעבר ל-``127.0.0.1`` — בדיוק כפי שהג'וב ``alembic-migrations`` באותו קובץ כבר עושה עבור postgres. הוא מוצא לסבב נפרד, כי הוא **יעיר** את הבדיקות האלה ואי אפשר לדעת מראש אילו מהן עוברות.

   **אחרי מיזוג הן כן רצות, וזה לא אותו קובץ.** ``.github/workflows/deploy.yml`` מריץ את אותה חבילה על push ל-``main``, ושם השירות ``mongodb`` **כן** מוגדר עם ``ports:`` וה-``MONGODB_URL`` מצביע ל-``localhost:27017`` — כלומר שרת נגיש, והבדיקות שנשענות על ``MONGODB_URL`` רצות במלואן. זה ההסבר לכשל שמופיע "רק אחרי מיזוג": אותה חבילה בדיוק, פעם אחת בלי מסד ופעם אחת איתו.

**גרסת השרת: 8.0 ומעלה, ולא "מונגו כלשהו".** הפרודקשן רץ על MongoDB Atlas 8.0, ולכן כל סביבות הבדיקה מרימות ``mongo:8.0`` — ``.github/workflows/ci.yml``, ``.github/workflows/deploy.yml``, ``docker-compose.yml`` ו-``docker-compose.dev.yml``. בדיקה שרצה מול מסד אמיתי ובודקת מנוע אחר מזה שבפרודקשן היא ביטחון שווא, ולא כיסוי. מי שמרים את ה-compose מקומית על volume שנוצר בזמן של 6.0 צריך מעבר חד-פעמי לפני ההרצה הראשונה — ראו :doc:`/installation`.

ל-``tests/test_profiler_projection_mongo.py`` זה קריטי במיוחד: הוא משווה את ``queryShapeHash`` שמונגו מחזירה ב-``explain``, ולפי `התיעוד של explain <https://www.mongodb.com/docs/manual/reference/command/explain/>`_, השדה הזה נוסף ב-MongoDB 8.0. מול 6.0 הוא פשוט אינו חוזר, וההשוואה מתרוקנת מתוכן. הפיקסצ'ר שם קורא ``buildInfo``, ואם הגרסה נמוכה מ-8.0 הוא **נכשל** בהודעה שאומרת מה גרסת השרת ומה נדרש — ולא מדלג, כי דילוג היה צובע את הריצה בירוק בזמן שההשוואה היחידה שמוכיחה את התיקון אינה מתבצעת.

להרצה מקומית מול שרת אמיתי:

.. code-block:: bash

   MONGODB_URL='mongodb://127.0.0.1:27017' pytest tests/test_note_boards_mongo.py -v

   MONGODB_URL='mongodb://127.0.0.1:27017' pytest tests/test_profiler_projection_mongo.py -v

   NOTE_FONTS_TEST_MONGO_URI='mongodb://127.0.0.1:27017' \
       pytest tests/test_snippet_hebrew_offsets_mongo.py -v

   NOTE_FONTS_TEST_MONGO_URI='mongodb://127.0.0.1:27017' \
       pytest tests/test_recycle_bin_ttl_index_mongo.py -v

.. warning::
   כל הקבצים האלה יוצרים מסד ייעודי משלהם ואינם נוגעים במסד ברירת המחדל: ``test_note_boards_mongo.py`` מגריל שם עם התחילית ``codebot_notes_it_``, ``test_profiler_projection_mongo.py`` עם התחילית ``codebot_profiler_it_``, ``test_recycle_bin_ttl_index_mongo.py`` עם התחילית ``codebot_recycle_ttl_it_``, ו-``wired_mongo`` בונה ``cktest_<שם קובץ הבדיקה>``. ה-teardown של כל קובץ שמגריל שם מוודא שהשם תואם לתחילית **לפני** ``drop_database``. עם זאת — אל תכוונו את אף אחד משני המשתנים למסד שיש בו נתונים אמיתיים.

כיסוי בדיקות (pytest-cov)
--------------------------

- הפרויקט מגדיר ``pytest-cov`` ב-``pytest.ini``. אם חסר, התקינו: ``pip install pytest-cov``.
- דוחות:

.. code-block:: bash

   pytest --cov=. --cov-report=term-missing --cov-report=xml

CI נתמך
-------

- אילו ג'ובים רצים על PR ואילו סטטוסים הוא חייב לעבור — ב-:doc:`ci-cd`. העמוד הזה מפנה לשם במקום להחזיק עותק של הרשימה.

טסטי Markdown כבדים (``md_heavy``)
-----------------------------------

**טסטים שמסומנים ``md_heavy`` רצים ב-CI במסלול משלהם, במקביל לשאר הטסטים.** אלה טסטי פרסר ה-Markdown שעיקר העבודה שלהם הוא החישוב עצמו: השוואה לאורקל cmark-gfm (``tests/test_md_parser_oracle.py``), קלט ענק בתקרות של הפרסר, והטסטים של סקריפטי המדידה (``scripts/md_parser_upgrade_zero_diff.py`` ו-``scripts/measure_md_parse_cost.py``). הסימון רשום ב-``pytest.ini``. הוא מונח על הקובץ כולו (``pytestmark``) כשכל הקובץ מהסוג הזה, ועל טסט בודד כשרק הוא כזה — כמו שני טסטי התקרה ב-``tests/test_md_parser.py``.

- ``pytest`` בלי ``-m`` מריץ את כולם, כולל ``md_heavy``. כדי להריץ רק חלק אחד:

  .. code-block:: bash

     # רק הכבדים — מה שהמסלול md-heavy מריץ ב-CI
     pytest -m md_heavy

     # כל השאר — מה שהמסלול הרגיל מריץ ב-CI
     pytest -m "not md_heavy"

- ב-CI הג'וב ``unit-tests`` ב-``.github/workflows/ci.yml`` רץ בשני מסלולים לכל גרסת פייתון, וכל מסלול מדווח סטטוס חובה משלו (ראו :doc:`ci-cd`).
- **מתי מסמנים טסט חדש:** כשהוא מאותו סוג — השוואה לאורקל, קלט בתקרות של הפרסר, או סקריפט מדידה. טסט איטי מסוג אחר אינו שייך לכאן: המסלול הזה אינו מקום לכל מה שאיטי.
- **אין קשר ל-``heavy``.** ``heavy`` שייך לטסטי הביצועים (``-m performance``), ראו :doc:`performance-tests`.
- **מסלול שלא נבחר בו אף טסט נכשל ואינו עובר בשקט:** pytest יוצא בקוד 5 כשלא נאסף אף טסט, גם כשכולם סוננו ב-``-m`` (נמדד ב-pytest 8.4.2). לכן שם סימון ששונה ב-``ci.yml`` בלי הטסטים, או בכל הטסטים בלי ``ci.yml``, מפיל את המסלול ``md-heavy``. טסט בודד שהסימון שלו חסר או שגוי אינו נתפס כך: הוא עובר למסלול הרגיל ורץ שם, לאט יותר. ``tests/test_required_checks_are_listed.py`` מקבע את קוד היציאה, ובודק שהביטויים של שני המסלולים משלימים זה את זה, כך שכל טסט נבחר במסלול אחד בדיוק.

בדיקות דפדפן, ותקרת הזמן
-------------------------

**בדיקות הדפדפן מדולגות כשאין דפדפן, וההכרעה נעשית פעם אחת לכל הריצה.** הפיקסצ'ר ``chromium_executable`` ב-``tests/conftest.py`` מנסה להרים Chromium פעם אחת, ואם אין — כל בדיקות הדפדפן מדולגות שם, לפני שאף אחת מהן מרימה תהליך דרייבר של Playwright בעצמה. ל-CI **אין שלב שמתקין דפדפן**, ולכן זה המצב הרגיל שם ולא תקלה — והריצה אומרת את זה במפורש בסיכום, כדי שלא ייראה כאילו הבדיקות רצו.

מכאן נובע שהכיסוי של בדיקות הדפדפן ב-CI הוא אפס. מי שרוצה להריץ אותן מקומית צריך דפדפן מותקן ואת ``PLAYWRIGHT_BROWSERS_PATH`` מכוון אליו; בלי זה הן מדולגות בשקט מוצהר.

**ובדיקה שחורגת מהתקרה נכשלת בשמה, ואינה הורגת את התהליך.** ``pytest.ini`` קובע ``timeout = 60`` ואינו קובע ``timeout_method`` — ההשמטה מכוונת, ו-``pytest-timeout`` בוחר בעצמו לפי הפלטפורמה. בשיטה ``thread``, שהייתה כתובה שם קודם, התוסף קורא ``os._exit``: הבדיקה אינה נכשלת אלא הורגת את התהליך שמריץ אותה.

זה מסביר את ההודעה ``node down: Not properly terminated`` שמופיעה בלוגים של ריצות עבר תחת ``pytest-xdist``. היא באה מה-controller, שרואה תהליך שנעלם, ואינה נוקבת בשם הבדיקה — כי ה-worker כותב את המחסנית ל-stderr שלו ויוצא לפני שהפלט נשטף. הסימן שמזהה אותה בלוג הוא הפער: היא מופיעה בדיוק ``timeout`` שניות אחרי השורה האחרונה של אותו worker.

Sentry בבדיקות
----------------

**אף בדיקה לא משאירה Sentry מוכן להידלק בבדיקות שאחריה.** ``tests/_sentry_isolation.py`` נרשם מ-``tests/conftest.py``, ולכן פעיל בכל ריצה שאוספת בדיקות מתוך ``tests/`` — כולל הריצה המלאה — ובריצה כזו הוא חל על כל בדיקה, גם על אלה שמחוץ ל-``tests/`` (``testpaths`` ב-``pytest.ini`` כולל את ``.``). בתחילת הריצה הוא מסיר את ``SENTRY_DSN`` מהסביבה, כך שגם כתובת אמיתית מהמעטפת של מי שמריץ לא מגיעה לבדיקות. אחרי כל בדיקה, כשכל הפיקסצ'רים שלה כבר פורקו — כולל ``monkeypatch`` — הוא בודק שלא נשאר ``SENTRY_DSN`` בסביבה ושאין לקוח Sentry חי. אם נשאר, המצב מוחזר לנקי, והבדיקה **שהשאירה אותו** נכשלת בשמה (``ERROR at teardown``) עם הסבר מה לעשות במקום.

**למה.** טסט הטפטוף של ``PUT /api/agent/upload`` ב-``tests/test_mcp_uploads.py`` עבר לבדו ונפל רק בריצה הסדרתית של ``deploy.yml``, אחרי שתי בדיקות אחרות. אחת השאירה ``SENTRY_DSN`` בסביבה; השנייה טענה מחדש את ``main``, ש-``main.py`` קורא ל-``init_sentry()`` ברמת המודול (#3512), ומשם נדלק Sentry אמיתי עם כל האינטגרציות שהוא מדליק לבד כשהספרייה שלהן מותקנת — Starlette, pymongo, redis, httpx. אינטגרציית ה-Starlette קוראת את גוף הבקשה לפני ה-route ובלי דדליין (``StarletteRequestExtractor.extract_request_info``, נקרא ב-sentry-sdk 2.42.1; #3513), ולכן הטסט שבודק את הדדליין של ה-route נתקע — והשגיאה הופיעה ב-``authenticate_bearer``, רחוק משתי הבדיקות שגרמו לה. ב-``ci.yml`` הבדיקות מתחלקות בין כמה תהליכים (``-n auto``), ולכן שם השרשרת תלויה בחלוקה, ובריצה של ה-PR היא לא נפגשה.

**איך כותבים בדיקה שנוגעת ב-Sentry.** משתנה סביבה — רק ב-``monkeypatch.setenv``. השמה ישירה ל-``os.environ`` נשארת לכל שאר הריצה, ו-``monkeypatch.delenv`` אחרי השמה ישירה **אינו ניקוי**: הוא זוכר את הערך שמצא ומחזיר אותו בסוף הבדיקה — כך בדיוק דלף ``SENTRY_DSN`` מ-``tests/test_db_sentry_checks.py``. בדיקה שבודקת את האתחול מחליפה את ``sentry_sdk.init`` בדמה דרך ``monkeypatch`` (כמו ``tests/test_observability_new.py``), ובדיקה שחייבת לקוח אמיתי קוראת בסופה ל-``_sentry_isolation.shut_down_sentry()``, שמנתקת מכל ה-scopes כל לקוח שרשום בהם וסוגרת כל אחד מהם. ``close()`` לבדו **אינו מספיק**: לקוח סגור שעדיין רשום ב-scope ממשיך להיחשב פעיל (``_Client.is_active``, נקרא ב-sentry-sdk 2.42.1), והשומר יכשיל את הבדיקה.

הבדיקה נעשית אחרי **כל** בדיקה, ולכן גם פיקסצ'ר ברמת מודול שמגדיר ``SENTRY_DSN`` ייתפס אחרי הבדיקה הראשונה שלו. זה מכוון: ``SENTRY_DSN`` בסביבה לאורך כמה בדיקות הוא בדיוק המצב שבו טעינה מחדש של ``main`` מדליקה Sentry. השומר מכסה את ``SENTRY_DSN`` ואת הלקוח בלבד — דליפה של משתני סביבה אחרים בין בדיקות היא #3511. ההתנהגות מקובעת ב-``tests/test_sentry_isolation.py``, שמריץ סשן pytest פנימי ובודק גם שבלי השומר הדליפה כן עוברת לבדיקה הבאה.

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

העמוד הזה הוא נקודת הכניסה לטסטים, ולכן הוא מפנה גם לעמודים שנוגעים בטסטים מזוויות אחרות, כך שמי שהגיע לכאן ראשון יוכל למצוא אותם בקלות.

- :doc:`troubleshooting` – שגיאות ייבוא בזמן טסטים, בעיות event loop של asyncio, וכלים לדיבוג מהיר.
- :doc:`performance-tests` – ``pytest -m performance``: איך להריץ בבטחה, מה מסומן כקל ומה כבד, ואיפה נשמרים זמני הריצה.
- :doc:`testing-rate-limit-examples` – קטעי דוגמה לכתיבת טסטים ל-Rate Limiting מול Redis.
- :doc:`ci-cd` – אילו ג'ובים רצים על PR, ומה הסטטוסים הנדרשים.
- :doc:`ai-guidelines` – ההנחיות לסוכנים שעובדים בריפו; בפרק הטסטים: ``tmp_path`` בלבד לכל IO, ו-``safe_rmtree`` למחיקות.
