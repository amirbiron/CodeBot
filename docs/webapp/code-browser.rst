דפדפן קוד (Code Browser)
=========================

דפדפן הקוד מאפשר צפייה וניווט בריפוזיטורים מ-GitHub ישירות בממשק ה-WebApp.

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
        - ``https://<הדומיין של קודבוט>/api/webhooks/github``
      * - **Content type**
        - ``application/json``
      * - **Secret**
        - אותו ערך שמוגדר ב-``GITHUB_WEBHOOK_SECRET`` בסביבה שלכם
      * - **Events**
        - בחרו **Just the push event**

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

ראו גם
------

- :doc:`/repository-integrations`
- :doc:`/webapp/overview`
