---
summary: תוכן זה מסביר את טעינת העורך, מנגנון הגיבוי, וניהול העדפות.
---

# ⌨️ עורך קוד (WebApp Editor)

## טעינת CodeMirror ומצב isLoading
- נטען את CodeMirror בצורה דינמית.
- אם הטעינה נכשלת → מנגנון fallback (textarea) מופעל.
- במהלך הטעינה מוצג מצב `isLoading` כדי למנוע אינטראקציה מיותרת.

```javascript
let isLoading = true;
try {
  const cm = await import('codemirror');
  // init editor...
} catch (e) {
  console.warn('Editor fallback to textarea', e);
} finally {
  isLoading = false;
}
```

---

## החבילה המקומית של CodeMirror, וכיוון לכל שורה
- `EditorManager` (`webapp/static/js/editor-manager.js`) טוען קודם את `webapp/static/js/codemirror.local.js`, שמגדיר `window.CodeMirror6`. רק כשהיא לא עולה הוא בונה את `window.CodeMirror6` ממודולים ב-CDN, ובמסלול הזה אין את התוספים שהחבילה המקומית מוסיפה.
- **החבילה נבנית מקובץ ה-entry** `webapp/static_build/codemirror.bundle.entry.mjs` עם `webapp/static_build/build-cm.mjs`, מהגרסאות שב-`package-lock.json`. הבנייה רצה מתוך `webapp/static_build`: esbuild כותב בחבילה הערות עם נתיבי המודולים יחסית לתיקייה שממנה רצים, ובנייה מתיקייה אחרת משנה את כל ההערות האלה. בנייה מתוך התיקייה, בלי שינוי ב-entry, מחזירה קובץ זהה בייט-בייט לזה שבריפו (נבדק באוקטובר 2026), ולכן הדיף של שינוי ב-entry הוא רק השינוי עצמו. הסקריפט `build-cm` שב-`package.json` מריץ את אותו קובץ מהשורש, ולכן הוא משנה את ההערות. מתקינים מהשורש ובונים מהתיקייה:

```bash
npm ci --ignore-scripts
cd webapp/static_build && node build-cm.mjs
```

- **`perLineAutoDirection`** (ב-entry, ומיוצא ב-`window.CodeMirror6`): כל שורה מקבלת `dir="auto"`, והפאסט `EditorView.perLineTextDirection` גורם ל-CodeMirror לקרוא את הכיוון של כל שורה בנפרד — שורה בעברית מימין לשמאל, שורת קוד או אנגלית משמאל לימין, והסמן והחצים עוקבים אחריו. `initEditor` עם `textDirection: 'auto'` מוסיף אותו, ואת המחלקה `codemirror-container--dir-auto`, שב-`codemirror-custom.css` הופכת את העורך כולו לימין-לשמאל (מספרי השורות מימין). משתמש בו העורך הציבורי (`/markdown-editor`); עמודי העריכה וההעלאה נשארים משמאל לימין, כמו עורך קוד. כשהחבילה נטענה מה-CDN, האפשרות נרשמת כאזהרה בקונסול, והעורך נשאר משמאל לימין.
- **ההודעה הזמנית** ("כל הקוד סומן", "הוזרק: טבלה") מוצגת במקום התווית "קיצורי מקלדת זמינים", באותו תא (`.editor-info-slot`), ולא בשורה משלה — כך שורת הכפתורים לא משנה גובה והעורך לא זז.

---

## שמירת העדפות משתמש – שני נתיבי API
כדי לשמור תאימות לאחור, מומלץ לכתוב לשני נתיבים:
- `POST /api/ui_prefs`
- `POST /api/user/preferences`

```javascript
async function savePrefs(prefs) {
  const body = JSON.stringify(prefs);
  const headers = { 'Content-Type': 'application/json' };
  // כתיבה לשני מסלולים (best-effort)
  await Promise.allSettled([
    fetch('/api/ui_prefs', { method: 'POST', headers, body }),
    fetch('/api/user/preferences', { method: 'POST', headers, body }),
  ]);
}

savePrefs({ wrap: true, fontSize: 14, theme: 'ocean' });
```

שדות טיפוסיים: `wrap`, `fontSize`, `theme`, `tabSize`.

---

## המלצות
- אחסון לוקאלי משלים (`localStorage`) להאצת טעינה.
- ולידציה צד־שרת לערכים חריגים.
- לוגים מאוחדים עם `request_id` עבור פעולות עריכה ושמירת העדפות.
