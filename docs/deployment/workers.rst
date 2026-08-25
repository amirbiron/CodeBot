עובדי Push
===========
:summary: Web Push מקצה לקצה — דרישות ומפתחות VAPID, המסלול המקומי ב-pywebpush מול עובד ה-Node, החיבור ל-WebApp, מי שולח את התזכורות, צד הלקוח, ובדיקות.

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

דרישות מוקדמות
---------------

**דפדפנים.** Chrome, Edge, Firefox ואנדרואיד תומכים ישירות. ב-iOS פוש עובד
**רק מתוך PWA מותקנת** (הוספה למסך הבית, iOS 16.4 ומעלה) — בלשונית רגילה
בספארי אין פוש כלל, וזו הסיבה הנפוצה ביותר ל"לא מקבל התראות" באייפון.

**מפתחות VAPID.** זוג מפתחות חובה בשני המסלולים. ייצור:

.. code-block:: bash

   npx web-push generate-vapid-keys

**דגל ראשי.** ``PUSH_NOTIFICATIONS_ENABLED`` (ברירת מחדל ``true``). כיבוי
עוצר את התזמון ואת השליחה, אבל **משאיר את נקודות הקצה זמינות** — כלומר
הדפדפן עדיין יכול להירשם, ופשוט לא יקבל דבר.

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
  - ה-Worker מאזין על ``127.0.0.1`` בלבד.

**פריסה כשירות נפרד ב-Render.** ``render.push-worker.yaml`` מגדיר שירות
Docker ל-``push_worker``. אפשר להעלות אותו כ-Blueprint, או ליצור שירות Web
חדש שמצביע ל-``push_worker/Dockerfile``. משתני הסביבה שהשירות הזה צריך:
``PUSH_DELIVERY_TOKEN``, ``WORKER_VAPID_PUBLIC_KEY``,
``WORKER_VAPID_PRIVATE_KEY``, ``WORKER_VAPID_SUB_EMAIL``.

.. important::

   הבינד ל-``127.0.0.1`` מתאים **רק לפריסת sidecar**, כלומר כשה-Worker
   וה-WebApp חולקים את אותו network namespace (אותו קונטיינר, או אותו Pod
   ב-Kubernetes). בפריסה שבה ה-Worker רץ בקונטיינר או ב-Pod נפרד, ה-WebApp
   לא יוכל להגיע אליו כלל.

   לפריסה נפרדת יש לבצע bind לממשק פנימי (למשל ``0.0.0.0`` בתוך רשת פרטית),
   ולהגן עליו בשתי שכבות: NetworkPolicy או Security Group שמתירים תעבורה
   מה-WebApp בלבד, ובנוסף ``PUSH_DELIVERY_TOKEN``. אין לחשוף את הפורט
   לאינטרנט בשום מקרה.

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
      PUSH_DELIVERY_TIMEOUT_SECONDS=3

   ``PUSH_DELIVERY_URL`` הוא **בסיס בלי** ``/send`` — השרת מוסיף אותו בעצמו.

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

מי שולח את התזכורות, ומתי
--------------------------

**לא ג'וב רשום ולא cron חיצוני, אלא thread בתוך תהליך ה-WebApp.**
``webapp/push_api.py`` מרים thread דמון בשם ``push-sender``, שמריץ
``_send_due_once()`` בלולאה ונרדם ``PUSH_SEND_INTERVAL_SECONDS`` בין סבב
לסבב (ברירת מחדל 60 שניות, ורצפה של 20 גם אם הוגדר פחות).

הסבב שולף מ-``note_reminders`` תזכורות שהגיע זמנן, ושולח לכל מנוי של
המשתמש — במסלול המקומי ישירות עם ``pywebpush``, ובמסלול המרוחק דרך
``POST /send`` של ה-Worker.

.. important::

   **רק תהליך אחד שולח.** לפני הרמת ה-thread נלקחת נעילת ``flock`` על
   ``PUSH_SENDER_LOCK_FILE`` (ברירת מחדל ``/tmp/codebot-push-sender.lock``);
   תהליך שלא השיג אותה פשוט אינו מרים שולח. בלי זה כל worker של gunicorn
   היה שולח את אותה תזכורת. הנעילה היא **fail-open** — אם ``fcntl`` אינו
   זמין, כל תהליך מרים שולח משלו.

   מניעת הכפילות ברמת התזכורת עצמה היא נפרדת, ונשענת על ``_claim_reminder``
   ועל דגל ``needs_push``.

צד הלקוח
---------

**נקודות קצה בשרת:**

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - נתיב
     - תפקיד
   * - ``GET /api/push/public-key``
     - מחזיר ``{ok, vapidPublicKey}`` — המפתח שהדפדפן נרשם איתו
   * - ``POST /api/push/subscribe``
     - שומר מנוי למשתמש המחובר
   * - ``DELETE /api/push/subscribe?endpoint=...``
     - מסיר מנוי

**Service Worker.** ``sw.js`` נטען משורש הסקופ (``/sw.js``) ומאזין
ל-``push`` ול-``notificationclick``, כולל פעולות מהירות בהתראה עצמה:
``open_note`` (פתיחת הפתק) ו-``snooze_10``/``snooze_60``/``snooze_1440``
(דחייה ב-10 דקות, שעה, או יממה — מטופלת ב-SW עצמו).

**הרשמה.** בעמוד ``/settings`` יש CTA שמבצע את הרצף המלא: רישום ה-Service
Worker, בקשת הרשאה מהדפדפן, רישום Push מול המפתח הציבורי, ושליחת המנוי
לשרת.

בדיקות ועצות
-------------

**בדיקת חיים** – ``curl -fsS $PUSH_DELIVERY_URL/healthz`` אמור להחזיר ``{"ok":true}``.

**בדיקת אינטגרציה** – ``POST /send`` דורש Bearer token וגוף JSON תקין,
אחרת יוחזר ``401`` או ``400`` עוד לפני ניסיון השליחה:

.. code-block:: bash

   curl -X POST "$PUSH_DELIVERY_URL/send" \
     -H "Authorization: Bearer $PUSH_DELIVERY_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
           "subscription": {
             "endpoint": "https://fcm.googleapis.com/fcm/send/...",
             "keys": {"p256dh": "<base64url>", "auth": "<base64url>"}
           },
           "payload": {"notification": {"title": "בדיקה", "body": "שלום"}},
           "options": {"ttl": 3600, "urgency": "high", "contentEncoding": "aes128gcm"}
         }'

את ערכי ה-``subscription`` אפשר להעתיק מ-``/settings/push-debug`` (כפתור
"הצג מנויים") או מ-``PushSubscription.toJSON()`` בקונסולת הדפדפן.

**בדיקת לקוח** – ``POST /api/push/test`` (נדרש session) שולח פוש לדפדפן
ומחזיר JSON עם ``sent`` ומערך ``errors`` מפורט. דף ``/settings/push-debug``
עוטף את זה בממשק.

**פענוח שגיאות**

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - קוד
     - משמעות
   * - ``401``
     - שגיאת הרשאה בין ה-WebApp ל-Worker: ``PUSH_DELIVERY_TOKEN`` חסר, שגוי, או לא זהה בשני הצדדים. **אינו** מעיד על מפתחות VAPID.
   * - ``403``
     - נדחה על ידי שירות הפוש. ברוב המקרים אי-התאמת מפתחות VAPID — המנוי נוצר עם מפתח ציבורי אחר מזה שחותם. בדקו את ה-Worker ואת זוג המפתחות.
   * - ``404`` / ``410``
     - המנוי מת (המשתמש ביטל, ניקה נתונים, או שהדפדפן חידש). נמחק אוטומטית מהמסד.
   * - ``Registration failed - push service error``
     - שגיאת צד לקוח מ-Google Play Services במכשיר (שעון לא מסונכרן, חשבון Google חסר, GMS ישן). אינה קשורה לשרת.

**ניסיונות חוזרים** – **אין ניסיון חוזר מיידי בכלל.** ``_post_to_worker()``
שולח בקשה אחת ומחזיר, ואין סביבה לולאת retry.

מה שכן קורה: ``needs_push`` מתנקה **רק בשליחה שהצליחה**. כל שליחה שלא
הצליחה — מכל סוג, כולל ``4xx`` שאינו ``404``/``410`` — משאירה את הדגל
דלוק, ולכן הסבב הבא של ``push-sender`` (ראו למעלה) יאסוף את אותה תזכורת
וינסה שוב. הקצב הוא ``PUSH_SEND_INTERVAL_SECONDS``, לא backoff.

מה **כן** מפסיק לחזור: ``404``/``410`` גוררים מחיקת ה-endpoint מ-
``push_subscriptions``, ולכן המנוי המת אינו נשלף בסבב הבא. התזכורת עצמה
עדיין תישלף כל עוד ``needs_push`` דלוק — כלומר כל עוד אף מנוי אחר של
המשתמש לא הצליח.

.. note::

   בפועל המשמעות היא ש-``401``/``403`` — טוקן שגוי בין השרת ל-Worker, או
   אי-התאמת VAPID — נשלחים שוב ושוב עד שמתקנים את הקונפיג. זו התנהגות
   הקוד היום, לא המלצה: תיקון של הסיבה עדיף על המתנה לניסיון הבא.

**X-Idempotency-Key** – ה-Worker מעביר את הכותרת הלאה בלבד, ושירותי הפוש
מתעלמים ממנה. זוהי כותרת **מתאם ואבחון** לשיוך לוגים בין השרת ל-Worker,
ו\ **אינה** מונעת שליחה כפולה. מניעת כפילויות אמיתית מתבצעת בצד השרת
דרך ``_claim_reminder`` ודגל ``needs_push``.

**בדיקות יחידה** – ``tests/test_push_api.py`` מכסה את ``public-key`` ואת
``subscribe``/``unsubscribe``.

**לוגים** – נרשם hash של ה-endpoint בלבד, ו-URLs מנוקים מהודעות שגיאה.
