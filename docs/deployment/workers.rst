עובדי Push
===========

ל-Code Keeper Bot יש שני מסלולים לשליחת Web Push:

1. **מסלול מקומי (ברירת מחדל)** – ה-WebApp שולח ישירות עם ``pywebpush``. זה המסלול הפעיל בפרודקשן.
2. **Node Push Worker** (``/push_worker``) – תהליך נפרד שרץ לצד הבוט (Render/Docker/VM), למי שרוצה להפריד את המפתח הפרטי מתהליך ה-Flask.

העמוד מסביר איך לפרוס ולחבר אותם אל ה-WebApp (``webapp/push_api.py``) בצורה מאובטחת.

.. contents::
   :local:
   :depth: 2

.. warning::

   **Cloudflare Workers אינו נתמך לשליחת Web Push.**

   בעבר הייתה בריפו תיקיית ``worker/`` עם Cloudflare Worker. היא הוסרה, כי
   ספריית ``web-push`` נשענת על ``https.request`` מ-Node, ובסביבת Workers זהו
   stub שזורק מיד::

      [unenv] https.request is not implemented yet!

   התוצאה: ה-Worker החזיר 502 על כל שליחה, בלי שאף בקשת רשת יצאה. הוספת
   ``nodejs_compat`` אינה פותרת את זה. מי שרוצה בכל זאת שולח Edge חייב לממש
   את פרוטוקול Web Push ישירות מול Web Crypto API ו-``fetch`` — לא דרך
   ``web-push``.

מסלול מקומי (pywebpush)
------------------------

זהו ברירת המחדל, ואין צורך בשום רכיב נוסף. נדרש רק:

.. code-block:: bash

   PUSH_REMOTE_DELIVERY_ENABLED=false
   VAPID_PUBLIC_KEY=<base64url>
   VAPID_PRIVATE_KEY=<base64url>
   VAPID_SUB_EMAIL=support@example.com

לאחר שינוי משתני הסביבה יש לבצע **restart** לשירות כדי שייקלטו.

Node Push Worker (``/push_worker``)
------------------------------------

- נכתב ב-Express (``index.js``) ומאזין כברירת מחדל על ``127.0.0.1:8080``.
- מיועד לרוץ כחלק מ-``scripts/start_with_worker.sh`` או כ-Container נפרד. הסקריפט טוען ``.env.worker`` כדי למנוע הדלפת מפתחות VAPID לתהליך הראשי.
- נתיבים:

  - ``GET /healthz`` – בדיקת חיים (משמשת את סקריפט ה-start להמתין ל-ready).
  - ``POST /send`` – מקבל ``{subscription, payload, options}`` ב-JSON.

- משתני סביבה:

  - ``PORT`` – ברירת מחדל 8080; הסקריפט מגדיר אוטומטית ``PUSH_WORKER_PORT``.
  - ``PUSH_DELIVERY_TOKEN`` – תואם לחלק השרת.
  - ``WORKER_VAPID_PUBLIC_KEY``, ``WORKER_VAPID_PRIVATE_KEY``, ``WORKER_VAPID_SUB_EMAIL`` – עדיפות ראשונה; נופל חזרה ל-``VAPID_*`` אם חסר.

- אבטחה:

  - השוואת Bearer מתבצעת ב-constant time בעזרת ``crypto.timingSafeEqual``.
  - ה-Worker מאזין רק ל-localhost כדי למנוע גישה חיצונית. לפריסה ב-Kubernetes/Compose חשפו רק דרך Service פנימי.

.. note::

   ``scripts/start_with_worker.sh`` מפעיל את ה-Worker רק כאשר
   ``PUSH_REMOTE_DELIVERY_ENABLED`` דלוק. שירות שרץ עם ``scripts/start_webapp.sh``
   (למשל ``code-keeper-webapp`` ב-Render) **אינו** מריץ sidecar כלל, ולכן שם
   המסלול המקומי הוא היחיד שזמין.

חיבור ל-WebApp (``webapp/push_api.py``)
----------------------------------------

כדי להפעיל משלוח דרך Worker חיצוני:

1. הגדירו ב-WebApp את המשתנים הבאים:

   .. code-block:: bash

      PUSH_REMOTE_DELIVERY_ENABLED=true
      PUSH_DELIVERY_URL=https://push-worker.example.com
      PUSH_DELIVERY_TOKEN=super-secret-token

2. אם עובדים מול Worker מקומי (באמצעות ``start_with_worker.sh``):

   - קבעו ``PUSH_WORKER_PORT`` (ברירת מחדל 18080).
   - מלאו את ``.env.worker`` עם המפתחות הייעודיים.
   - הסקריפט ימתין ל-``/healthz`` עד 6 שניות ויעדכן ``PUSH_DELIVERY_URL`` ל-``http://127.0.0.1:<port>`` אם לא סופק ערך.

.. danger::

   **אין להשתמש בזוגות VAPID שונים בין השרת ל-Worker.**

   מנוי בדפדפן נקשר למפתח הציבורי שאיתו הוא נוצר. אם השליחה נחתמת במפתח
   פרטי מזוג אחר, שירות הפוש דוחה אותה ב-403 וההתראה לא מגיעה — בלי שום
   שגיאה גלויה בצד הלקוח.

   שימו לב ש-``_coerce_vapid_pair()`` נותן עדיפות ל-``WORKER_VAPID_*`` על פני
   ``VAPID_*``, כולל במפתח שמוחזר ללקוח ב-``/api/push/public-key``. לכן הוספת
   ``WORKER_VAPID_PUBLIC_KEY`` לסביבת ה-WebApp **משנה את המפתח שהדפדפן נרשם
   איתו**, ומשביתה בשקט את כל המנויים הקיימים. אחרי כל החלפת מפתחות יש למחוק
   את המנויים הישנים ולהירשם מחדש.

בדיקות ועצות
-------------

- **בדיקת אינטגרציה** – הריצו ``curl -X POST $PUSH_DELIVERY_URL/send`` עם Bearer Token כדי לוודא את ה-Worker לפני שמפעילים את ה-WebApp.
- **בדיקת לקוח** – השתמשו ב-``POST /api/push/test`` (נדרש session) כדי לשלוח פוש לדפדפן שלכם ולקבל פלט JSON עם ``sent`` ומערך ``errors`` מפורט. דף ``/settings/push-debug`` עוטף את זה בממשק.
- **פענוח שגיאות** – ``403``/``401`` מעידים על אי-התאמת מפתחות; ``404``/``410`` על מנוי מת (נמחק אוטומטית); ``Registration failed - push service error`` בצד הלקוח מגיע מ-Google Play Services במכשיר ואינו קשור לשרת.
- **Idempotency** – ה-Worker מעביר הלאה את הכותרת ``X-Idempotency-Key`` (אם קיימת). מומלץ להפיק UUID לכל batch של תזכורות כדי להימנע משכפולים.
- **לוגים** – נרשם hash של ה-endpoint בלבד, לא ה-URL המלא.
