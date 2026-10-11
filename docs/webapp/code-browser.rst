:summary: ייבוא ריפו מ-GitHub לדפדפן הקוד וסנכרון אוטומטי שלו דרך webhook, תצוגת ה-Markdown של קבצים — הספריות שלה והעיצוב המשותף עם כרטיסי החיפוש בתיעוד — ולמה הקובץ מוצג בדיוק כמו בריפו, ומי רשאי לראות אותו.

דפדפן קוד (Code Browser)
=========================

ייבוא ריפו חדש
--------------

כדי לייבא ריפוזיטורי חדש לדפדפן הקוד, יש להריץ את הפקודה הבאה (אפשר להריץ ב-Shell של Render):

.. code-block:: python

   python3 - <<'PY'
   from services.repo_sync_service import initial_import
   from database.db_manager import get_db

   res = initial_import("<קישור לריפו.git>", "שם הריפו", get_db())
   print(res)
   PY

.. note::
   יש להחליף את ``<קישור לריפו.git>`` בכתובת ה-Git של הריפו (למשל ``https://github.com/user/repo.git``)
   ואת ``"שם הריפו"`` בשם שיוצג בממשק.

הגדרת סנכרון אוטומטי
--------------------

לאחר ביצוע ``initial_import``, יש להגדיר Webhook ב-GitHub כדי שהמערכת תסנכרן שינויים אוטומטית.

הגדרת Webhook ב-GitHub
^^^^^^^^^^^^^^^^^^^^^^

1. כנסו לריפו ב-GitHub
2. לכו ל-**Settings** → **Webhooks** → **Add webhook**
3. מלאו את הפרטים הבאים:

   .. list-table::
      :widths: 30 70
      :header-rows: 1

      * - שדה
        - ערך
      * - **Payload URL**
        - ``https://<הדומיין של ה-וובאפפ>/api/webhooks/github``
      * - **Content type**
        - ``application/json``
      * - **Secret**
        - אותו ערך שמוגדר ב-``GITHUB_WEBHOOK_SECRET`` בסביבה שלכם
      * - **Events**
        - בחרו **Just the push event**. בריפו של CodeBot עצמו בחרו **Let me select individual events**, וסמנו גם את ``deployment_status`` לצד ``push``: הוא מפעיל את אינדקס התיעוד אחרי כל פריסה של האתר (:ref:`docs-index`)

4. לחצו **Add webhook**

.. warning::
   ודאו שה-Secret תואם בדיוק לערך שמוגדר ב-``GITHUB_WEBHOOK_SECRET`` בשרת.
   אם הערכים לא תואמים, ה-Webhook ייכשל עם שגיאת אימות.

בדיקת הגדרת ה-Webhook
^^^^^^^^^^^^^^^^^^^^^

לאחר הגדרת ה-Webhook:

1. בצעו ``git push`` לריפו
2. כנסו ל-**Settings** → **Webhooks** ב-GitHub ובדקו את סטטוס המשלוח האחרון
3. סטטוס 200 מעיד על הצלחה
4. ודאו שהקבצים עודכנו בדפדפן הקוד

משתני סביבה נדרשים
------------------

.. list-table::
   :widths: 35 65
   :header-rows: 1

   * - משתנה
     - תיאור
   * - ``GITHUB_WEBHOOK_SECRET``
     - הסוד המשותף לאימות Webhooks מ-GitHub

.. _code-browser-markdown-preview:

תצוגת Markdown
--------------

קובץ ``.md`` בדפדפן הקוד אפשר לראות מרונדר, בכפתור "תצוגת Markdown" שבראש הקובץ. הרינדור הוא ``MarkdownLiveRenderer`` (``webapp/static/js/live-preview.js``), ואותו רינדור משמש גם את כרטיסי החיפוש בתיעוד בעמוד הקבצים (:ref:`global-search-docs`).

- **הספריות מגיעות מהבאנדל המקומי, בכוונה.** ``webapp/static/js/markdown-deps.js`` טוען ישירות את ``md_preview.bundle.js``, ולא את markdown-it ו-highlight.js מ-CDN. markdown-it מ-CDN מגיע בלי התוספים, והתצוגה הייתה מאבדת הערות ותרשימים בלי שום שגיאה. הבאנדל גדול, ולכן הוא נטען רק כשצריך אותו, ואחר כך מגיע מהמטמון עד שהגרסה משתנה.
- **הכתובת של הבאנדל נגזרת מהתגית של הטוען**: אותה תיקייה ואותו ``?v=``. כך עדכון של הבאנדל מגיע לדפדפן יחד עם הקוד שטוען אותו, גם אחרי שנה במטמון. אין כתובת בלי גרסה כגיבוי.
- **הדדליין של הטעינה** (``BUNDLE_DEADLINE_MS``) נגזר ממדידה של הבאנדל ברשת איטית, ולא נועד לקצר המתנה איטית. הוא שם כדי שבקשה שנתקעה לא תחזיק את התצוגה לנצח. טעינה שנכשלה מנוסה מחדש, בבקשה חדשה, בפעם הבאה שצריך את הבאנדל.
- **העיצוב** יושב ב-``webapp/static/css/markdown-preview.css``, שדפדפן הקוד וכרטיסי החיפוש בתיעוד טוענים. הגבולות וההדגשה נקראים בו דרך טוקנים של הרכיב ולא ישירות מהפלטה של דפדפן הקוד, כי עמוד הקבצים לא טוען אותה — הכלל ב-:doc:`theming_and_css`. ווי הדריסה של ערכות מיובאות לבלוקי הקוד מתוארים ב-:ref:`theme-variables-repo-md-code-block-hook`.

.. _code-browser-content-as-is:

התוכן כמו שהוא בריפו, ומי רואה אותו
-------------------------------------

**הקובץ מוצג תו בתו כמו שהוא במראה.** ``/repo/api/file/<path>`` קורא אותו ב-``get_file_content``, כלומר ``git show`` דרך ``_run_git_command`` (``services/git_mirror_service.py``), והפלט חוזר בלי שינוי. אותו תוכן ממלא את טופס ההעלאה ב"ערוך / העתק" (``/upload/from-repo``), ואותו תוכן האינדקס של הריפו (``repo_files``) קורא כשהוא מחשב ``size`` ו-``lines``. "תו בתו" כולל את סופי השורות: ``_run_git_command`` קורא את הפלט כבתים ומפענח אותו ב-UTF-8, כך ש-CRLF של קובץ Windows מגיע כמו שהוא. תצוגת ההיסטוריה (``/repo/api/file-at-commit``) קוראת במסלול אחר, ``get_file_at_commit``, ומקבלת את אותו טקסט לכל קובץ UTF-8 בלי BOM. ``_try_decode_content`` שבמסלול ההוא מסיר BOM ומציג גם קובץ שאינו UTF-8, וקובץ כזה ``get_file_content`` לא מציג.

- **אין צנזור על התוכן.** ``_run_git_command`` מעביר ב-``_sanitize_output`` רק את ה-stderr של git ואת הפקודה שנכתבת ללוג, כי שם git מדפיס את ה-URL כשפקודת רשת נכשלת. ה-stdout הוא הנתונים עצמם, ושינוי שלו משבש את מה שמוצג. עד אוקטובר 2026 גם הוא עבר בניקוי, והקובץ הוצג משובש — ההסבר ברשומה של 11.10.2026 ב-:doc:`/whats-new`.
- **מי רואה: אדמין בלבד.** כל הנתיבים תחת ``/repo/`` חסומים ב-``_require_admin_for_repo_browser`` (``before_request`` של ה-blueprint ב-``webapp/routes/repo_browser.py``), ו"ערוך / העתק" ב-``admin_required``. במצב התחזות שניהם חסומים, כמו כל עמוד אדמין.
- **אין חסימה לפי נתיב, בכוונה.** ``.env`` או ``*.pem`` שנכנסו לריפו מוצגים לאדמין כמו כל קובץ אחר: זה הריפו שלו, והוא רואה אותו גם ב-GitHub. בכלי הריפו של ה-MCP יש חסימה כזו (:ref:`mcp-secrets-policy`), כי שם התוכן עובר לסוכן AI.
- **הגודל ומספר השורות בעץ מגיעים מהאינדקס, ולא מהקובץ.** ערך שנשמר לפני התיקון מתעדכן כשהקובץ משתנה, או מיד בהרצה חוזרת של ``initial_import`` לריפו — הפקודה ב"ייבוא ריפו חדש" למעלה. ``initial_import`` על מראה שכבר קיימת לא מושך מ-GitHub, אלא מאנדקס מחדש את מה שכבר במראה.

ראו גם
------

- :doc:`/repository-integrations`
- :doc:`/webapp/overview`
