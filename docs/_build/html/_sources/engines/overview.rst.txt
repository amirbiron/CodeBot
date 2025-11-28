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
       def __init__(self) -> None:
           self.analyzer: Optional[CodeAnalyzer] = None
       
       def propose_refactoring(
           self, code: str, filename: str, refactor_type: RefactorType
       ) -> RefactorResult:
           # ניתוח קוד
           self.analyzer = CodeAnalyzer(code, filename)
           if not self.analyzer.analyze():
               return RefactorResult(
                   success=False, proposal=None, error="כשל בניתוח הקוד - ייתכן שגיאת תחביר"
               )
           # יצירת הצעה לפי סוג
           try:
               if refactor_type == RefactorType.SPLIT_FUNCTIONS:
                   proposal = self._split_functions()
               elif refactor_type == RefactorType.EXTRACT_FUNCTIONS:
                   proposal = self._extract_functions()
               elif refactor_type == RefactorType.MERGE_SIMILAR:
                   proposal = self._merge_similar()
               elif refactor_type == RefactorType.CONVERT_TO_CLASSES:
                   proposal = self._convert_to_classes()
               elif refactor_type == RefactorType.DEPENDENCY_INJECTION:
                   proposal = self._add_dependency_injection()
               else:
                   return RefactorResult(success=False, proposal=None, error="סוג רפקטורינג לא נתמך")
               # אימות בסיסי (AST) לתוצרים
               validated = self._validate_proposal(proposal)
               return RefactorResult(success=True, proposal=proposal, validation_passed=validated)
           except Exception as e:
               return RefactorResult(success=False, proposal=None, error=f"שגיאה: {e}")

יכולות מתקדמות (Smart Clustering, Cycle Guard)
-----------------------------------------------

- Smart Clustering (פיצול חכם לתת‑דומיינים):

  - המנוע בונה גרף תלותים בין פונקציות/מחלקות, מזהה "קישורים חלשים" (Weak Links) ומפצל תתי‑גרפים עצמאיים לקבצים נפרדים.
  - דוגמה: ``Inventory`` ו‑``ApiClient`` נחתכים לקבצים עצמאיים כאשר אינם תלויים ב‑Users/Finance.

- Coupling Rule (הצמדה): כאשר יש צימוד גבוה בין מנהל לישות (Type Hints/שימוש תכוף), הם יישבו יחד באותו קובץ (Collocation), למשל ``User`` + ``UserManager`` ב‑``users.py``.

- Dry‑Run Cycle Guard (מניעת מעגליות):

  - בניית גרף ייבוא בין המודולים שנוצרו, זיהוי SCC (Tarjan) ומיזוג נקודתי רק בתוך המעגל כדי לשבור אותו.
  - ניקוי self‑import ועדכון ``__init__.py`` בהתאם. מוסיף אזהרה ידידותית להצעה.

- שמות קבצים דומייניים יציבים (Canonical):

  - ``users.py``, ``finance.py``, ``inventory.py``, ``network.py`` (ל‑API clients), ``workflows.py``.
  - דומיינים אחרים יקבלו שם יציב על בסיס שם הקלט: ``<base>_<group>.py``.

מצב שכבות (Layered Mode)
-------------------------

- אופציונלי: דחיפת כל הישויות ל‑Leaf יחיד ``models.py`` והמודולים התלויים ייבאו ממנו.
- הפעלה דרך משתנה סביבה (ללא שינוי קוד):

.. code-block:: bash

   export REFACTOR_LAYERED_MODE=1

- בברירת מחדל (ללא הדגל) מופעל Collocation: מחלקות ופונקציות נוצרות יחד לפי דומיין.

Safe Decomposition ל‑models.py (פיצול בטוח לחבילת models/)
-----------------------------------------------------------

בסנריו שבו קיימת שכבה שכבתית יציבה וכל המחלקות מרוכזות בקובץ יחיד ``models.py`` (ללא פונקציות טופ‑לבל), המנוע מבצע פיצול בטוח ל‑תתי‑מודולים דומייניים בתוך חבילת ``models/``:

- ``models/core.py`` – ישויות ליבה כגון ``User``, ``UserManager``, ``PermissionSystem``, ``EmailService``.
- ``models/billing.py`` – רכיבי תשלום/מנויים כגון ``PaymentGateway``, ``SubscriptionManager``.
- ``models/inventory.py`` – ישויות מלאי כגון ``Product``, ``Inventory``.
- לפי צורך: ``models/network.py`` (לקוחות API), ``models/workflows.py`` (זרימות).

עקרונות:

- זיהוי דומיין לפי יוריסטיקה של שמות וסקשנים; ברירת המחדל היא שיוך ל‑``core`` כאשר אין רמזים.
- יצירת ``models/__init__.py`` עם re‑exports עבור תאימות לאחור (ייבוא מ‑``models`` ימשיך לעבוד).
- הזרקת יבוא בין‑מודולי למחלקות נדרשות (למשל ``billing`` ייבא ``User`` מ‑``core``: ``from .core import User``).
- Dry‑Run לזיהוי מעגליות בתוך ``models/`` בלבד; פירוק מעגל נעשה ע"י מיזוג נקודתי של מודולים מתוך ה‑SCC ועדכון ``models/__init__.py``.

מתי לבחור Safe Decomposition?

- כאשר המערכת רצה יציב עם ``models.py`` יחיד, אך קיים Coupling מלאכותי בין דומיינים שונים.
- כאשר אין תלות הדדית בין קבוצות ישויות (לדוגמה: ``Inventory`` אינו תלוי ב‑``User``).

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
