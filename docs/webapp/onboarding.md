# 🎉 Onboarding (Welcome Modal) – WebApp

מודאל **Welcome** מוצג למשתמשים שמתחברים ל־WebApp בפעם הראשונה, ונותן קיצור דרך למדריך הראשי ולמדריך משני. לאחר אישור/דילוג, המודאל לא יוצג שוב.  
**החל מ־דצמבר 2025** המודאל מושך את שניהם ישירות מקובץ `webapp/USER_GUIDE.md`, כך שכל עדכון במאגר נכנס מיידית למודאל ולשיתוף הציבורי (`/share/welcome?view=md`).

---

## מטרות
- להדריך משתמשים חדשים במהירות לשני מדריכים מרכזיים.
- לצמצם חיכוך בכניסה ראשונה, ולהציג רק פעם אחת באמצעות דגל `has_seen_welcome_modal`.

---

## זרימת משתמש
1. משתמש חדש מתחבר ל־WebApp.
2. מודאל Welcome נפתח ומציג:
   - קישור ראשי (Primary) למדריך הכרות כללי.
   - קישור משני (Secondary) לנושא משלים שכיח.
3. לחיצה על אחד הקישורים או על "דלג לעכשיו" שולחת קריאה אל `POST /api/welcome/ack`, מעדכנת את הדגל `has_seen_welcome_modal` ומסתירה את המודאל לצמיתות.

> הערה: אם תרצו להחזיר את המודאל לצורכי בדיקה – מחיקת הדגל ידנית ב־DB תאפשר הצגה מחדש (אין כיום UI לכך).

---

## סנכרון למדריך העדכני
- `USER_GUIDE.md` הוא מקור האמת – אין צורך לשמור גרסה נפרדת ב־DB.
- `get_internal_share()` מזהה את המזהים `welcome` ו־`welcome-quickstart` (וגם את המזהים ההיסטוריים `JjvpJFTXZO0oHtoC` / `sdVOAx6hUGsH4Anr`) ומחזיר את התוכן מהקובץ המקומי.
- אם הקובץ לא קיים, נרשמת אזהרה ב־log והמודאל מסתתר, לכן יש לשמור את הקובץ בריפו בכל פריסה.

### איך לעדכן את התוכן
1. ערכו את `webapp/USER_GUIDE.md` (לדוגמה: עדכון סעיף "מה חדש").
2. פרסמו את השינוי – אין צורך להריץ סקריפט יצירת share.
3. ודאו שהעמוד `/share/welcome?view=md` מציג את העדכון ושכפתור המודאל נטען ללא שגיאות קונסול.

## קישורי מדריכים (Anchors)
- מדריך ראשי (Primary): `/share/welcome?view=md`  
  נבנה מהקובץ `USER_GUIDE.md` וכולל את כל סעיפי גרסה 2.0 (דשבורד, קיצורי מקלדת, אוספים ועוד).
- מדריך משני (Secondary): `/share/welcome-quickstart?view=md`  
  כרגע מצביע לאותו תוכן כדי לשמור עקביות, אך ניתן להפנותו בעתיד לקובץ Markdown אחר או לעוגן פנימי (למשל `#התחברות-והתחלת-עבודה`).

ראו גם: רפרנס API ל־WebApp – `webapp/api-reference` (כולל `/md/<id>` להצגת Markdown).

---

## Best Practices – אינדיקציה למשתמשים חדשים
- סמנו והיעזרו ב־`has_seen_welcome_modal` עבור כל פיצ'ר שרץ "בפעם הראשונה" בלבד (למשל: הודעת היכרות עם Collections).
- שמרו את הדגל גם ב־session כדי להימנע מקריאות מיותרות עד ריענון.

```text
session: { has_seen_welcome_modal: true }
DB: users.has_seen_welcome_modal = true
```

---

## דוגמת JS – מודאל עם Ajax
דוגמה פשוטה ל־init של מודאל Welcome והקשה ל־`/api/welcome/ack`:

```javascript
function welcomeModalInit() {
  const modal = document.getElementById('welcome-modal');
  if (!modal) return;

  async function ackAndHide() {
    try {
      const res = await fetch('/api/welcome/ack', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({})
      });
      if (!res.ok) throw new Error('ack failed');
      // סימון דגל בסשן (client-side hint)
      try { sessionStorage.setItem('has_seen_welcome_modal', '1'); } catch (e) {}
      modal.style.display = 'none';
    } catch (e) {
      console.warn('welcome ack error', e);
    }
  }

  const primary = modal.querySelector('[data-action="primary"]');
  const secondary = modal.querySelector('[data-action="secondary"]');
  const skip = modal.querySelector('[data-action="skip"]');

  if (primary) primary.addEventListener('click', ackAndHide);
  if (secondary) secondary.addEventListener('click', ackAndHide);
  if (skip) skip.addEventListener('click', (ev) => {
    ev.preventDefault();
    ackAndHide();
  });
}

// דוגמת שילוב ב-base.html
window.addEventListener('DOMContentLoaded', () => {
  // אל תריצו שוב אם יש דגל בצד הלקוח (חוסך הבהוב ביניים)
  try {
    if (sessionStorage.getItem('has_seen_welcome_modal') === '1') return;
  } catch (e) {}
  welcomeModalInit();
});
```

---

## API קשור
- `POST /api/welcome/ack` – דורש התחברות, מסמן `has_seen_welcome_modal` ב־DB וב־session, מחזיר `{ "ok": true }`.
- `POST /api/shared/save` – שמירת שיתוף פנימי כקובץ Markdown בחשבון המשתמש; ראו `webapp/api-reference`.

---

## מדיה
- צילומי מסך/גיפים – יתווספו לאחר העלאת הנכסים לספריית `docs/_static/`.
