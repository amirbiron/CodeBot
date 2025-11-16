# Web Push – Sticky Notes Reminders

מסמך זה מסביר כיצד להפעיל ולבדוק התראות Web Push עבור תזכורות של Sticky Notes.

קישור למסמך המקורי עם דוגמאות והסברים מפורטים:
- https://code-keeper-webapp.onrender.com/share/k8yuEWIeQ1ZqdlGP

## דרישות
- דפדפנים נתמכים: Chrome/Edge/Firefox/Android. ב‑iOS: פוש רק ב‑PWA מותקנת (A2HS, iOS 16.4+).
- מפתחות VAPID.
- תלוי מצב שליחה:
  - Local: ספריית `pywebpush` בשרת.
  - Remote: שירות Worker חיצוני (Node) עם `web-push`.

## הגדרת מפתחות VAPID
1. צור זוג מפתחות VAPID (לדוגמה עם `web-push` של Node.js או כל כלי מתאים):
   ```bash
   npx web-push generate-vapid-keys
   ```
2. הזן לסביבת ההרצה:
   - `VAPID_PUBLIC_KEY` – מחרוזת base64url של המפתח הציבורי
   - `VAPID_PRIVATE_KEY` – המפתח הפרטי
   - (אופציונלי) `VAPID_SUB_EMAIL` – כתובת מייל ל־subject (לדוגמה: support@example.com)

3. ודא שהערכים זמינים בשירות ה‑WebApp (Render/Heroku/וכו׳).

## הפעלה/כיבוי
- דגל כללי: `PUSH_NOTIFICATIONS_ENABLED` (ברירת מחדל: true). כיבוי הדגל יפסיק את תזמון/שליחת הפושים בשרת אך ישאיר את נקודות הקצה זמינות.

## מצב Remote Worker (מומלץ לפרודקשן)
כדי להימנע מתלויות OpenSSL/cryptography בצד השרת, ניתן להאציל את חתימת/שליחת ה‑Web Push ל‑Worker חיצוני (Node):

1. פריסה (Render):
   - בקובץ `render.push-worker.yaml` מוגדר שירות Docker ל‑`push_worker`.
   - העלה ל‑Render כ‑Blueprint או צור שירות Web חדש המצביע ל‑`push_worker/Dockerfile`.
   - הגדר משתני סביבה בשירות ה‑Worker: `PUSH_DELIVERY_TOKEN`, `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY`, `VAPID_SUB_EMAIL`.

2. קונפיג ב‑WebApp:
   - `PUSH_REMOTE_DELIVERY_ENABLED=true`
   - `PUSH_DELIVERY_URL=https://<worker-domain>` (ללא `/send` בסוף)
   - `PUSH_DELIVERY_TOKEN=<אותו טוקן שהוגדר ב‑Worker>`
   - (אופציונלי) `PUSH_DELIVERY_TIMEOUT_SECONDS=3`

3. התנהגות:
   - השרת ישלח `POST <PUSH_DELIVERY_URL>/send` עם Bearer token.
   - קודי 404/410 מה‑Worker יגררו ניקוי מנוי מה‑DB.
   - `401/403` יופיעו ככשל התאמת מפתחות/הרשאות.
   - Retries: אין ניסיון חוזר על `4xx`; על `5xx/timeout` בלבד.

### חלופה: Sidecar (ללא שירות Render נוסף)
ניתן להריץ את ה‑Worker בתוך אותו קונטיינר של ה‑WebApp. זה חוסך עלות שירות נוסף.

1. ה‑Dockerfile מריץ סקריפט שמרים את ה‑Worker על `127.0.0.1:<PUSH_WORKER_PORT>` ואת ה‑Flask על `$PORT` של הפלטפורמה.
2. קנפוג נדרש:
   - `PUSH_REMOTE_DELIVERY_ENABLED=true`
   - `PUSH_DELIVERY_URL=http://127.0.0.1:18080` (או עדכנו את `PUSH_WORKER_PORT`)
   - `PUSH_DELIVERY_TOKEN=<טוקן משותף לשרת→Worker>`
   - ״סודות״ ל‑Worker בלבד: `WORKER_VAPID_PUBLIC_KEY`, `WORKER_VAPID_PRIVATE_KEY`, `WORKER_VAPID_SUB_EMAIL`
3. הערות אבטחה:
   - מפתח ה‑VAPID הפרטי אינו נדרש ע"י Flask, ולכן מוזן רק לסביבת ה‑Worker (דרך משתנים עם קידומת `WORKER_`).
   - ה‑Worker מאזין ל‑localhost בלבד, אינו נגיש חיצונית.

## נקודות קצה (Server)
- `GET /api/push/public-key` – מחזיר `{ ok, vapidPublicKey }`.
- `POST /api/push/subscribe` – שומר את המנוי לדחיפה (per user).
- `DELETE /api/push/subscribe?endpoint=...` – הסרת מנוי.

## Service Worker
קובץ `sw.js` נטען משורש הסקופ (`/sw.js`) ומאזין לאירועי `push` ו־`notificationclick`, כולל פעולות מהירות:
- open_note – פתיחת קובץ עם העוגן של הפתק
- snooze_10/60/1440 – דחיית התזכורת מה‑SW

## צד‑לקוח
בעמוד ההגדרות (`/settings`) נוסף CTA להפעלת התראות: רישום Service Worker, בקשת הרשאה, רישום Push מול VAPID ושליחת ה‑subscription לשרת.

## שליחה בזמן אמת
תהליך רקע בשרת סורק `note_reminders` ומפעיל שליחת Web Push כאשר `remind_at <= now` עבור מנויי המשתמש.

- במצב Local (`pywebpush`) השליחה מתבצעת ישירות מהשרת.
- במצב Remote (`PUSH_REMOTE_DELIVERY_ENABLED=true`) השליחה תתבצע דרך ה‑Worker, ו‑404/410 יימחקו את המנוי.

## בדיקות
- בדיקות יחידה מכסות public-key ו־subscribe/unsubscribe (`tests/test_push_api.py`).

