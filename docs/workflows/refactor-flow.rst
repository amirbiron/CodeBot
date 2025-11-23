זרימת רפקטורינג (Refactor Flow)
=================================

סקירה כללית
------------

מנוע הרפקטורינג מאפשר שינוי מבנה קוד בצורה בטוחה עם אימות לפני ואחרי.

סוגי רפקטורינג
---------------

.. list-table:: סוגי רפקטורינג
   :header-rows: 1
   :widths: 20 30 50

   * - סוג
     - Enum
     - תיאור
   * - Split Functions
     - ``RefactorType.SPLIT_FUNCTIONS``
     - פיצול קובץ גדול לפונקציות נפרדות
   * - Extract Functions
     - ``RefactorType.EXTRACT_FUNCTIONS``
     - חילוץ קוד חוזר לפונקציות
   * - Merge Similar
     - ``RefactorType.MERGE_SIMILAR``
     - מיזוג קוד דומה (DRY)
   * - Convert to Classes
     - ``RefactorType.CONVERT_TO_CLASSES``
     - המרה למחלקות (OOP)
   * - Dependency Injection
     - ``RefactorType.DEPENDENCY_INJECTION``
     - הוספת DI לשיפור בדיקות

זרימת עבודה
------------

.. mermaid::

   sequenceDiagram
       participant U as User
       participant B as Bot
       participant H as Refactor Handler
       participant RE as RefactoringEngine
       participant CA as CodeAnalyzer
       participant CS as CodeService
       participant DB as MongoDB

       U->>B: /refactor <filename>
       B->>H: handle_refactor()
       H->>DB: שליפת קובץ
       DB-->>H: file_data
       
       H->>U: תפריט בחירת סוג רפקטורינג
       U->>H: בחירת סוג
       
       H->>RE: refactor(file_data, refactor_type)
       RE->>CA: CodeAnalyzer(code, filename)
       CA->>CA: analyze() - AST parsing
       CA->>CA: _extract_functions()
       CA->>CA: _extract_classes()
       CA->>CA: _calculate_dependencies()
       CA-->>RE: functions, classes, dependencies
       
      RE->>RE: יצירת הצעת רפקטורינג
      alt SPLIT_FUNCTIONS
        RE->>RE: Smart Clustering (קבוצות דומיין) + Coupling
        RE->>RE: Dry-Run Import Graph (Tarjan SCC)
        RE->>RE: Merge within cycle + clean self-import + update __init__
       else EXTRACT_FUNCTIONS
         RE->>RE: _extract_duplicate_code()
       else MERGE_SIMILAR
         RE->>RE: _merge_similar_functions()
       else CONVERT_TO_CLASSES
         RE->>RE: _convert_to_classes()
       else DEPENDENCY_INJECTION
         RE->>RE: _add_dependency_injection()
       end
       
       RE-->>H: RefactorProposal
       H->>CS: validate_code_input(proposed_code)
       CS-->>H: validation_result
       
       alt validation passed
         H->>U: תצוגה מקדימה + אישור/עריכה/ביטול
         U->>H: אישור
         H->>DB: שמירת קוד מרופקטר
         H->>DB: יצירת גרסה חדשה
         H->>U: "רפקטורינג הושלם בהצלחה"
       else validation failed
         H->>U: "שגיאת אימות: {error}"
       end

שימוש בבוט (Telegram)
----------------------

הפקודה ``/refactor`` מופעלת ישירות בבוט טלגרם ומאפשרת לבצע רפקטורינג מונחה-מנוע לקובץ נתון.

סינטקס:

- ``/refactor <filename>`` – פותח תפריט בחירת סוג רפקטורינג עבור הקובץ
- ``/refactor <type> <filename>`` – דילוג על התפריט (כאשר סוג נתמך)

סוגים נתמכים בפקודה:

- ``split_functions`` – 📦 פיצול קובץ גדול לפי דומיין/קוהזיה
- ``extract_functions`` – 🔧 חילוץ קוד חוזר לפונקציות עזר
- ``convert_to_classes`` – 🎨 המרה למחלקות (OOP)
- ``merge_similar`` – 🔀 מיזוג קוד דומה (ניסיוני)
- ``dependency_injection`` – 💉 הוספת DI (ניסיוני)

התנהגות קלט שם קובץ:

- תומך בשם בסיסי או נתיב מלא (matching לפי basename)
- מתעלם מסימני גרש/Backticks כולל Smart Quotes: ``"file.py"``, ``'file.py'``, ```file.py````
- מנרמל רווח קשיח (NBSP) ותווי פורמט בלתי-נראים
- התאמה לא תלויה רישיות
- כולל תמיכה בקבצים גדולים (Large Files)
- אם לא נמצא הקובץ – תתקבל הודעה ידידותית והמלצה להשתמש ב-``/list``

תפריט אפשרויות והרצה:

1. לאחר בחירת סוג הרפקטורינג, המערכת מנתחת את הקוד ומייצרת הצעה (RefactorProposal)
2. מתקבלת הודעה מרוכזת הכוללת:
   - תיאור ההצעה
   - סיכום שינויים (Changes Summary)
   - אזהרות אפשריות
   - סטטוס אימות בסיסי (בדיקת AST לכל קובץ שנוצר)
3. כפתורים זמינים:
   - ``✅ אשר ושמור`` – שומר את הקבצים שנוצרו
   - ``🐙 ייצוא ל-Gist`` – יצוא מרובה-קבצים ל-GitHub Gist
   - ``📄 תצוגה מקדימה`` – צפייה בתוכן הקבצים שייווצרו
   - ``📝 ערוך הצעה`` – שמור (כרגע במצב מוקפא, תופיע הערה ידידותית)
   - ``❌ בטל`` – ביטול ההצעה

שמירה ומטא-דאטה:

- בעת שמירה, לכל קובץ חדש מתווספת תגית: ``refactored_<type>`` (למשל: ``refactored_split_functions``)
- נשמר רשומה בטבלה/אוסף ``refactorings`` עם:
  ``user_id``, ``timestamp``, ``refactor_type``, ``original_file``, ``new_files``, ``changes_summary``
- ניתן למצוא את הקבצים החדשים דרך ``/list`` ולנהל גרסאות כרגיל

דוגמאות:

.. code-block:: text

   /refactor large_module.py
   # הבוט יציג תפריט סוגי רפקטורינג עבור הקובץ ויפיק הצעה

.. code-block:: text

   /refactor split_functions services/payments_monolith.py
   # דילוג על התפריט והרצה ישירה של פיצול לפי קוהזיה

CodeAnalyzer
------------

המנתח משתמש ב-AST (Abstract Syntax Tree) לניתוח קוד Python:

.. code-block:: python

   class CodeAnalyzer:
       def __init__(self, code: str, filename: str = "unknown.py"):
           self.code = code
           self.filename = filename
           self.tree: Optional[ast.AST] = None
           self.functions: List[FunctionInfo] = []
           self.classes: List[ClassInfo] = []
           self.imports: List[str] = []
           self.global_vars: List[str] = []
       
       def analyze(self) -> bool:
           try:
               self.tree = ast.parse(self.code)
               self._extract_imports()
               self._extract_functions()
               self._extract_classes()
               self._extract_globals()
               self._calculate_dependencies()
               return True
           except SyntaxError as e:
               logger.error(f"שגיאת תחביר: {e}")
               return False

**מידע שנאסף:**

.. code-block:: python

   @dataclass
   class FunctionInfo:
       name: str
       start_line: int
       end_line: int
       args: List[str]
       returns: Optional[str]
       decorators: List[str]
       docstring: Optional[str]
       calls: Set[str]  # פונקציות שקוראות לה
       called_by: Set[str]  # פונקציות שהיא קוראת להן
       code: str
       complexity: int  # מורכבות ציקלומטית

יצירת הצעת רפקטורינג
----------------------

.. code-block:: python

   @dataclass
   class RefactorProposal:
       refactor_type: RefactorType
       original_file: str
       new_files: Dict[str, str]  # שם קובץ -> תוכן
       description: str
       changes_summary: List[str]
       warnings: List[str] = field(default_factory=list)
       imports_needed: Dict[str, List[str]] = field(default_factory=dict)

**דוגמה - פיצול קובץ גדול:**

.. code-block:: python

   def _split_large_file(
       self,
       analyzer: CodeAnalyzer,
       max_functions_per_file: int = 5
   ) -> RefactorProposal:
       # חלוקת פונקציות לקבוצות
       function_groups = []
       current_group = []
       
       for func in analyzer.functions:
           current_group.append(func)
           if len(current_group) >= max_functions_per_file:
               function_groups.append(current_group)
               current_group = []
       
       if current_group:
           function_groups.append(current_group)
       
       # יצירת קבצים חדשים
       new_files = {}
       base_name = Path(analyzer.filename).stem
       
       for i, group in enumerate(function_groups):
           file_content = self._generate_file_content(group, analyzer.imports)
           new_files[f"{base_name}_part{i+1}.py"] = file_content
       
       return RefactorProposal(
           refactor_type=RefactorType.SPLIT_FUNCTIONS,
           original_file=analyzer.filename,
           new_files=new_files,
           description=f"פיצול ל-{len(new_files)} קבצים",
           changes_summary=[f"נוצרו {len(new_files)} קבצים חדשים"]
       )

אימות לפני ואחרי
-----------------

**אימות לפני רפקטורינג:**

.. code-block:: python

   # אימות הקוד המקורי תקין
   original_valid = await code_service.validate_code_input(
       original_code,
       filename,
       user_id
   )

**אימות אחרי רפקטורינג:**

.. code-block:: python

   # אימות כל הקבצים החדשים
   for new_filename, new_code in proposal.new_files.items():
       validation = await code_service.validate_code_input(
           new_code,
           new_filename,
           user_id
       )
       if not validation['valid']:
           return RefactorResult(
               success=False,
               error=f"שגיאת אימות ב-{new_filename}: {validation['error']}"
           )

ייצוא לגיסט (אופציונלי)
------------------------

לאחר שהמשתמש בחן את ההצעה, הוא יכול לשתף את הקבצים שנוצרו לפני שלב השמירה:

- הכפתור ``🐙 ייצוא ל-Gist`` מופיע לצד ״✅ אשר ושמור״ בחלון ההצעה.
- לחיצה עליו מייצרת Gist מרובה-קבצים דרך ``gist_integration.create_gist_multi`` עם תיאור שמציין את סוג הרפקטורינג ואת מספר הקבצים.
- הפיצ'ר זמין רק כאשר מוגדר ``GITHUB_TOKEN`` תקין; אחרת מוצגת הודעה שהייצוא אינו זמין והמערכת אינה מבצעת קריאה ל-GitHub.
- הייצוא אינו שומר את הקבצים בבסיס הנתונים ואינו מסיר את ההצעה מרשימת ההמתנה, כך שניתן לייצא ואז לאשר/לבטל בנפרד.
- כישלון ביצירת ה-Gist (תקשורת, הגבלה, וכו') נרשם בלוגים ומוצגת למשתמש הודעת שגיאה ידידותית עם הנחיה לנסות שוב מאוחר יותר.

שמירת גרסה
-----------

לאחר רפקטורינג מוצלח:

1. הקוד המקורי נשמר כ-gרסה קודמת
2. הקוד המרופקטר נשמר כגרסה חדשה
3. מספר הגרסה מוגדל
4. נוצר log entry ב-Observability

.. code-block:: python

   # שמירת גרסה חדשה
   await db.save_file_version(
       file_id=file_id,
       code=refactored_code,
       version=current_version + 1
   )

Edge Cases
----------

**קוד לא תקין תחבירית:**
- הניתוח נכשל
- המשתמש מקבל הודעת שגיאה
- הרפקטורינג לא מתבצע

**קובץ קטן מדי:**
- חלק מסוגי הרפקטורינג לא רלוונטיים
- המשתמש מקבל הודעה

**תלויות מורכבות:**
- המערכת מזהירה על תלויות שעלולות להישבר
- המשתמש יכול לבחור להמשיך או לבטל

**שגיאת אימות:**
- הקוד המרופקטר לא נשמר
- המשתמש מקבל הסבר על השגיאה
- הקוד המקורי נשאר ללא שינוי

**Rollback:**
- אם המשתמש לא מרוצה, יכול לשחזר גרסה קודמת
- דרך ``/versions <filename>``

מדיניות קיבוץ ופיצול (Cohesion Policy)
----------------------------------------

המנוע מיישם מדיניות עקבית שמטרתה להימנע מ-Oversplitting בפיצול קבצים ולהימנע מ-God Class בהמרה ל-OOP:

- קיבוץ לפי דומיין: הפונקציות מסווגות לקבוצות לוגיות בסיסיות:

  - **io**: פונקציות קריאה/כתיבה/תקשורת (load/save/fetch/read/write/open/connect/request וכו').
  - **helpers**: פונקציות עזר/פורמט/נירמול/ולידציה (helper/utils/format/convert/parse/normalize/validate).
  - **compute**: לוגיקה חישובית/עסקית.

- תת-קיבוץ לפי prefix: בתוך כל דומיין מתבצע פירוק נוסף לפי prefix של שם הפונקציה, כאשר רק תת-קבוצות משמעותיות נשמרות.
- מיזוג לפי תלות (Affinity): קבוצות קטנות או קרובות ממוזגות על בסיס דמיון שמות וקשרי קריאה ביניהן.
- הגבלת מספר קבוצות: יעד של 3–5 מודולים/מחלקות. לעולם לא מפצלים 1‑ל‑1 לכל פונקציה.
- סף מינימלי לקבוצה: לא נוצרת קבוצה עבור פונקציה בודדת; קבוצות קטנות יתמזגו לקבוצות קרובות.
- מניעת God Class: בעת המרה ל-OOP, אם מתקבלת קבוצה יחידה גדולה – מתבצע פיצול לפי דומיין למחלקות נפרדות (3–5).

Smart Clustering ו‑Cycle Guard
------------------------------

- Smart Clustering:

  - זיהוי "קישורים חלשים" בין דומיינים לצורך פיצול לתת‑גרפים עצמאיים (למשל ``inventory.py`` ו‑``network.py``).
  - Coupling Rule: מנהל+ישות בצימוד גבוה יושבים יחד באותו קובץ (Collocation). אם ישנם ריבוי ישויות או העדפת שכבות – ראו מצב שכבות.

- Dry‑Run Cycle Guard:

  - נבנה גרף ייבוא בין הקבצים שנוצרו; מזוהים מעגלים באמצעות Tarjan SCC.
  - פירוק מעגלים נעשה ע"י מיזוג ממוקד של זוגות מתוך ה‑SCC בלבד, כולל ניקוי self‑import ועדכון ``__init__.py``.
  - ההצעה כוללת אזהרת ״פורקה תלות מעגלית״ כאשר הדבר התרחש.

שמות קבצים דומייניים (Canonical)
----------------------------------

כדי לשמור יציבות וקריאות, שמות הקבצים הדומייניים הם:

- ``users.py``, ``finance.py``, ``inventory.py``, ``network.py`` (API clients), ``workflows.py``
- דומיינים נוספים: ``<base>_<group>.py`` (למשל: ``split_test_big_file_analytics.py``)

מצב שכבות (Layered)
--------------------

- כאשר נדרש בידוד שכבה של ישויות (Entities) ללא תלות חזרה בשירותים:

  - כל המחלקות נוצרות ב‑Leaf יחיד: ``models.py``.
  - מודולי הדומיין מייבאים ממנו רק את המחלקות הדרושות.

- הפעלה באמצעות משתנה סביבה:

.. code-block:: bash

   export REFACTOR_LAYERED_MODE=1

פרמטרים ניתנים לכוונון
----------------------

הפרמטרים הבאים זמינים ב-``RefactoringEngine`` לשליטה בהתנהגות (ברירות המחדל מכוונות ליצירת 3–5 מודולים/מחלקות):

- ``preferred_min_groups``: מינימום מועדף לקבוצות משמעותיות (ברירת מחדל: 3)
- ``preferred_max_groups``: מקסימום מועדף לקבוצות (ברירת מחדל: 5)
- ``absolute_max_groups``: תקרה קשיחה לקבוצות במקרים קיצוניים (ברירת מחדל: 8)
- ``min_functions_per_group``: סף מינימלי לפונקציות בקבוצה כדי שתצדיק מודול/מחלקה (ברירת מחדל: 2)

מגבלות ידועות
--------------

- הסיווג לדומיינים מבוסס יוריסטיקה על שם הפונקציה והקריאות שלה, ולא על הבנת דומיין מלאה.
- אין כרגע ניתוח side-effects או state עמוק; איחוד state משותף נעשה ידנית לפי צורך.
- ``MERGE_SIMILAR`` ו-``DEPENDENCY_INJECTION`` טרם הושלמו במלואם – תופיע הודעת שגיאה ידידותית כאשר יופעלו.
- ``EXTRACT_FUNCTIONS`` מחלץ כפילויות רק כאשר זוהו דפוסים רלוונטיים; אם לא נמצאו, תוחזר הודעת הסבר מתאימה.

קישורים
--------

- :doc:`/api/refactoring_engine`
- :doc:`/api/refactor_handlers`
- :doc:`/workflows/save-flow`
