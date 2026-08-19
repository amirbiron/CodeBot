Doc Authoring Guide (Sphinx/RTD)
================================

מטרות
------
- בנייה ללא אזהרות (``-W --keep-going`` / ``fail_on_warning: true``).
- עקביות בכותרות, קישורים ועוגנים.

מדיניות
--------
- עמודי סקירה חופפים: הוסיפו ``:noindex:`` (api, database, handlers, services, configuration).
- ``autodoc_mock_imports``: רשימת מודולים כבדים/לא זמינים בזמן build.
- אין להריץ קוד בזמן import ברמת מודול.

הטמעת קוד מהמקור (``literalinclude``)
--------------------------------------
- **אסור** למען לפי מספרי שורות (``:lines:``) — הקוד זז והתיעוד ממשיך להציג את הטווח הישן בלי שום אזהרה. זה דפוס ``line-number-coupling`` (ראו amir-bug-patterns), והוא כבר קרה כאן: בלוק שהצביע על ``main.py:739`` הציג פנימיות של פונקציה אחרת, במרחק 2,900 שורות מהיעד.
- פונקציה או מחלקה שלמה ← ``:pyobject:``. הקוד נמשך לפי שם בכל בנייה, ושינוי שם מפיל את הבנייה ברעש.
- קטע בתוך פונקציה ← הערות סימון בקוד בפורמט ``# docs:<שם>:start`` / ``# docs:<שם>:end``, ומיעון ב-``:start-after:`` / ``:end-before:``. הערת ה-start חייבת לומר שהתיעוד תלוי בה ולאיזה דף — אחרת הריפקטור הבא ימחק אותה כהערה סתומה.
- marker חסר מפיל את הבנייה תחת ``-W`` (אזהרת docutils, שאינה מושתקת בקונפיגורציה) — נבדק. marker כפול מסוכן יותר: הבלוק ירונדר מהמופע הראשון בלי אזהרה, ולכן כל שם מופיע פעם אחת בדיוק. ``tests/test_docs_literalinclude_anchors.py`` אוכף את שני הכללים.

טיפים מהירים
------------
- בדקו לוקאלית עם ``make html SPHINXOPTS='-W --keep-going'``.
- השתמשו ב‑``copybutton`` לקוד שמיועד ל‑Copy‑Paste.
- שמרו עוגנים יציבים לכותרות עיקריות.

קישורים
--------
- :doc:`/troubleshooting`
- `DOCUMENTATION_GUIDE.md <https://github.com/amirbiron/CodeBot/blob/main/docs/DOCUMENTATION_GUIDE.md>`_
