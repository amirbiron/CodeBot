Clean Architecture ב-src
========================

למה Clean Architecture
----------------------
ארכיטקטורה זו מפרידה בין לוגיקה עסקית, תזמור יישומי ותשתיות כך שניתן לבדוק יחידות קוד בנפרד, להחליף מקורות נתונים בלי לשבור את שאר המערכת ולרוץ גם בסביבות ללא MongoDB.

תרשים שכבות
------------
.. mermaid::

   graph TD
     U[Handlers / WebApp] --> A[Application Layer]
     A --> D[Domain Layer]
     A --> I[Infrastructure Layer]
     I --> DB[(MongoDB)]
     I --> Files[(Legacy DB Facade)]

מבנה תיקיות
------------

.. code-block:: text

   src/
     domain/
       entities/snippet.py
       services/code_normalizer.py
       services/language_detector.py
       interfaces/snippet_repository_interface.py
     application/
       dto/create_snippet_dto.py
       services/snippet_service.py
     infrastructure/
       database/mongodb/repositories/snippet_repository.py
       composition/container.py
       composition/files_facade.py

שכבת הדומיין (Domain)
----------------------
* `domain/entities/snippet.py` מגדיר ישות קלה (dataclass) שאינה תלויה ב-DB או ב-Telegram.
* `domain/services/code_normalizer.py` מנרמל קוד (BOM, תווים נסתרים, CRLF→LF) כך שכל צרכן יקבל תוכן נקי.
* `domain/services/language_detector.py` מזהה שפה באמצעות שם קובץ ותוכן, כולל Shebangs, קבצי Markdown/YAML ועוד.
* `domain/interfaces/snippet_repository_interface.py` מצהיר על API לשכבת נתונים (save/get/search) כדי שהדומיין לא יכיר MongoDB.

שכבת היישום (Application)
-------------------------
* `application/dto/create_snippet_dto.py` מרכז ולידציה בסיסית עבור פקודות יצירת סניפט.
* `application/services/snippet_service.py` מתזמר את התהליך: מקבל DTO, מפעיל את `CodeNormalizer`, מבצע זיהוי שפה, בונה `Snippet` ושומר דרך הממשק הדומייני.
* הלוגיקה כאן "דקה" – אין קריאות Telegram או MongoDB, רק שימוש באובייקטים שהוזרקו.

שכבת התשתית (Infrastructure)
-----------------------------
* `infrastructure/database/mongodb/repositories/snippet_repository.py` מממש את הממשק הדומייני באמצעות `DatabaseManager` ו-`CodeSnippet` הקיימים.
* `infrastructure/composition/container.py` הוא Composition Root שמבנה Singleton של `SnippetService`, מזריק Normalizer, Detector ומחבר ל-Repository.
* `infrastructure/composition/files_facade.py` מספק שכבת מעבר עבור מודולים שעדיין נשענים על מנגנון ה-DB הישן.

דוגמת זרימה: יצירת סניפט
------------------------
1. Handler קורא ל-`get_snippet_service()` מה-Container.
2. הקריאה `create_snippet(dto)` מנרמלת קוד, מזהה שפה ומייצרת Entity.
3. ה-Repository מתרגם את ה-Entity ל-`CodeSnippet` ושומר ב-MongoDB.
4. התוצאה שחזרה לשכבות העליונות היא אובייקט דומיין עקבי (כולל גרסה ומטא-דאטה מעודכן).

הנחיות עבודה
-------------
* להוספת Use Case חדש – התחילו ב-Domain (ישות/שירות), צרו Service/Application שירכיב את הזרימה ואז חברו דרך התשתית.
* בדיקות יחידה מומלצות לרוץ על שכבת הדומיין והיישום עם Doubles (ללא DB אמיתי).
* בחיבור לפיצ'רים קיימים, העדיפו להשתמש ב-`container.get_snippet_service()` על פני יבוא ישיר של Database Manager.
