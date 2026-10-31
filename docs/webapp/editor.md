---
summary: טעינת העורך ומנגנון הגיבוי ל-CDN, החבילה המקומית של CodeMirror — איך בונים אותה מחדש, הכיוון בעורך הציבורי (מימין לשמאל חוץ מבלוקי קוד) ועורך בלי מספרי שורות — הדבקה שמחליפה את כל המסמך, וניהול העדפות.
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

- **`rtlExceptCodeBlocks`** (ב-entry, ומיוצא ב-`window.CodeMirror6`): העורך כולו מימין לשמאל, ורק השורות של בלוק קוד מקבלות `dir="ltr"`. בלוק קוד הוא מה שהמנתח של Markdown בעורך כבר זיהה — הצמתים `FencedCode` (בין ```` ``` ````, כולל שורות הגדר) ו-`CodeBlock` (שורות מוזחות) בעץ התחביר — ולא ביטוי משלנו. `EditorView.perLineTextDirection` גורם ל-CodeMirror לקרוא את הכיוון של כל שורה בנפרד, כך שהסמן, הבחירה והחצים עוקבים אחריו. `initEditor` עם `textDirection: 'rtl'` מוסיף אותו, ואת המחלקה `codemirror-container--rtl`, שב-`codemirror-custom.css` הופכת את העורך לימין-לשמאל ונותנת לשורה ריווח לפי הכיוון שלה (ה-`.cm-line` של CodeMirror מרווח בצדדים פיזיים, ובעורך מימין לשמאל הטקסט נצמד לגבול). בעורך הפשוט, כש-CodeMirror לא עלה, הכול מימין לשמאל: ב-textarea אין כיוון לשורה בודדת. משתמש בו העורך הציבורי (`/markdown-editor`); עמודי העריכה וההעלאה נשארים משמאל לימין, כמו עורך קוד. כשהחבילה נטענה מה-CDN, האפשרות נרשמת כאזהרה בקונסול, והעורך נשאר משמאל לימין. עד אוקטובר 2026 כל שורה קיבלה `dir="auto"` (`perLineAutoDirection`), כלומר כיוון לפי האות החזקה הראשונה בה — ושורות כמו `- [x] משימה` או שורת היישור של טבלה יצאו משמאל לימין בתוך מסמך עברי.
- **`createBasicSetup({ gutters })`** — `basicSetup` עם האפשרות להוריד את העמודה שבצד הטקסט: בלי מספרי שורות ובלי חיצי קיפול (קיצורי הקיפול במקלדת נשארים). `initEditor` עם `gutters: false` משתמש בו; העורך הציבורי מעביר אותה. הוא קיים גם במסלול ה-CDN של `loadCodeMirror`, שבונה `basicSetup` משלו.
- **הדבקה שמחליפה את כל המסמך** — לתוך עורך ריק, או אחרי "בחר הכל" — משאירה את הסמן ואת העורך בתחילת המסמך (`getFullPasteExtension`: מסנן טרנזקציות על ה-userEvent `input.paste`), ושולחת על ה-textarea את האירוע `editor:document-replaced`, שבו התצוגה החיה (`live-preview.js`) חוזרת גם היא לראש המסמך. כפתור "הדבק" מסמן את ההדבקה שלו באותו userEvent (`insertTextAtCursor`), ובעורך הפשוט `watchTextareaFullPaste` עושה את אותו דבר. הדבקה לתוך טקסט קיים לא משתנה: הסמן אחרי מה שהודבק.
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
