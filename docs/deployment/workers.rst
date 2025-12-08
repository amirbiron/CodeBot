עובדי Push ו-Edge
==================

שתי תצורות Worker תומכות במנגנון ה-Web Push של Code Keeper Bot:

1. **Cloudflare Worker** (`/worker`) – מתאים לדיפלוימנט Edge סרברלס.
2. **Node Service Worker** (`/push_worker`) – תהליך נפרד שרץ לצד הבוט (Render/Docker/Hobby VM).

העמוד מסביר איך לפרוס ולחבר אותם אל ה-WebApp (`webapp/push_api.py`) בצורה מאובטחת.

.. contents::
   :local:
   :depth: 2

Cloudflare Worker (`/worker`)
-----------------------------

- קובץ הכניסה: ``worker/src/index.js``. משתמש ב‑``web-push`` כדי לשלוח הודעות בשם השרת.
- נתיב יחיד: ``POST /send``.
- אימות: כותרת ``Authorization: Bearer <PUSH_DELIVERY_TOKEN>`` – חייב להיות זהה ל‑ENV ב-WebApp (`PUSH_DELIVERY_TOKEN`).
- משתני סביבה חובה ב־Workers KV/Secrets:

  - ``PUSH_DELIVERY_TOKEN`` – אסימון שיתוף בין ה-Worker ל-WebApp.
  - ``WORKER_VAPID_PUBLIC_KEY`` / ``WORKER_VAPID_PRIVATE_KEY`` – זוג VAPID ייעודי (base64url). **אל תשתפו** את המפתח הפרטי עם תהליכי Flask.
  - ``WORKER_VAPID_SUB_EMAIL`` – מייל לתמיכה (נדרש ע"י ספריית web-push; מומר ל-``mailto:`` אם צריך).

- לוגיקה: מוודא JSON תקין, בודק הרשאות, מגבה את האנדפוינט ב-hash לצורך לוגים, ושולח את הפוש. שגיאות 4xx מוחזרות כ־``ok:false`` עם ``status`` כדי לאפשר לשרת למחוק מנויים מתים.
- פריסה: באמצעות `wrangler publish` עם קובץ ``wrangler.toml``. מומלץ להגדיר נתיב זמין רק ב-HTTPS ולחסום GET/PUT לשאר הנתיבים (ה-Worker כבר מחזיר 404/405).

Node Push Worker (`/push_worker`)
---------------------------------

- נכתב ב-Express (``index.js``) ומאזין ברירת מחדל על ``127.0.0.1:8080``.
- מיועד לרוץ כחלק מ-``scripts/start_with_worker.sh`` או כ-Container נפרד. הסקריפט טוען ``.env.worker`` כדי למנוע הדלפת VAPID keys לפרוסס הראשי.
- נתיבים:

  - ``GET /healthz`` – בדיקת חיים (משמשת את סקריפט ה-start להמתין ל-ready).
  - ``POST /send`` – API זהה ל-Cloudflare Worker (אותם שדות JSON).

- משתני סביבה:

  - ``PORT`` – ברירת מחדל 8080; הסקריפט מגדיר אוטומטית ``PUSH_WORKER_PORT``.
  - ``PUSH_DELIVERY_TOKEN`` – תואם לחלק השרת.
  - ``WORKER_VAPID_PUBLIC_KEY``, ``WORKER_VAPID_PRIVATE_KEY``, ``WORKER_VAPID_SUB_EMAIL`` – עדיפות ראשונה; נופל חזרה ל-``VAPID_*`` אם חסר.

- אבטחה:

  - השוואת Bearer מתבצעת ב-constant time בעזרת ``crypto.timingSafeEqual``.
  - ה-Worker מאזין רק ל־localhost כדי למנוע גישה חיצונית. לפריסה ב-Kubernetes/Compose חשפו רק דרך Service פנימי.

חיבור ל-WebApp (`webapp/push_api.py`)
-------------------------------------

כדי להפעיל משלוח דרך אחד ה-Workers:

1. הגדירו ב-WebApp את המשתנים הבאים:

   .. code-block:: bash

      PUSH_REMOTE_DELIVERY_ENABLED=true
      PUSH_DELIVERY_URL=https://push-worker.example.com
      PUSH_DELIVERY_TOKEN=super-secret-token

2. אם עובדים מול Worker מקומי (באמצעות `start_with_worker.sh`):

   - קבעו ``PUSH_WORKER_PORT`` (ברירת מחדל 18080).
   - מלאו את ``.env.worker`` עם המפתחות הייעודיים.
   - הסקריפט ימתין ל-``/healthz`` עד 6 שניות ויעדכן ``PUSH_DELIVERY_URL`` ל-``http://127.0.0.1:<port>`` אם לא סופק ערך.

3. במצב Cloudflare אין צורך בסקריפט – פשוט הציבו את ה-URL של ה-Worker.

בדיקות ועצות
-------------

- **בדיקת אינטגרציה** – הריצו ``curl -X POST $PUSH_DELIVERY_URL/send`` עם Bearer Token כדי לוודא את ה-Worker לפני שמפעילים את ה-WebApp.
- **בדיקת לקוח** – השתמשו ב-``POST /api/push/test`` (נדרש session) כדי לשלוח פוש לדפדפן שלכם ולקבל פלט JSON עם הצלחות/כישלונות.
- **הפרדת מפתחות** – הקפידו להשתמש במפתחות VAPID שונים בין הסרבר הראשי לבין ה-Worker. כך ניתן לבטל Worker פגום בלי להחליף את המפתחות של הבוט.
- **Idempotency** – ה-Worker מעביר הלאה את הכותרת ``X-Idempotency-Key`` (אם קיימת). מומלץ להפיק UUID לכול Batch של תזכורות כדי להימנע משכפולים.
- **לוגים** – שני ה-Workers מדפיסים hash של ה-endpoint בלבד (12 תווים) כדי שלא דולפים URL מלאים.
