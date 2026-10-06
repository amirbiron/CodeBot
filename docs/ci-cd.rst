CI/CD Guide
===========
:summary: מדריך ה-CI/CD: החוקים הקשיחים, הסטטוסים הנדרשים ב-PR, ריכוז ה-workflows, הבדיקות המומלצות ובניית התיעוד.

חוקים קשיחים
-------------

- אין ``git clean/reset`` ב‑CI
- אין ``sudo``
- טסטים ירוצו בסביבות מבודדות; IO רק תחת ``/tmp``
- התיעוד נכשל על אזהרות (``fail_on_warning: true``)
- ``runs-on`` הוא תווית אובונטו שנוקבת בגרסה, ולא תווית שזזה לבד — ראו :ref:`ci-runner-label`

סטטוסים נדרשים
---------------

- 🔍 Code Quality & Security
- Unit Tests (3.11)
- Unit Tests (3.12)
- Unit Tests md-heavy (3.11)
- Unit Tests md-heavy (3.12)

שמות הסטטוסים של ``Unit Tests`` נבנים מהמטריצה של הג'וב ``unit-tests`` ב-``.github/workflows/ci.yml`` (``label`` ו-``python-version``). אותם שמות כתובים ביד גם בקבצים אחרים בריפו, ו-``tests/test_required_checks_are_listed.py`` משווה למטריצה כל קובץ כזה שרשום בו (``LISTS``), כולל העמוד הזה. הוא נכשל גם כשעותק מופיע בקובץ שאינו רשום בו, אלא אם הקובץ מסומן שם כתמונת מצב ולא כרשימה שפועלים לפיה (``SNAPSHOTS``). עמוד שרק צריך להזכיר את הרשימה מפנה לכאן במקום להעתיק אותה.

**סטטוס חדש אינו חוסם מיזוג עד שמסמנים אותו כבדיקת חובה** בכלל שמגן על ``main`` בהגדרות של GitHub (Require status checks to pass before merging). GitHub מציע לבחירה רק בדיקה שעברה בהצלחה בריפו בשבעת הימים האחרונים (GitHub Docs, "Troubleshooting required status checks"), ולכן מסמנים אותה אחרי שה-CI של ה-PR שהוסיף אותה עבר.

ריכוז CI (Overview)
--------------------

- **Code Quality & Security** – בדיקות סטטיות ואבטחה
- **Unit Tests (3.11/3.12)** ו-**Unit Tests md-heavy (3.11/3.12)** – טסטי היחידה, בשני מסלולים לכל גרסת פייתון שרצים במקביל. ``Unit Tests`` מריץ את כל הטסטים חוץ מאלה שמסומנים ``md_heavy``, ו-``Unit Tests md-heavy`` מריץ רק אותם: טסטי פרסר ה-Markdown הכבדים (ראו :doc:`testing`). כל מסלול מדווח סטטוס חובה משלו, והמסלול ``md-heavy`` אינו מרים את MongoDB ואת Redis (``services`` של ``unit-tests``). coverage נמדד ונשלח ל-Codecov רק במסלולים שהמטריצה מסמנת ב-``coverage`` (רשומת ``include`` לפי גרסת פייתון), כדי לא לשלם פעמיים על ההאטה שהוא מוסיף לטסטים, וההעלאות של אותו קומיט מתמזגות ב-Codecov לדוח אחד.
- **JS Tests (node)** – טסטי הצד-לקוח שב-``tests/*.test.js``. כל קובץ הוא סקריפט עצמאי שמריץ את עצמו ויוצא עם קוד שגיאה בכשל, בלי רץ טסטים חיצוני. ``repo-history.test.js`` מדולג במפורש: הוא כתוב בסגנון ``describe``/``it`` ואין בפרויקט רץ שמספק אותם. **אינו סטטוס נדרש** – הכשל מופיע ב-PR אך אינו חוסם מיזוג.
- **Performance Tests** – טסטי ביצועים (ברירת מחדל: הכל; Draft + ``perf-light``: רק קלים). דוחות זמני ריצה נשמרים כארטיפקטים.

קישורים מהירים:

- Actions (Performance): ``https://github.com/<OWNER>/<REPO>/actions/workflows/performance-tests.yml``
- ריצת ה‑PR: בתגובות ה‑PR מתווסף קישור אוטומטי ל‑Run ול‑Artifact.

.. _ci-runner-label:

תווית ה-runner
----------------

כל ``runs-on`` תחת ``.github/workflows`` הוא תווית אובונטו שנוקבת בגרסה, וכל הג'ובים רצים על אותה תווית. ``tests/test_workflow_runner_labels.py`` אוכף את שני הכללים, ולכן התווית עצמה כתובה רק ב-workflows ולא כאן. הצורה המותרת מוגדרת ב-``PINNED_LABEL`` שבטסט, כצורה שחייבת להתקיים ולא כרשימה של תוויות אסורות — למה, ב-docstring של הטסט.

**למה לא ``ubuntu-latest``.** זו לא גרסה אלא מצביע ש-GitHub מעבירים לגרסה חדשה מתי שהם מחליטים, והמעבר הדרגתי: את המעבר ל-Ubuntu 26.04 הם הכריזו כתהליך של כמה שבועות שמתחיל ב-19 באוקטובר 2026 (`actions/runner-images#14748 <https://github.com/actions/runner-images/issues/14748>`_). בזמן הזה חלק מהג'ובים רצים על הגרסה הישנה וחלק על החדשה, ומה שנשבר נראה כמו כישלון אקראי שעובר בהרצה חוזרת. כשהתווית נעוצה, המעבר קורה רק כשמחליטים עליו.

**שדרוג לגרסה חדשה** הוא PR אחד שמחליף את התווית בכל הקבצים. לפני שממזגים בודקים בריצות של הענף של ה-PR אילו ג'ובים רצו על התווית החדשה — בצעד ``Set up job`` של כל ג'וב, הקבוצה ``Runner Image`` כותבת את התמונה בשורת ``Image:``. ג'וב שלא רץ עליה לפני המיזוג יפגוש אותה לראשונה אחריו. **את זה לא מסיקים מה-``on:`` של הקובץ, כי הוא מטעה לשני הכיוונים.** ``push`` רץ מקובץ ה-workflow שבענף שנדחף, גם כשהקובץ עוד לא מוזג, ולכן ``push`` שמסונן רק ב-``paths`` (בלי ``branches``) רץ על הענף של ה-PR כשהוא נוגע בנתיבים האלה, ו-``push`` שמוגבל ל-``main`` לא. ומנגד, ``schedule``, ``workflow_run``, ``issue_comment`` ו-``pull_request_target`` רצים בהקשר של ענף ברירת המחדל — ה-``GITHUB_SHA`` שלהם הוא הקומיט האחרון שם (תיעוד GitHub, "Events that trigger workflows") — ולכן גם כשהם רצים בזמן שה-PR פתוח, הם עדיין על התווית הישנה. לפני הרצה ידנית של workflow מהענף בודקים מה ה-``workflow_dispatch`` שלו מפעיל: ב-``deploy.yml`` הוא פורס (ראו את ה-``if:`` של ``deploy-staging``).

**עד מתי תווית ישנה זמינה:** לפי ה-README של ``actions/runner-images`` (נבדק ב-2026-10-05), GitHub מחזיקים לכל היותר שתי גרסאות GA במקביל, ומתחילים להוציא את הישנה משימוש כשגרסה חדשה עוברת ל-GA.

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
