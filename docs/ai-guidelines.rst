הנחיות מלאות לסוכני AI
========================

מגבלות קריטיות
--------------

הרצת פקודות
~~~~~~~~~~~~

אסור בהחלט::

  # אין sudo
  sudo apt install something

  # תהליכים ארוכי-חיים
  npm run dev
  python manage.py runserver
  watch -n 1 "pytest"

  # פקודות אינטראקטיביות
  git rebase -i
  git add -i
  nano file.txt

  # שינוי git config
  git config user.email "..."
  git config --global ...

  # פעולות git מסוכנות (ללא הוראה מפורשת)
  git push
  git push --force
  git clean -fdx
  git reset --hard

מותר ומומלץ::

  # טסטים
  pytest
  pytest tests/test_file.py -v

  # linting
  black --check .
  mypy .

כלי קבצים מאושרים
-------------------

השתמשו בכלים המובנים::

  Read(path="file.py")
  LS(target_directory=".")
  Grep(pattern="def.*hello", type="py")
  Glob(glob_pattern="*.py")

אל תשתמשו בפקודות raw::

  cat file.py
  ls -la
  find . -name "*.py"
  grep -r "pattern" .
  head -n 10 file.py
  tail -f log.txt

עקרונות עריכת קוד
-------------------

1. עריכות נקודתיות בלבד
2. שמירה על סגנון קיים
3. ללא try/except מיותרים
4. העדפת guard clauses

קומיטים ו-Pull Requests
-----------------------

תמיד HEREDOC::

  git commit -m "$(cat <<'EOF'
  docs: improve AI guidelines and quickstart

  - Add safe_rmtree example
  - Clarify allowed tools and flows

  EOF
  )"

Conventional Commits: `feat` | `fix` | `docs` | `test` | `refactor` | `chore` | `perf`

עבודה עם טסטים
---------------

- שימוש ב-`tmp_path` בלבד לכל IO
- שימוש ב-`safe_rmtree` למחיקות תחת `/tmp` בלבד

דוגמה::

  def test_file_operations(tmp_path):
      test_file = tmp_path / "test.py"
      test_file.write_text("print('hello')")

מחיקה בטוחה::

  from pathlib import Path
  import shutil

  def safe_rmtree(path: Path, allow_under: Path) -> None:
      p = path.resolve()
      base = allow_under.resolve()
      if not str(p).startswith(str(base)) or p in (Path('/'), base.parent, Path.cwd()):
          raise RuntimeError(f"Refusing to delete unsafe path: {p}")
      shutil.rmtree(p)

קישורים מהירים
--------------

- :doc:`quickstart-ai`
- :doc:`testing`
- :doc:`ci-cd`
- :doc:`security`
