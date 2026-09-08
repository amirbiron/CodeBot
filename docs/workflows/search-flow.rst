זרימת חיפוש (Search Flow)
===========================
:summary: סוגי החיפוש בזרימת הבוט — טקסט, Regex, Fuzzy, פונקציות ותוכן — עם מבנה ה-SearchIndex, הפילטרים, הטיפול בשגיאות Regex ומיון התוצאות. החיפוש הסמנטי הוא מסלול נפרד ב-WebApp.

סקירה כללית
------------

מנוע החיפוש תומך במספר סוגי חיפוש:
- **Text Search** - התאמת מחרוזת בסיסית
- **Regex Search** - חיפוש מבוסס תבניות (עם הגנת ReDoS)
- **Fuzzy Search** - התאמה משוערת
- **Content Search** - חיפוש בתוך תוכן הקבצים
- **Function Search** - מציאת הגדרות פונקציות

.. warning::

   ``SearchType.SEMANTIC`` קיים ב-``enum`` אבל **אינו ממומש בזרימה הזו**:
   ל-``AdvancedSearchEngine.search`` אין ענף עבורו, והוא נופל ל-``else``
   שמריץ ``_text_search`` — כלומר חיפוש טקסט רגיל, בלי embeddings.

   החיפוש הסמנטי האמיתי הוא מסלול נפרד: הפונקציה ``semantic_search``
   ברמת המודול (חיפוש היברידי טקסט+וקטור), שנחשפת ב-
   ``POST /api/search/semantic`` ב-WebApp. גם היא נופלת לחיפוש טקסט
   כאשר ``SEMANTIC_SEARCH_ENABLED`` כבוי או ששירות ה-embeddings לא זמין.

.. note::

   בצינור ההיברידי יש **שני** רפי ציון, על שתי סקאלות שונות — אל תבלבלו
   ביניהם:

   * ``SEMANTIC_MIN_VECTOR_SCORE`` חל על ציון ``$vectorSearch`` הגולמי,
     בטווח קבוע ``0..1`` (ל-``similarity: cosine`` הוא ``(1 + cos) / 2``).
     הוא מסנן את הענף הווקטורי בלבד, מיד אחרי שהציון מחושב.
   * ``MIN_RRF_SCORE`` חל על ציון ה-RRF **אחרי** האיחוד, והמקסימום שלו הוא
     בערך ``0.036``.

   סף שנבחר על הסקאלה הלא נכונה כבר סינן פעם אחת את **כל** התוצאות (ראו
   טבלת תיקוני הבאגים ב-``GUIDES/SEMANTIC_SEARCH_IMPLEMENTATION_GUIDEv2.md``).
   ``SEMANTIC_MIN_VECTOR_SCORE`` הוא ``0`` (כבוי) עד שיכויל על נתונים
   אמיתיים, ואת הכיול יש לעשות **אחרי** ה-re-index ואחרי הדלקת
   ``quantization`` על האינדקס.

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
       
       SE->>SE: ביצוע חיפוש לפי סוג
       alt Text Search
         SE->>IDX: בדיקת עדכניות אינדקס
         alt אינדקס לא מעודכן
           IDX->>DB: בניית אינדקס מחדש
           DB-->>IDX: כל הקבצים
           IDX->>IDX: בניית word_index, function_index, etc.
         end
         SE->>IDX: חיפוש ב-word_index
       else Function Search
         SE->>IDX: בדיקת עדכניות אינדקס (ובנייה אם צריך)
         SE->>IDX: חיפוש ב-function_index
       else Regex Search
         SE->>SE: בדיקת ReDoS protection
         SE->>SE: ביצוע regex search
       else Fuzzy Search
         SE->>SE: rapidfuzz.fuzz.partial_ratio()
       else Content Search
         SE->>DB: סריקת תוכן בעימוד
       end
       
       SE->>DB: שליפת קבצים תואמים
       DB-->>SE: results
       SE->>SE: חישוב relevance_score
       SE->>SE: מיון לפי SortOrder
       SE-->>H: SearchResult[]
       H->>U: הצגת תוצאות (עם דפדוף)

מבנה SearchIndex
-----------------

‏``SearchIndex`` הוא אינדקס הפוך **בזיכרון התהליך**: מילון שממפה מילה, שם
פונקציה, שפה או תגית אל קבוצת הקבצים שמכילים אותם. הוא נבנה מחדש כאשר הוא
מתיישן — ראו ``should_rebuild`` — ומת עם התהליך.

.. important::

   האינדקס נבנה **רק** עבור ``SearchType.TEXT`` ו-``SearchType.FUNCTION``, שהם
   הסוגים היחידים שקוראים ממנו. ‏``CONTENT``, ``REGEX`` ו-``FUZZY`` סורקים את
   ה-DB בעצמם. עד לתיקון הזה הבנייה קדמה ל-dispatch ורצה בכל חיפוש, כולל
   ``CONTENT`` — ברירת המחדל של ה-WebApp — כלומר סריקה מלאה של כל קבצי המשתמש
   (עם ``code``) שאיש לא קרא את תוצאתה, ומיד אחריה עוד סריקה מלאה לחיפוש עצמו.

.. note::

   **מה היחס לאינדקס ה-TEXT של מונגו?** ‏``search_text_idx`` על ``code_snippets``
   (ראו :doc:`/database/indexing`) עושה את אותה עבודה עבור ``word_index``, ואף
   בצורה טובה יותר: הוא על הדיסק, משותף לכל התהליכים, ומתעדכן בכל כתיבה במקום
   להשתהות עד ה-rebuild הבא. מה שיש כאן ואין שם: ``function_index``, שנבנה
   מהרצת ``code_processor.extract_functions`` ומונגו אינו יודע לייצר, וההתאמה
   החלקית (prefix/substring) של ``_text_search``, ש-``$text`` אינו תומך בה.

   ``SEARCH_MEMORY_INDEX_ENABLED=false`` מכבה את האינדקס בזיכרון לגמרי. במצב
   כזה ``TEXT`` ו-``FUNCTION`` מחזירים רשימה ריקה, וב-WebApp ``_safe_search``
   נופל מהם לחיפוש ``$text`` ישירות במונגו — כלומר שני הסוגים ממשיכים להחזיר
   תוצאות, בלי שתי היכולות שלמעלה.

.. note::

   **צרכן שלישי, עקיף: ההשלמה האוטומטית.** ``suggest_completions`` קורא את
   האינדקס דרך ``_get_ready_index``, שבמכוון **אינו** בונה אותו — ההשלמה רצה
   תוך כדי הקלדה, ובניית אינדקס שם הייתה יקרה מדי. לכן היא נהנתה מאינדקס
   שנבנה כתופעת לוואי של חיפוש אחר. משהוסרה הבנייה מ-``CONTENT``, ההשלמה
   מאבדת מילים מתוך תוכן הקבצים ושמות פונקציות; שמות קבצים, תגיות ושפות
   מגיעים מ-``autocomplete_manager`` ומ-``$text`` וממשיכים לעבוד.

   ``SEARCH_MEMORY_INDEX_EAGER_BUILD=true`` מחזיר את החימום ואיתו את ההשלמה
   המלאה, במחיר הסריקה. שני המתגים מצטרפים כך:

   .. list-table::
      :header-rows: 1
      :widths: 30 20 50

      * - ``SEARCH_MEMORY_INDEX_ENABLED``
        - ``..._EAGER_BUILD``
        - התנהגות
      * - ``false``
        - לא רלוונטי
        - אין אינדקס בזיכרון בכלל
      * - ``true`` (ברירת מחדל)
        - ``false`` (ברירת מחדל)
        - אינדקס רק ל-``TEXT``/``FUNCTION``
      * - ``true``
        - ``true``
        - אינדקס בכל חיפוש; ההשלמה מקבלת אותו חם

מבנה האינדקס:

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
- נבנה אוטומטית בענפים שצורכים אותו (``TEXT``/``FUNCTION``) לפני החיפוש
- יכול לקחת זמן לקבצים רבים
- ``SEARCH_MEMORY_INDEX_ENABLED=false`` ⇒ אינו נבנה כלל, והחיפוש נופל ל-``$text``

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
