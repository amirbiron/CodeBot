.. _db-indexing-cookbook:

MongoDB Indexing Cookbook
=========================
:summary: ספר מתכונים לאינדקסים ב-MongoDB: אילו אינדקסים מומלצים, מתכוני PyMongo, קריאת explain, ובדיקת קיום אינדקסים.

למה?
-----
- **ביצועים**: אינדקס נכון מקטין זמן תגובה ועומס CPU/IO.
- **מיון יעיל**: מאפשר ``sort`` מהיר ללא ``in-memory sort``.
- **סקלביליות**: מונע ``COLLSCAN`` יקר כשמאגר הנתונים גדל.

אינדקסים מומלצים
-----------------
הדוגמאות מתייחסות לקולקציה לדוגמה בשם ``code_snippets`` (התאימו לשם אצלכם):

- ``(user_id, created_at)`` – לדפדוף כרונולוגי לפי משתמש.
- ``(user_id, programming_language)`` – לסינון לפי שפה.
- ``(user_id, tags)`` – שדה מערך; מזרז סינון לפי תגיות.
- ``(user_id, is_favorite)`` – סינון מועדפים למשתמש.
- אינדקס ``text`` על ``file_name``, ``description``, ``tags`` – לחיפוש טקסט.

מתכונים (Python / PyMongo)
---------------------------
.. code-block:: python

   from pymongo import ASCENDING, DESCENDING

   coll = db["code_snippets"]

   coll.create_index([
       ("user_id", ASCENDING), ("created_at", DESCENDING)
   ], name="user_created_at", background=True)

   coll.create_index([
       ("user_id", ASCENDING), ("programming_language", ASCENDING)
   ], name="user_lang", background=True)

   coll.create_index([
       ("user_id", ASCENDING), ("tags", ASCENDING)
   ], name="user_tags", background=True)

   coll.create_index([
       ("user_id", ASCENDING), ("is_favorite", ASCENDING)
   ], name="user_favorite", background=True)

   coll.create_index([
       ("file_name", "text"), ("description", "text"), ("tags", "text")
   ], name="text_file_desc_tags", background=True)

בדיקות explain (Mongo Shell)
----------------------------
.. code-block:: javascript

   // newer -> older feed for a given user
   db.code_snippets
     .find({ user_id: 123 })
     .sort({ created_at: -1 })
     .limit(20)
     .explain('executionStats')

מה לחפש ב-explain?
-------------------
- **stage**: עדיף לראות ``IXSCAN`` (סריקת אינדקס) ולא ``COLLSCAN``.
- **totalDocsExamined / totalKeysExamined**: מספרים נמוכים מצביעים על שימוש יעיל באינדקס.
- **executionTimeMillis**: צריך לרדת משמעותית אחרי הוספת אינדקסים נכונים.
- **sortPattern**: וודאו שהמיון נתמך ע"י האינדקס (ללא ``SORT`` נוסף).

בדיקת קיום אינדקסים
--------------------
.. code-block:: javascript

   // Mongo shell
   db.code_snippets.getIndexes()

.. code-block:: python

   # PyMongo
   coll.index_information()

מהדפדפן, בלי טרמינל: ``/admin/verify-indexes`` (אדמין) מחזיר את האינדקסים של הקולקציות הקריטיות, ובסעיף ``recycle_bin_ttl`` — האם אינדקס ה-TTL של סל המיחזור קיים ותואם למפרט, וכמה פריטים שתאריכם עבר עדיין יושבים בסל.

.. _db-behavior-indexes:

אינדקסים שהם התנהגות, לא אופטימיזציה
--------------------------------------
רוב העמוד הזה עוסק במהירות, ואינדקס מהירות שחסר הוא איטיות. שני סוגים אינם כאלה:

- **TTL** (``expireAfterSeconds``) — מונגו מוחק בעזרתו מסמכים בצד השרת. בלעדיו הנתונים פשוט נשארים, בלי שגיאה ובלי אזהרה.
- **ייחודי** (``unique``) — הוא מה שדוחה כפילות. בלעדיו הכפילות נכתבת.

ולכן:

- אינדקס כזה מוצהר **במסלול שרץ בכל עלייה** (``DatabaseManager._create_indexes``), ולא רק בסקריפט חד-פעמי או בפקודת אדמין. מסד חדש, או שחזור אחרי הפלת חירום, מקבלים רק את מה שהעלייה יוצרת.
- ``safe_create_index`` אינו זורק; כשל חוזר כ-``False``. באינדקס של התנהגות בודקים את הערך ומדווחים עליו, כמו ``_create_recycle_bin_ttl_indexes`` ששולח ``db_recycle_bin_ttl_index_missing``.
- טסט מקבע שמסלול העלייה מבקש את האינדקס במפרט המלא — ראו ``tests/test_recycle_bin_ttl_index.py``.
- מי שמצמצם את רשימת האינדקסים "לאופטימלית" שואל איזו שאילתה כל אחד מאיץ. ל-TTL ול-``unique`` אין שאילתה, ולכן הם הראשונים שנופלים מרשימה כזו. כך נעלם אינדקס ה-TTL של סל המיחזור, והסל הפסיק להתרוקן.
- **ביצירה ראשונה של TTL — וגם אחרי כל פער שבו הוא חסר — מונגו מוחק בבת אחת את כל מה שכבר פג** (`TTL Indexes <https://www.mongodb.com/docs/manual/core/index-ttl/>`_). ההחלטה אם זה רצוי נכתבת בקוד, ליד היצירה.

שיטות עבודה מומלצות
--------------------
- **התאימו את סדר העמודות** באינדקס לסדר הסינון והמיון בפועל (prefix rule).
- **מיון יציב**: אם אתם ממיינים לפי ``created_at`` הוסיפו גם ``_id`` בסוף בעת צורך.
- **Text Index יחיד**: ב-MongoDB יש בדרך כלל אינדקס טקסט יחיד לכל קולקציה; רכזו שדות יחד.
- **הימנעו מאינדקסים מיותרים**: כל אינדקס עולה בזיכרון ובכתיבה; מדדו לפני ואחרי.
- **Array Fields**: אינדקס עולה על כל ערך במערך; טוב ל-``tags``.
- **התאימו לשאילתות אמיתיות**: הסתכלו ב-logs/metrics ובנו אינדקסים לפי העומס.

דוגמאות נוספות
---------------
.. code-block:: javascript

   // חיפוש לפי תגיות + מיון חדש -> ישן
   db.code_snippets
     .find({ user_id: 123, tags: 'flask' })
     .sort({ created_at: -1, _id: -1 })
     .limit(20)
     .explain('executionStats')

   // חיפוש טקסטואלי
   db.code_snippets
     .find({ $text: { $search: 'pagination cursor' } })
     .project({ score: { $meta: 'textScore' } })
     .sort({ score: { $meta: 'textScore' }, created_at: -1 })
     .limit(20)
     .explain('executionStats')

Gotchas נפוצים
--------------
- **סדר מיון לא תואם לאינדקס** יגרום ל-``SORT`` יקר בזיכרון.
- **Text Index קיים**: אי אפשר ליצור שני אינדקסים טקסטואלים שונים על אותה קולקציה.
- **Regex עם Wildcard בתחילה** (``/^.*abc/``) לא ינצל אינדקס רגיל.
- **סינון על שדה לא ממופתח** יגרור ``COLLSCAN`` גם אם המיון ממופתח.
- **שינוי סכימה**: אם שדות עוברים שינוי שם, עדכנו גם את האינדקסים.
