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
         RE->>RE: _split_large_file()
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

קישורים
--------

- :doc:`/api/refactoring_engine`
- :doc:`/api/refactor_handlers`
- :doc:`/workflows/save-flow`
