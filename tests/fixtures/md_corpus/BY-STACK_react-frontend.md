# BY-STACK: React frontend

## רלוונטיות — העתק את הקובץ הזה אם בפרויקט יש...
- ✅ React עם `useState` / `useEffect` / `useCallback` / `useMemo`
- ✅ Data fetching דרך TanStack Query, SWR, או דומה (state של frontend שמסונכרן מהשרת)
- ✅ טפסים, dropdowns, או כל קומפוננטה שמקבלת ערך התחלתי מ-prop שיכול להשתנות
- ✅ צד-דפדפן `URL.createObjectURL`, `setTimeout`, או DOM manipulation
- ⏭ דלג אם: HTML עם server-rendering בלבד (לא SPA), או React עם state מקומי בלבד

> Cross-link: **K4 (XSS via innerHTML)** ב-`CRITICAL-PATTERNS.md` הוא חובת קריאה לכל פרויקט React שמרנדר מחרוזות חיצוניות.

---

## דפוס 1 — useState מאותחל מ-prop שמשתנה (CORE U2)

**תדירות:** Noa, EmailFlow, Web — 3+ מופעים
**חומרה:** MEDIUM (שחיתות שקטה כשה-state הישן נשלח חזרה ל-backend)

### איך זה נראה
```jsx
function StatusDropdown({ leadId, currentStatus }) {
  const [status, setStatus] = useState(currentStatus);  // ❌
  // currentStatus משתנה כש-parent עושה refetch, אבל status לא
  return <select value={status} onChange={...}>...</select>;
}
```
אחרי refetch של הרשימה שמעדכן את ה-status של ה-lead, ה-dropdown עדיין מציג את הערך הישן. המשתמש לוחץ Save, ה-dropdown שולח את ה-`expected_status` הישן, בדיקת CAS אופטימית ב-backend דוחה, ה-pipeline חוזר אחורה.

### שלושה דפוסי resync (לבחור אחד לכל הפרויקט)
1. **`key` prop על parent (הכי פשוט):**
   ```jsx
   <StatusDropdown key={lead.id} leadId={lead.id} currentStatus={lead.status} />
   ```
   מאלץ את React לעשות remount לקומפוננטה ב-`id` change, כך שה-state המקומי טרי.
2. **`useEffect` resync:**
   ```jsx
   const [status, setStatus] = useState(currentStatus);
   useEffect(() => { setStatus(currentStatus); }, [currentStatus]);
   ```
3. **Derived state (בלי state מקומי):**
   ```jsx
   // רנדר ישירות מ-currentStatus, הרם edits ל-parent
   return <select value={currentStatus} onChange={(e) => onChange(lead.id, e.target.value)}>...</select>;
   ```

### כלל לזיהוי
דווח על `const [s, setS] = useState(props.X)` כש-`props.X` יכול להשתנות וגם אין `useEffect([props.X])` resync וגם אין `key={...}` על הקומפוננטה.

### False positives
- props רק ב-mount (`user.id` שלעולם לא משתנה).
- state מקומי בלבד (modal פתוח/סגור).
- inputs uncontrolled עם `defaultValue`.

### Commits אמיתיים
- EmailFlow `d84daca`, `3987818` — status dropdown תקוע על ערך ישן.
- EmailFlow `02f633a` — חסר `key={conversationId}` ב-ReplyBox → state עבר בין שיחות.
- EmailFlow `b14e3f3` — `seenDraftKey` collision בין שתי הודעות.
- Noa `TBD-followup-rules` — `FollowupRulesSection` לא סינכרן state אחרי save (prop השתנה, useState המקומי תקוע).
- Noa `TBD-use-local-storage` — `useLocalStorage` hook לא איפס state ל-`defaultValue` כש-ה-key prop השתנה ולא היה ערך שמור.
- Web `2e5c480` — רק `token` עודכן, לא `refreshToken`.

---

## דפוס 2 — הפרת Rules of Hooks

### איך זה נראה
```jsx
function Comp({ data }) {
  if (!data) return null;
  const [x, setX] = useState(data.x);  // ❌ hook אחרי early return
  ...
}
```
ספירת hooks משתנה בין renders → React קורס ("Rendered fewer hooks than expected").

### כלל לזיהוי
כל `useState` / `useEffect` / `useCallback` / `useMemo` חייב לרוץ לפני כל `return null;` / conditional return.

### Commits אמיתיים
- EmailFlow `e968135`.

---

## דפוס 3 — Stale closure ב-useCallback / useMemo

### איך זה נראה
```jsx
const toggleActivity = useCallback((id) => {
  api.toggle(activeChildId, id);  // ❌ activeChildId לא ב-deps
}, []);
```
אחרי החלפת ילד, ה-callback עדיין משתמש ב-`activeChildId` הקודם.

### כלל לזיהוי
הפניות בגוף `useCallback` / `useMemo` חייבות כולן להופיע ב-dependency array. ה-`react-hooks/exhaustive-deps` של ESLint תופס את רובן — שמור עליו ב-`error`.

### Commits אמיתיים
- routine `259c2a3` — `activeChildId` חסר → toggle השפיע על הילד הקודם.

---

## דפוס 4 — setState אחרי `await` בלי cancellation flag

### איך זה נראה
```jsx
useEffect(() => {
  let cancelled = false;
  async function load() {
    const data = await fetchData();
    if (cancelled) return;
    setData(data);
  }
  load();
  return () => { cancelled = true; };
}, [...]);
```
בלי בדיקת `cancelled`, ה-`await` של ה-render השני מסיים ודורס את ה-UI של הראשון.

### Commits אמיתיים
- Noa `b360c66` — `renderTemplate` async דרס את ה-UI עם preview ישן.
- Noa `7444dd9` — `Promise.all` setLoading התחרה עם render.

---

## דפוס 5 — Identity לא יציב ב-deps (אובייקטים של TanStack Query mutation)

```jsx
const mutation = useMutation(...);
useEffect(() => { mutation.mutate(...); }, [mutation]);  // ❌ identity של mutation לא יציב → re-run אינסופי
```
אובייקט ה-mutation של TanStack Query נוצר מחדש בכל render. השתמש ב-`mutation.mutate` (identity יציב של callback) ב-dep array, או `useEffect(() => { ... }, [])` עם `mutation.mutate` בגישה מבפנים (eslint suppression עם הערה).

---

## דפוס 6 — דליפת `URL.createObjectURL`

```jsx
const url = URL.createObjectURL(blob);  // ❌ לעולם לא משוחרר
```

```jsx
useEffect(() => {
  const url = URL.createObjectURL(blob);
  setSrc(url);
  return () => URL.revokeObjectURL(url);
}, [blob]);
```

### Commits אמיתיים
- Web `f5cbaf9` — דליפת blob URL של תמונת profile.

---

## דפוס 7 — `setTimeout(fn, delay)` / `new Date(value)` עם delay לא סופי

```js
setTimeout(load, parsed);  // ❌ אם parsed הוא NaN, שגיאת React
setTimeout(load, isFinite(parsed) && parsed > 0 ? parsed : 1000);  // ✅
```

### Commits אמיתיים
- EmailFlow `e432866` — `setTimeout(fn, NaN)` קרס.

---

## דפוס 8 — CSS reset גלובלי שדורס מחלקות utility

```css
* { margin: 0; padding: 0; }  /* ❌ דורס Tailwind space-y-*, p-*, m-* */
```

השתמש ב-reset מוגבל-scope (למשל `@tailwind base` בלבד) או הסר את ה-selector של `*`.

### Commits אמיתיים
- Web `c586691`.

---

## דפוס 9 — Tooltip / dropdown נסגר על click בגלל bubbling של event

```jsx
<div onClick={closeMenu}>
  <Tooltip>...</Tooltip>  {/* clicks בפנים בועלים למעלה → תפריט נסגר */}
</div>
```

עצור propagation בתוך האלמנט הפנימי:
```jsx
<Tooltip onClick={(e) => e.stopPropagation()}>...</Tooltip>
```

### Commits אמיתיים
- Markdown-Academy `315154e`.

---

## הפניות צולבות

- **CORE U2** — סנכרון state ב-React (הקובץ הזה הוא ה-deep-dive)
- **CORE U1** — חל כש-React קורא ל-endpoints שמקושרים ל-webhook (idempotency keys ב-request)
- **CRITICAL K4** — XSS via `innerHTML` / `dangerouslySetInnerHTML`
- **R3** — quirks רחבים יותר של Browser API (clipboard, mailto:, blob URLs)
- **`bugbot-rules/react-stale-state-on-prop.md`** — prompt עצמאי
- **`bugbot-rules/react-async-media-resource.md`** — משאב async חיצוני (מיקרופון, WebSocket, MediaRecorder): double-action, setState אחרי unmount, ו-cleanup בכל מסלולי היציאה
