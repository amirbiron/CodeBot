מנועי המערכת (System Engines)
===============================

סקירה כללית
------------

מסמך זה מתאר את המנועים המרכזיים במערכת וכיצד הם עובדים.

מנוע חיפוש (Search Engine)
----------------------------

**מיקום:** ``search_engine.py``

**תפקיד:** חיפוש מתקדם בקטעי קוד

**סוגי חיפוש:**
- Text Search - התאמת מחרוזת
- Regex Search - ביטויים רגולריים
- Fuzzy Search - התאמה משוערת
- Content Search - חיפוש Full-Text
- Function Search - חיפוש פונקציות

**רכיבים מרכזיים:**

.. code-block:: python

   class SearchEngine:
       def __init__(self):
           self.index = SearchIndex()
       
       async def search(
           self,
           query: str,
           search_type: SearchType,
           filters: SearchFilter,
           user_id: int
       ) -> List[SearchResult]:
           # בניית אינדקס אם נדרש
           if self.index.needs_rebuild(user_id):
               await self.index.rebuild_index(user_id)
           
           # ביצוע חיפוש
           results = await self._perform_search(query, search_type, filters, user_id)
           
           # חישוב relevance score
           for result in results:
               result.relevance_score = self._calculate_relevance(result, query)
           
           # מיון
           return self._sort_results(results, sort_order)

**אינדקס:**
- Word Index - מילים -> קבצים
- Function Index - פונקציות -> קבצים
- Language Index - שפות -> קבצים
- Tag Index - תגיות -> קבצים

**ראו גם:** :doc:`/workflows/search-flow`

מנוע רפקטורינג (Refactoring Engine)
-------------------------------------

**מיקום:** ``refactoring_engine.py``

**תפקיד:** שינוי מבנה קוד בצורה בטוחה

**סוגי רפקטורינג:**
- Split Functions - פיצול קובץ גדול
- Extract Functions - חילוץ קוד חוזר
- Merge Similar - מיזוג קוד דומה
- Convert to Classes - המרה למחלקות
- Dependency Injection - הוספת DI

**רכיבים מרכזיים:**

.. code-block:: python

   class RefactoringEngine:
       def __init__(self):
           self.analyzer = CodeAnalyzer
       
       async def refactor(
           self,
           code: str,
           filename: str,
           refactor_type: RefactorType
       ) -> RefactorResult:
           # ניתוח קוד
           analyzer = CodeAnalyzer(code, filename)
           if not analyzer.analyze():
               return RefactorResult(success=False, error="Parse error")
           
           # יצירת הצעה
           proposal = await self._create_proposal(analyzer, refactor_type)
           
           # אימות
           validation = await self._validate_proposal(proposal)
           if not validation:
               return RefactorResult(success=False, error="Validation failed")
           
           return RefactorResult(success=True, proposal=proposal)

**CodeAnalyzer:**
- משתמש ב-AST לניתוח Python
- מזהה פונקציות, מחלקות, imports
- מחשב תלויות ומורכבות

**ראו גם:** :doc:`/workflows/refactor-flow`

מעבד קוד (Code Processor)
---------------------------

**מיקום:** ``code_processor.py``

**תפקיד:** עיבוד וזיהוי קוד

**יכולות:**
- זיהוי שפת תכנות
- הדגשת תחביר (Syntax Highlighting)
- ניתוח מטריקות קוד
- זיהוי קידוד תווים

**רכיבים מרכזיים:**

.. code-block:: python

   class CodeProcessor:
       def detect_language(self, code: str, filename: str = None) -> str:
           # ניסיון לפי שם קובץ
           if filename:
               try:
                   lexer = get_lexer_for_filename(filename)
                   return lexer.name
               except:
                   pass
           
           # ניסיון לפי תוכן
           try:
               lexer = guess_lexer(code)
               return lexer.name
           except:
               return 'text'
       
       def highlight_code(
           self,
           code: str,
           language: str,
           format: str = 'html'
       ) -> str:
           lexer = get_lexer_by_name(language)
           formatter = HtmlFormatter(style='monokai')
           return highlight(code, lexer, formatter)
       
       def analyze_code(self, code: str, language: str) -> Dict:
           # מטריקות בסיסיות
           metrics = {
               'lines': len(code.splitlines()),
               'characters': len(code),
               'functions': self._count_functions(code, language),
               'classes': self._count_classes(code, language),
               'complexity': self._calculate_complexity(code, language)
           }
           return metrics

**תמיכה בשפות:**
- 100+ שפות תכנות (דרך Pygments)
- זיהוי אוטומטי לפי שם קובץ או תוכן

מנוע ניתוח (Code Analyzer)
----------------------------

**מיקום:** ``refactoring_engine.py`` (חלק מ-CodeAnalyzer)

**תפקיד:** ניתוח מבנה קוד Python

**יכולות:**
- AST Parsing
- זיהוי פונקציות ומחלקות
- חישוב תלויות
- חישוב מורכבות ציקלומטית

**דוגמה:**

.. code-block:: python

   analyzer = CodeAnalyzer(code, "example.py")
   if analyzer.analyze():
       print(f"Functions: {len(analyzer.functions)}")
       print(f"Classes: {len(analyzer.classes)}")
       for func in analyzer.functions:
           print(f"  {func.name}: complexity={func.complexity}")

מנוע גיבויים (Backup Service)
-------------------------------

**מיקום:** ``services/backup_service.py``

**תפקיד:** יצירת גיבויים ושחזור

**יכולות:**
- יצירת ZIP מגיבוי מלא
- שחזור מגיבוי
- ניהול metadata גיבויים

**ראו גם:** :doc:`/workflows/backup-flow`

מנוע אינטגרציות (Integration Services)
----------------------------------------

**GitHub Service:**
- מיקום: ``services/github_service.py``
- תפקיד: אינטגרציה עם GitHub API
- יכולות: העלאה, הורדה, יצירת repos, PRs

**Google Drive Service:**
- מיקום: ``services/google_drive_service.py``
- תפקיד: אינטגרציה עם Google Drive
- יכולות: העלאה, הורדה, גיבויים אוטומטיים

**ראו גם:** :doc:`/integrations`

מנוע Observability
-------------------

**מיקום:** ``observability.py``, ``observability_otel.py``

**תפקיד:** מעקב אחר ביצועים ושגיאות

**רכיבים:**
- Structured Logging (structlog)
- Metrics (Prometheus)
- Tracing (OpenTelemetry)
- Error Tracking (Sentry)

**ראו גם:** :doc:`/observability`

קישורים
--------

- :doc:`/workflows/search-flow`
- :doc:`/workflows/refactor-flow`
- :doc:`/workflows/backup-flow`
- :doc:`/api/search_engine`
- :doc:`/api/refactoring_engine`
- :doc:`/api/code_processor`
