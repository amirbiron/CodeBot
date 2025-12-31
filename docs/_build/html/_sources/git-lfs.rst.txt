Git LFS Integration
===================

מטרה
-----
להסביר מתי ואיך להשתמש ב‑Git Large File Storage (LFS) עבור קבצים גדולים.

מתי להשתמש ב‑LFS
------------------
- קבצים בינאריים גדולים (תמונות, וידאו, מודלים של ML)
- קבצים שמשתנים לעיתים תכופות וקשה למזג דיפים טקסטואליים

התקנה בסיסית
-------------

.. code-block:: bash

   # התקנת Git LFS (במכונה מקומית)
   git lfs install

   # מעקב אחרי סיומות קבצים גדולות
   git lfs track "*.bin"
   git lfs track "*.mp4"

   # הוספה לקומיט
   git add .gitattributes
   git commit -m "chore: enable git-lfs for binaries"

Best Practices
--------------
- אל תעקבו אחר קבצים טקסטואליים באמצעות LFS (פוגע בביקורות קוד)
- הגדירו תבניות ספציפיות בלבד ב‑``.gitattributes``; הימנעו מ‑globs גורפים
- ודאו ש‑CI/RTD לא מושך מדי קבצים גדולים שלא נחוצים לבנייה

מגבלות וגבולות
---------------
- מגבלות אחסון ותעבורה של Git LFS בחשבון GitHub
- Forks לא תמיד יירשו קבצי LFS ללא הגדרת הרשאות מתאימות

קישורים
-------
- :doc:`integrations`
- :doc:`repository-integrations`
