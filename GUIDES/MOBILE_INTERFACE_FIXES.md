# מדריך תיקונים: ממשק מובייל – Split View וניצול שטח 📱

> **תיאור**: מדריך טכני לתיקון שתי בעיות בממשק המובייל בדף העלאה/עריכת קבצים.
>
> **קבצים רלוונטיים**:
> - `webapp/static/css/split-view.css` – סגנונות Split View
> - `webapp/static/css/file-editor.css` – סגנונות טפסי העלאה/עריכה
> - `webapp/templates/upload.html` – תבנית דף ההעלאה
> - `webapp/templates/base.html` – סגנונות גלובליים
>
> **ראו גם**: [SPLIT_VIEW_CSS_DESIGN.md](./SPLIT_VIEW_CSS_DESIGN.md)

---

## תוכן עניינים

1. [בעיה 1: גלילה ב-Markdown Live Preview](#בעיה-1-גלילה-ב-markdown-live-preview)
2. [בעיה 2: ניצול שטח לא אופטימלי במובייל](#בעיה-2-ניצול-שטח-לא-אופטימלי-במובייל)
3. [סיכום שינויים נדרשים](#סיכום-שינויים-נדרשים)

---

## בעיה 1: גלילה ב-Markdown Live Preview

### תיאור הבעיה

במובייל, כשעוברים לטאב "תצוגה" ב-Split View, התוכן נחתך ולא ניתן לגלול למטה.

**הבעיה לא קיימת בטאבלט/דסקטופ** כי שם ה-Split View מוצג Side-by-Side עם גלילה תקינה.

### ניתוח הסיבה

#### המבנה הנוכחי (`split-view.css`)

```css
/* שורות 344-349: הגדרת .split-panels */
.split-panels {
  display: flex;
  flex-direction: row;
  min-height: 280px;
  max-height: calc(100vh - 200px);
}
```

```css
/* שורות 496-498: media query למובייל */
@media (max-width: 767px) {
  .split-view {
    max-height: none;  /* ← איפוס ה-max-height! */
  }
  /* ... */
  .split-panels {
    flex-direction: column;
  }
  /* ... */
  .split-preview-content {
    min-height: 220px;  /* רק min-height, אין max-height */
  }
}
```

```css
/* שורות 478-488: התנהגות בטאב "תצוגה" */
.split-view[data-active-panel="preview"] .split-panel--editor {
  display: none;
}

.split-view[data-active-panel="preview"] .split-resizer {
  display: none;
}

.split-view[data-active-panel="preview"] .split-panel--preview {
  flex: 1;
}
```

#### הבעיה המרכזית

כשעוברים לטאב "תצוגה" במובייל:
1. ה-`max-height: none` מאפשר ל-`.split-panels` לגדול ללא הגבלה
2. ה-`.split-panel--preview` מקבל `flex: 1` וגדל לגודל התוכן
3. **אין הגבלת גובה** על `.split-preview-content` – אז הוא לא גולל אלא "נדחף" מחוץ למסך

### הפתרון

#### שלב 1: הוסף הגבלת גובה ל-Split View במובייל

**קובץ**: `webapp/static/css/split-view.css`

**מיקום**: בתוך ה-media query של `@media (max-width: 767px)` (שורה 496)

```css
@media (max-width: 767px) {
  .split-view {
    max-height: none;
    /* הוסף: */
    height: calc(100vh - 200px);       /* Fallback */
    height: calc(100dvh - 200px);      /* Dynamic viewport לתמיכה בכתובת דפדפן */
    display: flex;
    flex-direction: column;
  }
  /* ... */
}
```

#### שלב 2: הגדר גובה וגלילה ל-Preview במצב טאב

**קובץ**: `webapp/static/css/split-view.css`

**מיקום**: הוסף בתוך ה-media query של `@media (max-width: 767px)`:

```css
@media (max-width: 767px) {
  /* ... קוד קיים ... */

  /* תיקון גלילה במצב "תצוגה" בלבד */
  .split-view[data-active-panel="preview"] .split-panels {
    flex: 1;
    min-height: 0;  /* חשוב! מאפשר ל-flex item להתכווץ */
    overflow: hidden;
  }

  .split-view[data-active-panel="preview"] .split-panel--preview {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .split-view[data-active-panel="preview"] .split-preview-content {
    flex: 1;
    min-height: 0;
    max-height: 100%;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;  /* גלילה חלקה ב-iOS */
  }
}
```

#### שלב 3: תיקון נוסף ל-`.split-preview-canvas`

ב-Split View, התוכן בפועל מוזרק לתוך `.split-preview-canvas`. יש לוודא שגם הוא גולל כראוי:

```css
@media (max-width: 767px) {
  .split-view[data-active-panel="preview"] .split-preview-canvas {
    min-height: auto;  /* Override ל-min-height: 160px מהגדרה הגלובלית */
  }
}
```

### קוד מלא לתיקון

הוסף את הקוד הבא **בסוף** קובץ `webapp/static/css/split-view.css` (לפני סוף הקובץ):

```css
/* ==============================================
   Mobile Scroll Fix for Preview Tab
   Issue: Content cut off in "תצוגה" tab on mobile
   ============================================== */

@media (max-width: 767px) {
  /* Container height constraint */
  .split-view {
    height: calc(100vh - 200px);
    height: calc(100dvh - 200px);
  }

  /* Enable proper flex shrinking */
  .split-view[data-active-panel="preview"] .split-panels {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  /* Preview panel fills available space */
  .split-view[data-active-panel="preview"] .split-panel--preview {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* Scrollable preview content */
  .split-view[data-active-panel="preview"] .split-preview-content {
    flex: 1;
    min-height: 0;
    max-height: 100%;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  /* Reset canvas min-height */
  .split-view[data-active-panel="preview"] .split-preview-canvas {
    min-height: auto;
  }
}
```

### בדיקה

1. פתח את דף ההעלאה (`/upload`) במובייל או בכלי מפתחים במצב מובייל
2. בחר שפה "Markdown" או שם קובץ עם סיומת `.md`
3. הקלד תוכן Markdown ארוך (עם כותרות, רשימות, קוד)
4. הפעל את "Live Preview"
5. לחץ על טאב "תצוגה"
6. **וודא**: ניתן לגלול למטה ולראות את כל התוכן

---

## בעיה 2: ניצול שטח לא אופטימלי במובייל

### תיאור הבעיות

#### א. שוליים רחבים מדי בצדדים
אזור העריכה נראה "צר" עם ריווח מיותר בצדדים.

#### ב. עורך הקוד קצר מדי
ה-textarea תופס רק כ-40% מגובה המסך במובייל.

### ניתוח המצב הנוכחי

#### שוליים – המקורות

1. **`base.html`** (שורות 740-746):
```css
@media (max-width: 768px) {
    .glass-card {
        padding: 1.5rem;  /* ← שוליים פנימיים */
    }
    
    .container {
        max-width: 100%;
        padding: 0 12px;  /* ← שוליים צדדיים */
    }
}
```

2. **`base.html`** (שורות 549-554):
```css
.main-content .glass-card {
    margin-left: 0.5rem;
    margin-right: 0.5rem;
    width: calc(100% - 1rem);
}
```

3. **`split-view.css`** (שורות 518-521):
```css
@media (max-width: 767px) {
    .split-panel--editor,
    .split-panel--preview {
        padding: 0.65rem;
    }
}
```

#### גובה העורך – המצב הנוכחי

**`upload.html`** (שורה 109):
```html
<textarea id="codeTextarea" name="code" rows="18" ...>
```

`rows="18"` קובע גובה של 18 שורות טקסט, שבמובייל תופס מעט מדי ממסך.

### הפתרון

#### א. צמצום שוליים במובייל

**קובץ**: `webapp/static/css/file-editor.css`

הוסף בסוף הקובץ:

```css
/* ==============================================
   Mobile Space Optimization
   ============================================== */

@media (max-width: 767px) {
  /* Reduce glass-card padding on upload/edit pages */
  form[data-file-form-config] {
    gap: 0.75rem !important;  /* Tighter form spacing */
  }

  /* Reduce side padding in split panels */
  .split-panel--editor,
  .split-panel--preview {
    padding: 0.5rem 0.35rem;
  }

  /* Reduce preview content padding */
  .split-preview-content {
    padding: 0.75rem;
  }
}

/* Very small screens */
@media (max-width: 480px) {
  .split-panel--editor,
  .split-panel--preview {
    padding: 0.35rem 0.25rem;
  }

  .split-preview-content {
    padding: 0.5rem;
  }
}
```

**אופציונלי** – אם רוצים לצמצם עוד יותר את שולי ה-glass-card בדף ההעלאה בלבד, הוסף ב-`upload.html` (בתוך `{% block extra_css %}`):

```html
<style>
@media (max-width: 767px) {
  .glass-card {
    padding: 1rem 0.75rem;
  }
}
@media (max-width: 480px) {
  .glass-card {
    padding: 0.75rem 0.5rem;
  }
}
</style>
```

#### ב. הגדלת גובה עורך הקוד במובייל

**קובץ**: `webapp/static/css/file-editor.css`

הוסף בסוף הקובץ (ממשיך מהקוד הקודם):

```css
/* ==============================================
   Code Editor Height Optimization
   ============================================== */

/* Mobile: Taller code textarea */
@media (max-width: 767px) {
  textarea.code-field,
  textarea[name="code"] {
    min-height: 55vh;      /* ~55% of viewport height */
    max-height: 70vh;      /* Prevent over-expansion */
    resize: vertical;      /* Allow manual resize */
  }
}

/* Small mobile screens */
@media (max-width: 480px) {
  textarea.code-field,
  textarea[name="code"] {
    min-height: 50vh;
  }
}

/* Landscape mobile */
@media (max-width: 767px) and (orientation: landscape) {
  textarea.code-field,
  textarea[name="code"] {
    min-height: 60vh;      /* More height in landscape */
  }
}

/* When CodeMirror replaces textarea */
@media (max-width: 767px) {
  #editorContainer .cm-editor {
    min-height: 55vh;
    max-height: 70vh;
  }
}
```

### קוד מלא לתיקון

הוסף את כל הקוד הבא **בסוף** קובץ `webapp/static/css/file-editor.css`:

```css
/* ==============================================
   Mobile Optimization: Space & Editor Height
   Issue: Wasted space + short code editor on mobile
   ============================================== */

/* ============ A. Reduce Margins ============ */

@media (max-width: 767px) {
  /* Tighter form spacing */
  form[data-file-form-config] {
    gap: 0.75rem !important;
  }

  /* Reduce split panel padding */
  .split-panel--editor,
  .split-panel--preview {
    padding: 0.5rem 0.35rem;
  }

  /* Reduce preview content padding */
  .split-preview-content {
    padding: 0.75rem;
  }
}

@media (max-width: 480px) {
  .split-panel--editor,
  .split-panel--preview {
    padding: 0.35rem 0.25rem;
  }

  .split-preview-content {
    padding: 0.5rem;
  }
}


/* ============ B. Taller Code Editor ============ */

@media (max-width: 767px) {
  /* Native textarea */
  textarea.code-field,
  textarea[name="code"] {
    min-height: 55vh;
    max-height: 70vh;
    resize: vertical;
  }

  /* CodeMirror editor */
  #editorContainer .cm-editor {
    min-height: 55vh;
    max-height: 70vh;
  }
}

@media (max-width: 480px) {
  textarea.code-field,
  textarea[name="code"] {
    min-height: 50vh;
  }

  #editorContainer .cm-editor {
    min-height: 50vh;
  }
}

/* Landscape: More vertical space available */
@media (max-width: 767px) and (orientation: landscape) {
  textarea.code-field,
  textarea[name="code"],
  #editorContainer .cm-editor {
    min-height: 60vh;
  }
}
```

### בדיקה

1. פתח את דף ההעלאה (`/upload`) במובייל או בכלי מפתחים
2. **שוליים**: וודא שהאזור המרכזי רחב יותר ופחות "רווח מת" בצדדים
3. **גובה עורך**: וודא שה-textarea/CodeMirror תופס כ-55% מגובה המסך
4. בדוק גם במצב landscape (סיבוב לרוחב)
5. בדוק במסכים קטנים מאוד (320px-375px)

---

## סיכום שינויים נדרשים

### קובץ 1: `webapp/static/css/split-view.css`

הוסף בסוף הקובץ:

```css
/* ==============================================
   Mobile Scroll Fix for Preview Tab
   Issue: Content cut off in "תצוגה" tab on mobile
   ============================================== */

@media (max-width: 767px) {
  .split-view {
    height: calc(100vh - 200px);
    height: calc(100dvh - 200px);
  }

  .split-view[data-active-panel="preview"] .split-panels {
    flex: 1;
    min-height: 0;
    overflow: hidden;
  }

  .split-view[data-active-panel="preview"] .split-panel--preview {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  .split-view[data-active-panel="preview"] .split-preview-content {
    flex: 1;
    min-height: 0;
    max-height: 100%;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  .split-view[data-active-panel="preview"] .split-preview-canvas {
    min-height: auto;
  }
}
```

### קובץ 2: `webapp/static/css/file-editor.css`

הוסף בסוף הקובץ:

```css
/* ==============================================
   Mobile Optimization: Space & Editor Height
   Issue: Wasted space + short code editor on mobile
   ============================================== */

@media (max-width: 767px) {
  form[data-file-form-config] {
    gap: 0.75rem !important;
  }

  .split-panel--editor,
  .split-panel--preview {
    padding: 0.5rem 0.35rem;
  }

  .split-preview-content {
    padding: 0.75rem;
  }

  textarea.code-field,
  textarea[name="code"] {
    min-height: 55vh;
    max-height: 70vh;
    resize: vertical;
  }

  #editorContainer .cm-editor {
    min-height: 55vh;
    max-height: 70vh;
  }
}

@media (max-width: 480px) {
  .split-panel--editor,
  .split-panel--preview {
    padding: 0.35rem 0.25rem;
  }

  .split-preview-content {
    padding: 0.5rem;
  }

  textarea.code-field,
  textarea[name="code"],
  #editorContainer .cm-editor {
    min-height: 50vh;
  }
}

@media (max-width: 767px) and (orientation: landscape) {
  textarea.code-field,
  textarea[name="code"],
  #editorContainer .cm-editor {
    min-height: 60vh;
  }
}
```

---

## צ'קליסט לבדיקה

- [ ] **בעיה 1**: גלילה עובדת בטאב "תצוגה" במובייל
- [ ] **בעיה 2א**: שוליים צרים יותר במובייל
- [ ] **בעיה 2ב**: עורך הקוד גבוה יותר (~55% מהמסך)
- [ ] **רגרסיה**: טאבלט ודסקטופ לא נפגעו
- [ ] **נגישות**: ניתן לגלול עם מגע ועם מקלדת
- [ ] **iOS Safari**: גלילה חלקה עם `-webkit-overflow-scrolling`

---

## הערות נוספות

### Dynamic Viewport Units

שימוש ב-`100dvh` במקום `100vh` מתקן בעיות עם כתובת הדפדפן במובייל (Safari/Chrome) שמשנה את גובה ה-viewport בזמן גלילה.

### `min-height: 0` על Flex Items

זוהי טכניקה חשובה ב-Flexbox: כברירת מחדל, `min-height` של flex item הוא `auto`, מה שמונע ממנו להתכווץ מתחת לגודל התוכן. הגדרת `min-height: 0` מאפשרת לו להתכווץ וליצור גלילה פנימית.

### סדר ספציפיות

הקוד החדש משתמש בסלקטורים ספציפיים יותר (כמו `.split-view[data-active-panel="preview"]`) כדי לעקוף את ההגדרות הקיימות רק במצב הרלוונטי.

---

## קישורים

- [CSS Overflow](https://developer.mozilla.org/en-US/docs/Web/CSS/overflow)
- [Dynamic Viewport Units](https://web.dev/viewport-units/)
- [Flexbox min-height issue](https://stackoverflow.com/questions/36247140/why-dont-flex-items-shrink-past-content-size)
