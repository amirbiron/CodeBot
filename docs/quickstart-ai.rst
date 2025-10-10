התחלה מהירה - סוכני AI
=========================

מטרה
-----
מסמך זה נועד לאפשר לסוכן AI להתחיל לעבוד על הריפו במהירות ובבטחה, בהתאם למדיניות הפרויקט.

מה אסור
--------

- ללא sudo – לעולם אל תריץ פקודות עם sudo
- ללא תהליכים ארוכי-חיים – אל תריץ `npm run dev`, `watch`, שרתים וכדו'
- ללא פקודות אינטראקטיביות – אל תשתמש ב-`git rebase -i`, `git add -i`, `nano`
- ללא שינוי git config – אל תערוך הגדרות git
- ללא push ל-remote – אל תדחוף קוד אלא אם התבקשת מפורשות

מה מותר ומומלץ
--------------

- כלי קריאה מאושרים בלבד: `Read`, `LS`, `Grep`, `Glob`
- אל תשתמש בפקודות raw כמו `cat`, `ls`, `find`, `grep` – השתמש בכלים המובנים
- עבודה בנתיבים מוחלטים
- כל IO בטסטים ובסקריפטים – אך ורק תחת `/tmp`
- עריכות נקודתיות ושמירה על סגנון קיים

פורמטי ציטוט קוד
-----------------

קוד קיים (CODE REFERENCE):

.. code-block:: none

   12:15:app/components/Todo.tsx
   export const Todo = () => {
     return <div>Todo</div>;
   };

קוד חדש/מוצע (Markdown code block רגיל):

.. code-block:: bash

   gh pr create --title "feat: add X" --body "Why and test plan"

מחיקה בטוחה (רק ב-/tmp)
------------------------

.. code-block:: python

   from pathlib import Path
   import shutil

   def safe_rmtree(path: Path, allow_under: Path) -> None:
       p = path.resolve()
       base = allow_under.resolve()
       if not str(p).startswith(str(base)) or p in (Path('/'), base.parent, Path.cwd()):
           raise RuntimeError(f"Refusing to delete unsafe path: {p}")
       shutil.rmtree(p)

   # שימוש
   safe_rmtree(Path("/tmp/test"), allow_under=Path("/tmp"))

קומיטים ו-PR
------------

קומיט עם HEREDOC:

.. code-block:: bash

   git commit -m "$(cat <<'EOF'
   feat: short why-oriented message

   - List key changes
   - Add tests, update docs

   EOF
   )"

Checklist לפני קומיט:

- אין סודות/PII בדיפים
- Conventional Commit
- טסטים ירוקים

קישורים מהירים
--------------

- :doc:`ai-guidelines`
- :doc:`installation`
- :doc:`examples`
- :doc:`user/github_browse`
- :doc:`webapp/overview`
