מדריך תרומה
============

מטרה
-----
לתת מסלול ברור לתרומות קוד, עם דגש על סוכני AI ו-CI.

כללים כלליים
-------------

- Conventional Commits: ``feat|fix|docs|test|refactor|chore|perf``
- הודעת קומיט ב-HEREDOC
- ללא סודות/PII בקוד ובדיפים
- טסטים ירוקים לפני PR

Workflow בסיסי
--------------

1. עדכון docstrings בקוד
2. הרצת טסטים: ``pytest`` (ב-tmp בלבד ל-IO)
3. בניית תיעוד: ``sphinx-build -b html docs docs/_build/html -W --keep-going``
4. פתיחת PR עם תיאור What/Why/Tests ורולבק

דוגמאות שימושיות
-----------------

HEREDOC לקומיט::

   git commit -m "$(cat <<'EOF'
   docs: update contributing guide

   - Clarify tmp_path usage in tests
   - Add docs build step

   EOF
   )"

טסטים – עבודה ב-tmp בלבד::

   def test_file_operations(tmp_path):
       f = tmp_path / "test.py"
       f.write_text("print('ok')")

בדיקות איכות::

   black --check .
   mypy .

קישורים
-------

- :doc:`ai-guidelines`
- :doc:`environment-variables`
- :doc:`examples`
- :doc:`user/github_browse`
- :doc:`webapp/overview`
- :doc:`branch-protection-and-pr-rules`
