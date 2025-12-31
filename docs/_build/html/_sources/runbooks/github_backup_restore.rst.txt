GitHub Backup & Restore Runbook
===============================

מטרה
-----
מדריך צעד‑אחר‑צעד לגיבוי ושחזור מאגר GitHub, כולל יצירת נקודת בדיקה (Checkpoint Tag) ושחזור בטוח.

דרישות מקדימות
---------------
- ``gh`` מותקן ומחובר: ``gh auth login``
- הרשאות ``repo`` ו‑``workflow`` לטוקן בשימוש

יצירת נקודת גיבוי (Checkpoint Tag)
-----------------------------------

.. code-block:: bash

   # סימון נקודת גיבוי (SemVer + תאריך)
   git tag -a v1.0-stable-$(date +%Y%m%d-%H%M) -m "Stable checkpoint"
   git push origin --tags

יצירת ארכיון ZIP
-----------------

.. code-block:: bash

   # ארכיון של הענף הנוכחי
   gh api -H "Accept: application/vnd.github+json" \
     repos/:owner/:repo/zipball -o backup.zip

   # או ספציפית ל‑tag
   gh api -H "Accept: application/vnd.github+json" \
     repos/:owner/:repo/zipball/v1.0-stable-YYYYMMDD-HHMM -o backup.zip

שחזור – בדיקה מקומית
----------------------

.. code-block:: bash

   # יצירת ענף זמני מהגיבוי לבדיקות
   git fetch --all --tags
   git checkout -b restore-from-backup <TAG_NAME>

שחזור מלא לפרודקשן (זהירות!)
------------------------------

.. code-block:: bash

   # החלפת main בגרסת הגיבוי
   git checkout main
   git reset --hard <BACKUP_TAG_OR_BRANCH>
   git push --force origin main

שחזור קבצים/תיקיות נקודתיים
-----------------------------

.. code-block:: bash

   # קובץ בודד
   git checkout <BACKUP_TAG> -- path/to/file.py

   # תיקייה שלמה
   git checkout <BACKUP_TAG> -- path/to/dir/

טיפים ובטיחות
--------------
- אמתו ``git status`` לפני פקודות הרסניות
- גבו שינויים מקומיים ב‑stash או ענף זמני
- הימנעו מ‑``--force`` אלא אם נדרש ומאומת

קישורים
-------
- :doc:`../integrations`
- :doc:`../ci-cd`
- :doc:`../security`
- :doc:`../environment-variables`
- :doc:`../repository-integrations`
