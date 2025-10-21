# ⌨️ עורך קוד (WebApp Editor)

תוכן זה מסביר את טעינת העורך, מנגנון הגיבוי, וניהול העדפות.

---

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
