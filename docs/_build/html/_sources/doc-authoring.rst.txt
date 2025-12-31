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

טיפים מהירים
------------
- בדקו לוקאלית עם ``make html SPHINXOPTS='-W --keep-going'``.
- השתמשו ב‑``copybutton`` לקוד שמיועד ל‑Copy‑Paste.
- שמרו עוגנים יציבים לכותרות עיקריות.

קישורים
--------
- :doc:`/troubleshooting`
- `DOCUMENTATION_GUIDE.md <https://github.com/amirbiron/CodeBot/blob/main/docs/DOCUMENTATION_GUIDE.md>`_
