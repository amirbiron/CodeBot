דפדפן קוד (Code Browser)
=========================
:summary: ייבוא של ריפו מ-GitHub לצפייה ולניווט בוובאפ, סנכרון אוטומטי שלו דרך webhook, ותצוגת ה-Markdown של קבצים: מאיפה נטענות הספריות שלה, והעיצוב המשותף עם כרטיסי החיפוש בתיעוד.

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
- **העיצוב** יושב ב-``webapp/static/css/markdown-preview.css``, ששני המקומות טוענים. ווי הדריסה של ערכות מיובאות לבלוקי הקוד מתוארים ב-:ref:`theme-variables-repo-md-code-block-hook`.

ראו גם
------

- :doc:`/repository-integrations`
- :doc:`/webapp/overview`
