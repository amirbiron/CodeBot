# Web Push – Sticky Notes Reminders

מסמך זה מסביר כיצד להפעיל ולבדוק התראות Web Push עבור תזכורות של Sticky Notes.

קישור למסמך המקורי עם דוגמאות והסברים מפורטים:
- https://code-keeper-webapp.onrender.com/share/k8yuEWIeQ1ZqdlGP

## דרישות
- דפדפנים נתמכים: Chrome/Edge/Firefox/Android. ב‑iOS: פוש רק ב‑PWA מותקנת (A2HS, iOS 16.4+).
- מפתחות VAPID.
- תלויות שרת: pywebpush.

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
תהליך רקע בשרת סורק `note_reminders` ומפעיל שליחת Web Push כאשר `remind_at <= now` עבור מנויי המשתמש. במענה 404/410 מה־push service המנוי יימחק מה־DB.

## בדיקות
- בדיקות יחידה מכסות public-key ו־subscribe/unsubscribe (`tests/test_push_api.py`).

