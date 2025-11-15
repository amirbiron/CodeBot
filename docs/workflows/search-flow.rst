זרימת חיפוש (Search Flow)
===========================

סקירה כללית
------------

מנוע החיפוש תומך במספר סוגי חיפוש:
- **Text Search** - התאמת מחרוזת בסיסית
- **Regex Search** - חיפוש מבוסס תבניות (עם הגנת ReDoS)
- **Fuzzy Search** - התאמה משוערת
- **Content Search** - חיפוש בתוך תוכן הקבצים
- **Function Search** - מציאת הגדרות פונקציות

סוגי חיפוש
-----------

.. list-table:: סוגי חיפוש
   :header-rows: 1
   :widths: 20 30 50

   * - סוג
     - Enum
     - תיאור
   * - Text
     - ``SearchType.TEXT``
     - התאמת מחרוזת רגילה (case-insensitive)
   * - Regex
     - ``SearchType.REGEX``
     - ביטויים רגולריים (עם הגנת ReDoS)
   * - Fuzzy
     - ``SearchType.FUZZY``
     - התאמה משוערת (rapidfuzz)
   * - Content
     - ``SearchType.CONTENT``
     - חיפוש בתוך תוכן הקבצים (Full-Text)
   * - Function
     - ``SearchType.FUNCTION``
     - מציאת הגדרות פונקציות לפי שם

זרימת עבודה
------------

.. mermaid::

   sequenceDiagram
       participant U as User
       participant B as Bot
       participant H as Search Handler
       participant SE as SearchEngine
       participant IDX as SearchIndex
       participant DB as MongoDB

       U->>B: /search <query> [options]
       B->>H: handle_search()
       H->>H: פרסור שאילתה ופילטרים
       H->>SE: search(query, search_type, filters)
       
       SE->>IDX: בדיקת עדכניות אינדקס
       alt אינדקס לא מעודכן
         IDX->>DB: בניית אינדקס מחדש
         DB-->>IDX: כל הקבצים
         IDX->>IDX: בניית word_index, function_index, etc.
       end
       
       SE->>SE: ביצוע חיפוש לפי סוג
       alt Text/Content Search
         SE->>IDX: חיפוש ב-word_index
       else Regex Search
         SE->>SE: בדיקת ReDoS protection
         SE->>SE: ביצוע regex search
       else Fuzzy Search
         SE->>SE: rapidfuzz.fuzz.ratio()
       else Function Search
         SE->>IDX: חיפוש ב-function_index
       end
       
       SE->>DB: שליפת קבצים תואמים
       DB-->>SE: results
       SE->>SE: חישוב relevance_score
       SE->>SE: מיון לפי SortOrder
       SE-->>H: SearchResult[]
       H->>U: הצגת תוצאות (עם דפדוף)

מבנה SearchIndex
-----------------

האינדקס נבנה מחדש כל 24 שעות או על פי דרישה:

.. code-block:: python

   class SearchIndex:
       def __init__(self):
           self.word_index: Dict[str, Set[str]] = defaultdict(set)  # מילה -> קבצים
           self.function_index: Dict[str, Set[str]] = defaultdict(set)  # פונקציה -> קבצים
           self.language_index: Dict[str, Set[str]] = defaultdict(set)  # שפה -> קבצים
           self.tag_index: Dict[str, Set[str]] = defaultdict(set)  # תגית -> קבצים
           self.last_update = datetime.min.replace(tzinfo=timezone.utc)

**בניית אינדקס:**

.. code-block:: python

   def rebuild_index(self, user_id: int):
       # ניקוי אינדקס קיים
       self.word_index.clear()
       self.function_index.clear()
       # ...
       
       # שליפת כל הקבצים
       files = await db.get_all_files(user_id)
       
       for file in files:
           # אינדקס מילים
           words = extract_words(file.code)
           for word in words:
               self.word_index[word].add(file.file_id)
           
           # אינדקס פונקציות
           functions = extract_functions(file.code, file.programming_language)
           for func in functions:
               self.function_index[func].add(file.file_id)
           
           # אינדקס שפות ותגיות
           self.language_index[file.programming_language].add(file.file_id)
           for tag in file.tags:
               self.tag_index[tag].add(file.file_id)

פילטרים
--------

.. code-block:: python

   @dataclass
   class SearchFilter:
       languages: List[str] = field(default_factory=list)
       tags: List[str] = field(default_factory=list)
       date_from: Optional[datetime] = None
       date_to: Optional[datetime] = None
       min_size: Optional[int] = None
       max_size: Optional[int] = None
       has_functions: Optional[bool] = None
       has_classes: Optional[bool] = None
       file_pattern: Optional[str] = None

**דוגמת שימוש:**

.. code-block:: python

   filters = SearchFilter(
       languages=["python", "javascript"],
       tags=["api", "backend"],
       date_from=datetime(2025, 1, 1),
       min_size=1000,
       has_functions=True
   )
   
   results = await search_engine.search(
       query="async function",
       search_type=SearchType.FUNCTION,
       filters=filters
   )

טיפול בשגיאות Regex
--------------------

חיפוש Regex מטפל בשגיאות תחביר:

.. code-block:: python

   def _regex_search(self, pattern: str, user_id: int) -> List[SearchResult]:
       try:
           compiled_pattern = re.compile(pattern, re.IGNORECASE | re.MULTILINE)
       except re.error as e:
           logger.error(f"דפוס regex לא תקין: {e}")
           return []
       
       # ביצוע חיפוש...

**הערה חשובה - ReDoS Protection:**
כרגע הקוד **לא כולל** הגנת ReDoS (Regular Expression Denial of Service). 
המערכת רק בודקת תקינות תחבירית של התבנית דרך ``re.compile()``.

**נקודת שיפור עתידית:**
מומלץ להוסיף בדיקות ReDoS כמו:
- הגבלת אורך תבנית (למשל 1000 תווים)
- הגבלת nesting depth (למשל 10 רמות)
- זיהוי quantifiers מסוכנים (למשל ``.*+``, ``.{100,}``)

**המלצה:**
למשתמשים - הימנעו מתבניות regex מורכבות מאוד שעלולות לגרום ל-ReDoS.

מיון תוצאות
------------

.. code-block:: python

   class SortOrder(Enum):
       RELEVANCE = "relevance"  # לפי relevance_score
       DATE_DESC = "date_desc"  # תאריך יורד
       DATE_ASC = "date_asc"    # תאריך עולה
       NAME_ASC = "name_asc"    # שם עולה
       NAME_DESC = "name_desc"  # שם יורד
       SIZE_DESC = "size_desc"  # גודל יורד
       SIZE_ASC = "size_asc"    # גודל עולה

חישוב Relevance Score
----------------------

.. code-block:: python

   def _calculate_relevance_score(
       file: Dict,
       query: str,
       search_type: SearchType
   ) -> float:
       score = 0.0
       
       # התאמה בשם קובץ (משקל גבוה)
       if query.lower() in file['file_name'].lower():
           score += 10.0
       
       # התאמה בתיאור
       if query.lower() in (file.get('note') or '').lower():
           score += 5.0
       
       # התאמה בתגיות
       for tag in file.get('tags', []):
           if query.lower() in tag.lower():
               score += 3.0
       
       # התאמה בתוכן (משקל נמוך יותר)
       if search_type == SearchType.CONTENT:
           matches = count_matches(file['code'], query)
           score += matches * 0.1
       
       return score

Edge Cases
----------

**שאילתה ריקה:**
- מחזיר רשימה ריקה
- לוג warning

**אינדקס לא קיים:**
- נבנה אוטומטית לפני החיפוש
- יכול לקחת זמן לקבצים רבים

**Regex לא תקין:**
- נדחה עם הודעת שגיאה
- המשתמש מקבל הסבר

**ReDoS detection:**
- השאילתה נדחית
- המשתמש מקבל אזהרה

**תוצאות רבות:**
- מוגבל ל-100 תוצאות
- עם דפדוף (10 פריטים לעמוד)

קישורים
--------

- :doc:`/api/search_engine`
- :doc:`/database/indexing`
- :doc:`/workflows/save-flow`
