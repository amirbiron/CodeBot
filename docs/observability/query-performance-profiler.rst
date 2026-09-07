Query Performance Profiler
==========================
:summary: כלי ניטור לשאילתות MongoDB איטיות: דשבורד ב-WebApp שמציג את השאילתות הכבדות, ה-API שמאחוריו, ומה הכלי במפורש אינו עושה.

.. contents:: תוכן עניינים
   :local:
   :depth: 2

Overview
--------

**Query Performance Profiler** הוא כלי ניטור לשאילתות MongoDB איטיות, המספק:

1. **זיהוי שאילתות איטיות** – מעקב בזמן אמת אחרי שאילתות שחורגות מסף זמן מוגדר
2. **ניתוח Explain Plans** – הצגה ויזואלית של תוכנית הביצוע של MongoDB (כולל Aggregation Pipelines)
3. **המלצות אופטימיזציה** – הצעות אוטומטיות לשיפור ביצועים
4. **היסטוריית שאילתות** – שמירה וניתוח של דפוסי שאילתות לאורך זמן

קהל יעד
~~~~~~~~

הפרופיילר מיועד למפעילים מורשים בלבד. במסלולי ה-**WebApp (Flask)** סשן
אדמין נדרש תמיד: ``_profiler_is_authorized`` (``webapp/app.py``) מסתיים
בבדיקת אדמין בכל מסלול Flask, ולכן:

- אין גישה למסלולי Flask בלי סשן אדמין — גם עם ``X-Profiler-Token`` תקין.
- כשיש סשן אדמין במסלולים האלה, הטוקן אינו נבדק כלל.
- ``PROFILER_ALLOWED_IPS``, אם הוגדר, חל **גם** על אדמין מחובר.

כלומר במסלולי Flask, ``PROFILER_AUTH_TOKEN`` אינו פותח גישה ואינו חוסם
אותה. החריג הוא מסלולי הפרופיילר של הבוט (aiohttp): אין בהם סשן WebApp,
וכאשר הטוקן מוגדר הם מאמתים את ``X-Profiler-Token`` ישירות. בנתיב
``GET /api/profiler/slow-queries`` של הבוט זמינים רק ``limit``,
``collection``, ``min_time`` ו-``hours`` — ראו את טבלת ההבדלים למטה.

מה הכלי לא עושה
~~~~~~~~~~~~~~~~~

- לא מחליף את MongoDB Profiler המובנה ברמת ה-DB
- לא מספק אופטימיזציה אוטומטית (רק המלצות)
- לא מיועד ל-Production Debugging בזמן אמת של שאילתות בודדות

ממשק משתמש (WebApp)
--------------------

הנתיב
~~~~~~

``GET /admin/profiler``

איך להגיע
~~~~~~~~~~

1. דרך Settings → כלי אדמין → Query Profiler
2. או ישירות לכתובת ``/admin/profiler``

מה רואים בדשבורד
~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - אזור
     - תיאור
   * - Summary
     - סיכום כללי: מספר שאילתות איטיות, זמן ממוצע, collections מושפעים
   * - Slow Queries Table
     - טבלה עם שאילתות איטיות, כולל סינון לפי collection
   * - ניתוח Query/Pipeline
     - טופס להזנת שאילתה לניתוח מיידי
   * - Explain Visualization
     - ויזואליזציה של שלבי הביצוע (COLLSCAN, IXSCAN, FETCH וכו')
   * - Recommendations
     - המלצות אופטימיזציה לפי חומרה (קריטי/אזהרה/מידע)

.. note::
   ברירת המחדל של ה-verbosity היא ``queryPlanner`` (בטוח) – לא מריץ את השאילתה בפועל.

API Reference
-------------

Authentication
~~~~~~~~~~~~~~

במסלולי הבוט (aiohttp), אם ``PROFILER_AUTH_TOKEN`` מוגדר, יש לשלוח את
הטוקן בכותרת:

.. code-block:: text

   X-Profiler-Token: <your-token>

במסלולי ה-WebApp (Flask) הטוקן אינו מחליף סשן אדמין. במסלולי הבוט אין
סשן WebApp, והטוקן נבדק ישירות (ראו `קהל יעד`_).

Endpoints
~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 15 50 35

   * - Method
     - Endpoint
     - תיאור
   * - GET
     - ``/api/profiler/summary``
     - סיכום מצב הפרופיילר
   * - GET
     - ``/api/profiler/slow-queries``
     - רשימת שאילתות איטיות (עם סינון, מיון ועימוד)
   * - GET
     - ``/api/profiler/patterns``
     - דפוסי שאילתות חוזרים בחלון (וובאפ בלבד)
   * - POST
     - ``/api/profiler/explain``
     - הרצת Explain Plan על שאילתה/pipeline
   * - POST
     - ``/api/profiler/recommendations``
     - ניתוח והמלצות לשאילתה
   * - POST
     - ``/api/profiler/analyze``
     - Alias ל-recommendations
   * - GET
     - ``/api/profiler/collection/<name>/stats``
     - סטטיסטיקות collection (גודל, אינדקסים)

GET /api/profiler/summary
^^^^^^^^^^^^^^^^^^^^^^^^^^

מחזיר סיכום כללי:

.. code-block:: bash

   curl -H "X-Profiler-Token: $TOKEN" \
        https://your-app.com/api/profiler/summary

**Response:**

.. code-block:: json

   {
     "status": "success",
     "data": {
       "total_slow_queries": 42,
       "collections_affected": ["code_snippets", "users"],
       "avg_execution_time_ms": 350.5,
       "max_execution_time_ms": 2500.0,
       "unique_patterns": 15,
       "threshold_ms": 100
     }
   }

GET /api/profiler/slow-queries
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. important::

   **הנתיב הזה מוגש בידי שני שירותים שונים, והם אינם זהים.**

   .. list-table::
      :header-rows: 1
      :widths: 20 30 50

      * - מי
        - הרשאה
        - מה יש בו
      * - הוובאפ (Flask)
        - סשן אדמין
        - כל מה שמתואר למטה — עימוד, מיון, ``total`` ו-``next_cursor``
      * - הבוט (aiohttp)
        - ``X-Profiler-Token``
        - ``limit``, ``collection``, ``min_time``, ``hours`` בלבד

   **כל מה שבסעיף הזה מתאר את הוובאפ.** בראוט של הבוט אין ``sort``/``dir``/``cursor``,
   התשובה אינה נושאת ``total`` או ``next_cursor``, ו-``limit`` אינו מגובל. פרמטר
   שאינו מוכר שם פשוט מתעלמים ממנו — כלומר בקשה עם ``sort`` תחזיר 200 עם הסדר
   הרגיל, בלי שום סימן שהמיון לא נלקח בחשבון. אם אתם מדברים עם השירות דרך טוקן,
   זה השירות שאתם מקבלים.

**Query Parameters:**

.. list-table::
   :header-rows: 1

   * - Parameter
     - תיאור
     - ברירת מחדל
   * - ``limit``
     - מספר שאילתות בדף. מגובל ל-500.
     - ``50``
   * - ``collection``
     - סינון לפי collection
     - (הכל)
   * - ``min_time``
     - זמן ביצוע מינימלי (ms). ערך שאינו מספר סופי מוחזר כ-400.
     - (הכל)
   * - ``hours``
     - חלון הזמן בשעות. מגובל ל-TTL של האוסף (7 ימים).
     - ``24``
   * - ``sort``
     - שדה המיון: ``execution_time_ms``, ‏``timestamp``, ‏``collection`` או
       ``operation``. ערך אחר מוחזר כ-400 ולא נופל לברירת מחדל.
     - ``execution_time_ms``
   * - ``dir``
     - ``asc`` או ``desc``. ערך אחר מוחזר כ-400.
     - ``desc``
   * - ``cursor``
     - הקורסור לדף הבא, כפי שהוחזר ב-``next_cursor``.
     - (הדף הראשון)

**מה חוזר.** לצד ``data`` ו-``count`` התשובה נושאת שני שדות שהעימוד נשען עליהם:

* ``total`` — כמה שאילתות יש **בחלון**, אחרי ``collection`` ו-``min_time`` אבל
  **בלי** תנאי הקורסור. לכן הוא אינו קטן בכל לחיצה על "טען עוד", וזה מה שמאפשר
  לכותרת לומר "מוצגות X מתוך Y" בלי לשקר. הוא נספר מחדש בכל בקשה: שאילתה איטית
  שנרשמת תוך כדי דפדוף **אמורה** להגדיל אותו.
* ``next_cursor`` — קורסור לדף הבא, או ``null`` כשאין. הוא נטבע עבור ``sort``
  ו-``dir`` מסוימים, ושליחתו עם מיון אחר מוחזרת כ-400 (``cursor_sort_mismatch``)
  ולא מנוחשת.

**דוגמה** — הכתובת של הוובאפ, עם עוגיית הסשן ולא עם טוקן. דוגמת ``curl`` עם
``X-Profiler-Token`` הייתה מגיעה לראוט של הבוט, ושם ``sort`` פשוט נבלע:

.. code-block:: text

   /api/profiler/slow-queries?limit=20&collection=code_snippets&sort=timestamp&dir=desc

GET /api/profiler/patterns
^^^^^^^^^^^^^^^^^^^^^^^^^^^

דפוסי השאילתות שחוזרים בחלון — הנתונים שמאחורי כרטיס "דפוסים ייחודיים". מקבל
``hours`` (כמו למעלה) ו-``limit`` (מגובל ל-200, ברירת מחדל 50), ומחזיר ``data``
עם שורה לכל דפוס — ``collection``, ‏``operation``, ‏``query_shape``, ‏``count``,
``avg_time_ms``, ‏``max_time_ms`` ו-``last_seen`` — לצד ``total``, מספר הדפוסים
הכולל בחלון. ``total`` הוא מה שמאפשר לומר כמה נחתך במקום להשמיט את זה בשקט.

ערכים אמיתיים לשאילתות שלך (``query_raw``)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

כל רשומה נושאת ``query_shape`` — שלד שבו כל ערך הוחלף ב-``<value>``. השלד הוא מה
שמזהה דפוס, מה שמוצג, ומה שנכנס לדוח שמודבק ל-AI. ההגנה הזו מעוורת גם את האדמין
שמנתח את השאילתות של **עצמו**: ניתוח על ``{"user_id": "<value>"}`` מחזיר אפס תוצאות
ומסקנות ריקות.

לכן, כשמזהה המשתמש שלך נמצא ב-``PROFILER_UNREDACTED_USER_IDS``, רשומה של שאילתה
**שזוהתה בוודאות כשלך** נושאת גם ``query_raw`` — הערכים האמיתיים — וכפתור הניתוח
בדשבורד מעדיף אותו. ``query_shape`` ו-``query_id`` אינם משתנים, כך שקיבוץ הדפוסים
נשאר כפי שהיה.

**מה בדיוק נשמר עם ערכים: תנאי הסינון.** בשאילתת ``find`` זו כל השאילתה, כי היא
כולה סינון. באגרגציה אלה שלבי ה-``$match`` בלבד, בכל עומק — כולל בתוך ``$lookup``
ו-``$unionWith`` — וכל שאר השלבים נשארים בשלד המנורמל. הסיבה: מה שנשמר עם ערכים
חייב להיות מה שעבר ולידציה מלאה מול רשימת השדות והאופרטורים, וגוף של
``$addFields`` או ``$group`` הוא ביטוי שאין מולו רשימה כזו. ה-explain לא מפסיד
מכך, כי מה שקובע אילו מסמכים נסרקים ואיזה אינדקס נבחר הוא הסינון.

**איך הערכים שורדים את הדרך לדפדפן.** ל-JSON רגיל אין טיפוס תאריך, ולכן ``datetime`` היה יוצא מחרוזת וחוזר מחרוזת — ומונגו שמשווה מחרוזת לשדה תאריך אינו מתאים לאף מסמך. נמדד על ``code_snippets`` בפרודקשן: התאריך האמיתי מתאים ל-1,157 מסמכים, המחרוזת ל-0. כלומר ה-``explain`` היה מתאר שאילתה מהירה עם אפס סריקה — דוח שנראה מצוין ומסקנתו הפוכה, וזה גרוע מ-``<value>`` שלפחות נראה שבור. לכן ``query_raw`` נוסע ב-**Extended JSON** (``{"$date": …}``), והבקשה שמחזירה אותו לניתוח **מצהירה** על הניב בשדה ``encoding``. ההצהרה נחוצה ואינה קישוט: פענוח גורף היה חל גם על השלד המנורמל, ושם ``{"$options": "<value>"}`` הופך בשקט ל-``Regex`` עם דגלים אקראיים במקום לייצר שגיאה רועשת ממונגו.

**וגם ערכי המבנה: ``$limit``, ``$skip``, כיווני ``$sort`` ודגלי ``$project``.**
אלה אינם נתוני משתמש אלא צורת השאילתה, והם ניתנים לאימות מלא בלי שום רשימה — שלם
חיובי, שלם אי-שלילי, שדה ← ``1``/``-1``/``$meta``, או היטלה שכולה
``0``/``1``/בוליאני/נתיב שדה. הם נשמרים אמיתיים כי בלעדיהם הניתוח מתאר שאילתה
אחרת: ``$limit`` הוא מה שהופך מיון חוסם ל-top-k, ובלעדיו השלב עלול לחרוג ממגבלת
המיון בזיכרון של Atlas ולהיראות כבעיה שאינה קיימת. (``_fix_pipeline_for_explain``
משלים ``$limit`` חסר בערך ברירת מחדל, ולכן ה-explain רץ בכל מקרה — אבל על מספר
שאינו זה שרץ בפרודקשן.)

**ולמה ``$project`` הצטרף אליהם.** מחרוזת שאינה מתחילה ב-``$`` בתוך היטלה אינה
נקראת כשם שדה אלא כ**קבוע**, ולכן ``{"$project": {"file_name": "<value>"}}`` אינו
היטלה מוסתרת אלא **פעולה אחרת לגמרי**: "החזר את הקבוע ``<value>``" במקום "החזר את
השדה ``file_name``". נמדד מול MongoDB 8.0.32 — ה-``explain`` מחזיר את השלב בתור
``{"file_name": {"$const": "<value>"}}``, ו-``queryShapeHash`` שלו שונה מזה של
ההיטלה האמיתית, כלומר המנוע עצמו סופר אותן כשתי שאילתות. שלב שמושך את ``code``
היה מנותח כשלב שאינו קורא שום שדה. וזה נכשל בשקט: בניגוד ל-``$limit``, מחרוזת
בהיטלה אינה גורמת למונגו לזרוק, ולכן גם ``_fix_pipeline_for_explain`` — שמתקנת רק
את השלבים שזורקים — לא נגעה בה.

הוולידציה כאן צרה בכוונה, וזו אינה החמרה קוסמטית: התיעוד של ``$project`` אומר
*"Non-zero integers are also treated as true"*, כלומר ``{"file_name": 6865105071}``
הוא היטלת הכללה חוקית לגמרי — ומזהה משתמש יושב בה בגלוי. סריקת הבעלות עוברת על
גופי ``$match`` בלבד ולעולם לא תראה אותו, ולכן ``0`` ו-``1`` בלבד הם מה שסוגר את
הדלת. ``$project`` שיש בו ולו ביטוי אחד חוזר כשלד **שלם**, ולא כתערובת של ערכים
אמיתיים ו-``<value>`` — שלב שחציו אמיתי נראה שלם ומתפרש אחרת ממה שרץ, וזה בדיוק
הכשל שהשינוי הזה בא לסגור. ``$addFields``/``$set`` ו-``$unset`` של אגרגציה נשארו
מחוץ להיתר, כי אין להם היום מופע אמיתי לאמת מולו.

השמירה נכשלת סגור, ובקול. כשאין ``query_raw`` יש ``raw_withheld_reason``, והדשבורד
מציג אותו בשורה — גם בשורות ``update``/``delete`` שאין להן כפתור ניתוח, כי דווקא
שם אין שום רמז אחר:

.. list-table::
   :header-rows: 1

   * - סיבה
     - מתי
   * - ``owner_missing``
     - השאילתה אינה מצהירה על ``user_id`` (ברמה העליונה או בתוך ``$and``, כשוויון או כ-``$in``; באגרגציה — בשלב ה-``$match`` הראשון, היחיד שמגביל את כל מה שאחריו). ``$or`` לבדו אינו מגביל, ולכן אינו נספר, וגם ``$ne``/``$nin`` אינם — הם "כל השאר", ההפך מהגבלה.
   * - ``owner_mismatch``
     - ``user_id`` שאינו ברשימה מופיע ב**מיקום סינון** — גוף ``$match`` בכל עומק, כולל בתוך ``$lookup``/``$unionWith``/``$facet``, ובשאילתת ``find`` בכל השאילתה. מזהה זר בשלב אחר (``$set``, ``$lookup.let``) אינו מגיע לרשומה מסיבה אחרת: השלבים האלה נשמרים מנורמלים ולעולם אינם נושאים את הערך.
   * - ``unknown_field:<שם>``, ``unknown_operator:<שם>``, ``unknown_stage:<שם>``
     - מפתח שאינו ברשימת השדות, האופרטורים או שלבי האגרגציה המוכרים. השם נשמר כדי שאפשר יהיה להרחיב את הרשימה בידיעה, לא בניחוש.
   * - ``vector_query``
     - ``$vectorSearch``. וקטור של מאות מספרים אינו קריא, אינו עוזר לניתוח, ומנפח אוסף עם TTL.
   * - ``unsupported_type:<טיפוס>``
     - ערך שאינו שורד מסע הלוך-ושוב ב-Extended JSON. ההגדרה אינה רשימת טיפוסים אלא הסיבוב עצמו (``json_util.dumps`` ← ``json_util.loads``), כך שטיפוס חדש נדחה בשמו בלי שאיש יעדכן רשימה. **``datetime``, ``ObjectId``, ``Decimal128`` ו-``bytes`` אינם כאן** — Extended JSON נושא את הטיפוס בתוך ה-JSON וכולם חוזרים שווים למקור.
   * - ``unsupported_number``
     - ``inf``, ``-inf`` או ``NaN``. ``NaN`` אינו מתאים לאף מסמך במונגו, ולכן שמירתו הייתה מייצרת ``explain`` על שאילתה שמחזירה אפס — בדיוק הדוח המטעה שהמנגנון קיים כדי למנוע. ``±inf`` בטוח רק בקידוד Extended JSON, וההחלטה כאן נעשית **בזמן הכתיבה**, לפני שידוע איך הרשומה תוגש. (שימו לב: ``json_util.dumps`` **מתעלם** מ-``allow_nan=False``, ולכן הבדיקה מפורשת ורצה לפני הסיבוב.)
   * - ``internal_error``
     - תקלה בלתי צפויה בהחלטה עצמה. היא נרשמת ללוג, ו**הרשומה עצמה שורדת** — ``query_raw`` הוא העשרה, והשאילתה האיטית היא המוצר.
   * - ``malformed``
     - מבנה שאינו ניתן לסידור כלל — למשל מפתח שאינו מחרוזת.
   * - ``malformed_stage:<שם>``
     - ערך מבני לא תקין בשלב: ``$limit`` שאינו שלם חיובי, ``$skip`` שלילי, או ``$sort`` שכיוונו אינו ``1``/``-1``/``$meta``.
   * - ``too_large``
     - ה-JSON גדול מ-``PROFILER_UNREDACTED_MAX_BYTES``.
   * - ``owner_not_allowed_now``
     - הרשומה נכתבה עם ערכים, אבל המשתמש כבר אינו ברשימה. הקונפיג הוא הסמכות הנוכחית, גם על רשומות ישנות.

**איפה הערכים חיים — במקום אחד בלבד:** ברשומה ב-``slow_queries_log``, תחת ה-TTL
של שבעה ימים. ה-buffer שבזיכרון התהליך מקבל **עותק בלי הערכים** — ``query_raw``
ו-``raw_owner_id`` מוסרים ממנו, ו-``raw_withheld_reason`` נשאר, כי הוא ההסבר
לכך שאין ערך ולא ערך בעצמו. הסיבה: ה-buffer חסום בגודל (``PROFILER_MAX_BUFFER_SIZE``)
ולא בגיל, ולכן ערך שהיה יושב בו לא היה נשמע ל-TTL בכלל. **לא בלוגים:** שורת
``slow_query_detected`` ממשיכה לשאת את השלד, כי הלוג עוזב לספק וה-DB לא. שני
מסלולי הקריאה, מה-DB ומהזיכרון, בודקים את הרשימה העדכנית, ולכן הסרת משתמש ממנה
מסתירה את הערכים מיד בשניהם. ותשובת ה-explain מנרמלת את השאילתה בעצמה, ולכן הדוח
שמודבק ל-AI מכיל את השלד גם כשהניתוח רץ על הערכים האמיתיים.

POST /api/profiler/explain
^^^^^^^^^^^^^^^^^^^^^^^^^^^

מריץ Explain Plan על שאילתה או Aggregation Pipeline.

**Body (Query):**

.. code-block:: json

   {
     "collection": "code_snippets",
     "query": {"user_id": "123", "is_deleted": false},
     "verbosity": "queryPlanner"
   }

**Body (Pipeline):**

.. code-block:: json

   {
     "collection": "code_snippets",
     "pipeline": [
       {"$match": {"user_id": "123"}},
       {"$group": {"_id": "$language", "count": {"$sum": 1}}}
     ],
     "verbosity": "queryPlanner"
   }

**דוגמה:**

.. code-block:: bash

   curl -X POST \
        -H "X-Profiler-Token: $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"collection":"code_snippets","query":{"user_id":"<value>"}}' \
        https://your-app.com/api/profiler/explain

POST /api/profiler/recommendations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

מחזיר Explain Plan + המלצות אופטימיזציה:

.. code-block:: bash

   curl -X POST \
        -H "X-Profiler-Token: $TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"collection":"code_snippets","query":{"user_id":"<value>"}}' \
        https://your-app.com/api/profiler/recommendations

GET /api/profiler/collection/<name>/stats
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

מחזיר סטטיסטיקות collection:

.. code-block:: bash

   curl -H "X-Profiler-Token: $TOKEN" \
        https://your-app.com/api/profiler/collection/code_snippets/stats

**Response:**

.. code-block:: json

   {
     "status": "success",
     "data": {
       "size_bytes": 1048576,
       "count": 5000,
       "avg_obj_size": 210,
       "index_count": 3,
       "indexes": ["_id_", "user_id_1", "user_id_1_is_deleted_1"],
       "total_index_size": 524288
     }
   }

Security
--------

Authentication
~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - שכבה
     - משתנה/מנגנון
     - תיאור
   * - Token
     - ``PROFILER_AUTH_TOKEN``
     - ב-Flask אינו מחליף סשן אדמין; ב-aiohttp נבדק ישירות כשהוא מוגדר
   * - IP Allowlist
     - ``PROFILER_ALLOWED_IPS``
     - רשימת IPs מורשים (CSV)
   * - Rate Limit
     - ``PROFILER_RATE_LIMIT``
     - מגבלת בקשות לדקה (ברירת מחדל: 60)
   * - Admin Session
     - WebApp
     - **נדרשת תמיד במסלולי Flask** — גם כשמוגדר Token; אינה חלה על מסלולי aiohttp

הגדרת Token
~~~~~~~~~~~~

.. code-block:: bash

   # .env
   PROFILER_AUTH_TOKEN=my-secure-profiler-token
   PROFILER_ALLOWED_IPS=127.0.0.1,10.0.0.1

אזהרת Observer Effect
-----------------------

.. warning::
   **Observer Effect** – הרצת ``explain("executionStats")`` או ``explain("allPlansExecution")`` **מריצה את השאילתה בפועל!**

   **הסיכונים:**

   - אם השאילתה איטית כי היא מעמיסה על ה-CPU, הרצת ה-Explain תכפיל את העומס
   - אם השאילתה נועלת מסמכים (write operations), זה עלול להחמיר את המצב
   - ב-Production עמוס, הרצה אוטומטית של explain יכולה ליצור "אפקט שלג"

**המלצות:**

1. **השתמש ב-``queryPlanner`` כברירת מחדל** – לא מריץ את השאילתה, רק מציג את התוכנית
2. **הרץ ``executionStats`` רק לפי דרישה** – כפי שממומש בכפתור "נתח" בדשבורד
3. **אל תריץ explain אוטומטית לכל שאילתה איטית** – זה יכפיל את הבעיה
4. **שקול הרצת explain בשעות שפל** או על replica secondary

.. list-table:: רמות Verbosity
   :header-rows: 1

   * - רמה
     - תיאור
     - מתי להשתמש
   * - ``queryPlanner``
     - תוכנית בלבד, ללא הרצה
     - לבדיקת אינדקסים (בטוח)
   * - ``executionStats``
     - כולל סטטיסטיקות ביצוע
     - ניתוח ביצועים מלא
   * - ``allPlansExecution``
     - כל התוכניות שנבחנו
     - Debug מתקדם בלבד

Privacy / PII
-------------

.. important::
   **נרמול שאילתות מונע דליפת מידע אישי (PII)**

הפונקציה ``_normalize_query_shape`` מחליפה את כל הערכים בפלייסהולדרים:

- ערכים פשוטים → ``<value>``
- מערכים → ``<N items>``
- null → ``<null>``

**דוגמה:**

.. code-block:: python

   # Query מקורי (לא מוצג)
   {"email": "john@example.com", "status": {"$in": ["active", "pending"]}}

   # Query מנורמל (מה שמוצג בדשבורד)
   {"email": "<value>", "status": {"$in": ["<2 items>"]}}

.. warning::
   **אל תתעד או תציג דוגמאות עם נתוני אמת/PII בדוחות או בלוגים.**

Persistence
-----------

Collection
~~~~~~~~~~

שם: ``slow_queries_log``

שלושת האינדקסים שלהלן נוצרים על ידי ``DatabaseManager._create_profiler_indexes``,
שרצה כחלק מיצירת האינדקסים בעליית התהליך. הכתיבה עצמה נעשית סינכרונית
מתוך ה-``CommandListener`` של pymongo — ראו :doc:`asyncio-loop-safety`.

TTL Index
~~~~~~~~~

מחיקה אוטומטית אחרי **7 ימים**:

.. code-block:: javascript

   db.slow_queries_log.createIndex(
     {"timestamp": 1},
     {expireAfterSeconds: 604800, name: "ttl_cleanup"}
   )

אינדקסים נוספים
~~~~~~~~~~~~~~~~

שני אלה משרתים את ``get_slow_queries`` — הקוראת של **הראוט של הבוט** — שממיינת
**תמיד** לפי ``execution_time_ms`` יורד, עם סינון אופציונלי לפי ``collection``.

.. warning::

   הם **אינם** משרתים את טבלת הדשבורד. היא עברה ל-``get_slow_queries_page``,
   ששאילתתה נושאת תמיד טווח על ``timestamp`` (חלון הזמן) — וטווח בתחילית שובר
   את סדר המיון, כלל ה-ESR. כלומר המיון שם נעשה בזיכרון בכל מקרה, ושני
   האינדקסים האלה אינם מונעים ממנו דבר. ראו את ההערה בסוף הסעיף.

.. code-block:: javascript

   // ברירת המחדל של הדשבורד: בלי סינון, ממוין לפי משך יורד
   db.slow_queries_log.createIndex(
     {"execution_time_ms": -1},
     {name: "slow_queries_duration"}
   )

   // סינון לפי collection עם אותו מיון (Equality ← Sort)
   db.slow_queries_log.createIndex(
     {"collection": 1, "execution_time_ms": -1},
     {name: "slow_queries_coll_dur"}
   )

.. note::

   גרסאות קודמות של העמוד הבטיחו ``collection_timestamp`` ו-``query_pattern``.
   שניהם **אינם נוצרים**, ומכאן ואילך משתי סיבות שונות.

   ``query_pattern`` — אין לו קורא. ``query_id`` רק נכתב ומוצג
   (``get_pattern_statistics`` מקבצת לפיו ב-``$group``, וזה לא משתמש באינדקס),
   ואינדקס בלי קורא עולה בכל כתיבה ולא מחזיר דבר.

   ``collection_timestamp`` — הטבלה **כן** ממיינת לפי ``timestamp`` מאז שנוסף
   המיון בעמודות, והאינדקס עדיין לא נוצר. חשוב להפריד בין שני דברים שקל לערבב:

   * **את המיון הוא לא היה מספק.** המיון מלווה תמיד בטווח על ``timestamp``,
     וטווח בתחילית שובר את סדר המיון (ESR). ארבעת שדות המיון האפשריים היו
     דורשים ארבעה אינדקסים, ואף אחד מהם לא היה מונע את המיון בזיכרון.
   * **את הסריקה הוא **כן** היה מצמצם** במסלול שבו נשלח ``collection`` —
     שם זה Equality ← Range. זה מסלול משני בדשבורד (ברירת המחדל היא בלי
     סינון), ולכן הוא לא נוצר; זו החלטה, לא היעדר תועלת.

   **המספרים הם מדידה ולא תקרה:** נמדד ב-``executionStats`` על מצב האוסף
   בזמן המדידה (225 רשומות) — כ-59KB במיון לפי משך וכ-40KB לפי זמן, מול מגבלת
   המיון החוסם של מונגו (32MB), בלי spill. ה-TTL של שבעה ימים והסף של שנייה
   **מגבילים** את הגידול ואינם חוסמים אותו: פרץ שאילתות איטיות בתוך אותו חלון
   יכול להיות גדול בהרבה, ואז המספרים האלה אינם מייצגים. שווה למדוד שוב אם
   נפח האוסף משתנה בסדר גודל.

Metrics (Prometheus)
--------------------

מטריקות זמינות כאשר ``PROFILER_METRICS_ENABLED=true``:

.. list-table::
   :header-rows: 1

   * - Metric
     - Type
     - תיאור
   * - ``mongodb_slow_queries_total``
     - Counter
     - מספר שאילתות איטיות לפי collection ו-operation
   * - ``mongodb_query_duration_seconds``
     - Histogram
     - התפלגות זמני שאילתות
   * - ``mongodb_collscan_detected_total``
     - Counter
     - מספר COLLSCAN שזוהו
   * - ``query_profiler_buffer_size``
     - Gauge
     - מספר שאילתות בבאפר הזיכרון

Environment Variables
---------------------

ראו את הטבלה המלאה ב-:doc:`../environment-variables`.

.. list-table::
   :header-rows: 1
   :widths: 30 50 20

   * - משתנה
     - תיאור
     - ברירת מחדל
   * - ``PROFILER_ENABLED``
     - הפעלת Query Performance Profiler
     - ``true``
   * - ``PROFILER_SLOW_THRESHOLD_MS``
     - סף זמן (ms) להגדרת "שאילתה איטית"
     - ``100``
   * - ``PROFILER_MAX_BUFFER_SIZE``
     - מספר שאילתות בזיכרון
     - ``1000``
   * - ``PROFILER_AUTH_TOKEN``
     - טוקן גישה (Header ``X-Profiler-Token``)
     - (ריק)
   * - ``PROFILER_ALLOWED_IPS``
     - Allowlist של IPs (CSV)
     - (ריק)
   * - ``PROFILER_RATE_LIMIT``
     - מגבלת בקשות לדקה
     - ``60``
   * - ``PROFILER_METRICS_ENABLED``
     - הפעלת מטריקות Prometheus
     - ``true``

המלצות אופטימיזציה נפוצות
--------------------------

.. list-table::
   :header-rows: 1

   * - בעיה
     - סימפטום
     - המלצה
   * - 🔴 COLLSCAN
     - ``stage: "COLLSCAN"``
     - צור אינדקס על שדות הסינון
   * - 🟠 Sort בזיכרון
     - ``stage: "SORT"``
     - הוסף שדה מיון לאינדקס
   * - 🟡 יחס יעילות נמוך
     - ``docsExamined >> nReturned``
     - שפר selectivity של האינדקס
   * - 🔴 $lookup ללא אינדקס
     - ``nestedLoopJoin``
     - צור אינדקס על ה-foreign field
   * - 🟠 $sort משתמש בדיסק
     - ``usedDisk: true``
     - הוסף $match לפני ה-$sort

קישורים נוספים
---------------

- :doc:`../environment-variables` – טבלת משתני סביבה מלאה
- :doc:`observability_dashboard` – דשבורד Observability
- :doc:`background-jobs-monitor` – מוניטור Jobs
- `MongoDB Explain Documentation <https://www.mongodb.com/docs/manual/reference/command/explain/>`_
- `MongoDB Index Strategies <https://www.mongodb.com/docs/manual/applications/indexes/>`_
