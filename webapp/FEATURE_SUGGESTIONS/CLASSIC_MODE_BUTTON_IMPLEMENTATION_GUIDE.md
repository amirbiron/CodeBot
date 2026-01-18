# מדריך מימוש: כפתור "קלאסי" לתצוגת Markdown בערכות כהות

## סקירה כללית

הפיצ'ר המוצע מאפשר למשתמשים בערכות כהות (ערכות מיובאות/ציבוריות/אישיות) לעבור זמנית לתצוגה בסגנון הערכה הקלאסית בעת צפייה במסמכי Markdown. כפתור "קלאסי" חדש יתווסף **בין** כפתור "מסך מלא" לבין כותרת "תצוגת Markdown", ובלחיצה עליו התצוגה תעבור לסגנון הקלאסי כולל הצגת כפתור "צבע רקע" עם 4 גוונים.

---

## מיקום הכפתור

### מבנה נוכחי (שורה 1619-1656 ב-`md_preview.html`)

```html
<div class="section-header">
  <div class="section-title-wrap">
    <h2 class="section-title">תצוגת Markdown</h2>
    <!-- כפתור צבע רקע - מוסתר כברירת מחדל בערכות כהות -->
    <div id="bgColorSwitcher">...</div>
  </div>
  <button id="mdFullscreenBtn">מסך מלא</button>
</div>
```

### מבנה מוצע (לאחר המימוש)

```html
<div class="section-header">
  <div class="section-title-wrap">
    <h2 class="section-title">תצוגת Markdown</h2>
    <!-- כפתור צבע רקע - מוסתר כברירת מחדל, מוצג במצב קלאסי -->
    <div id="bgColorSwitcher">...</div>
  </div>
  <!-- קבוצת כפתורים בצד שמאל -->
  <div class="md-toolbar-actions">
    <button id="mdClassicModeBtn" class="btn btn-secondary btn-icon" title="עבור לתצוגה קלאסית">
      🎨 קלאסי
    </button>
    <button id="mdFullscreenBtn" class="btn btn-secondary btn-icon" title="מסך מלא">
      <i class="fas fa-expand"></i> מסך מלא
    </button>
  </div>
</div>
```

---

## ערכות נתמכות (כהות)

הכפתור "קלאסי" יוצג **רק** בערכות הבאות:

| סוג ערכה | זיהוי ב-CSS | תיאור |
|----------|-------------|-------|
| מותאמת אישית | `[data-theme="custom"]` | ערכה שהמשתמש יצר בעצמו |
| ציבורית/משותפת | `[data-theme^="shared:"]` | ערכה מיובאת או ציבורית |
| כהה | `[data-theme="dark"]` | ערכת Dark מובנית |
| עמומה | `[data-theme="dim"]` | ערכת Dim מובנית |
| ערפילית | `[data-theme="nebula"]` | ערכת Nebula מובנית |

**לא יוצג** בערכות: `classic`, `ocean`, `rose-pine-dawn` (שכבר תומכות בכפתור צבע רקע באופן טבעי).

---

## לוגיקת הפעולה

### 1. מצב רגיל (ברירת מחדל)
- התצוגה משתמשת בצבעי הערכה הכהה הנוכחית
- כפתור "צבע רקע" **מוסתר**
- כפתור "קלאסי" מציג טקסט: `🎨 קלאסי`

### 2. מצב קלאסי (לאחר לחיצה)
- התצוגה עוברת לסגנון הערכה הקלאסית (רקע לבן, צבעי טקסט כהים)
- כפתור "צבע רקע" **מוצג** ופעיל
- כפתור "קלאסי" משתנה ל: `🌙 חזור לערכה`
- המשתמש יכול לבחור מ-4 גווני רקע (לבן, חום בהיר, בינוני, כהה)

### 3. חזרה למצב רגיל
- לחיצה נוספת על הכפתור מחזירה לתצוגת הערכה הכהה
- כפתור "צבע רקע" חוזר להסתתר
- בחירת צבע הרקע **נשמרת** ותוחל בפעם הבאה שהמשתמש יעבור למצב קלאסי

---

## הבעיה המרכזית שהפתרון פותר

### מה קורה היום?

בערכות כהות (כמו ערכה מותאמת אישית סגולה, או ערכה ציבורית), כשהמשתמש בוחר צבע רקע בהיר:

```css
/* הערכה הכהה מגדירה: */
[data-theme="custom"] #md-content {
  background: var(--bg-primary);      /* רקע כהה */
  color: var(--text-primary);         /* טקסט בהיר! */
}

/* כשבוחרים רקע חום: */
#md-content.bg-light {
  background: #f5e6d3;                /* רקע משתנה */
  /* אבל color נשאר var(--text-primary) = בהיר! */
}
```

**התוצאה**: טקסט בהיר על רקע בהיר = לא קריא! 😖

### מה הפתרון עושה?

ה-CSS של `.classic-mode-active` דורס **את כל** הצבעים עם `!important`:

```css
#md-content.classic-mode-active {
  background: #ffffff !important;     /* רקע בהיר */
  color: #111111 !important;          /* טקסט כהה! ✅ */
}

#md-content.classic-mode-active h1 {
  color: #111111 !important;          /* כותרות כהות! ✅ */
}

#md-content.classic-mode-active a {
  color: #0366d6 !important;          /* קישורים כחולים! ✅ */
}
/* וכו'... */
```

**התוצאה**: כל האלמנטים מקבלים צבעים מותאמים לרקע הבהיר = קריא! 😊

---

## קבצים לעריכה

### 1. `webapp/templates/md_preview.html`

#### א. הוספת הכפתור ל-HTML (אחרי שורה ~1650)

```html
<!-- קבוצת כפתורי פעולה -->
<div class="md-toolbar-actions" style="display:flex;gap:0.5rem;align-items:center;">
  <!-- כפתור מצב קלאסי - מוצג רק בערכות כהות -->
  <button id="mdClassicModeBtn" 
          class="btn btn-secondary btn-icon md-classic-mode-btn" 
          title="עבור לתצוגה קלאסית"
          style="display:none;">
    <span class="classic-mode-icon">🎨</span>
    <span class="classic-mode-label">קלאסי</span>
  </button>
  
  <button id="mdFullscreenBtn" class="btn btn-secondary btn-icon" title="מסך מלא">
    <i class="fas fa-expand"></i>
    מסך מלא
  </button>
</div>
```

#### ב. הוספת CSS (בבלוק `<style>` הקיים, אחרי שורה ~700)

> **חשוב מאוד**: ה-CSS הזה דורס את **כל** צבעי הערכה הכהה - לא רק רקע, אלא גם טקסט, כותרות, קישורים, קוד, טבלאות וכו'.

```css
/* ========================================
   כפתור מצב קלאסי - Classic Mode Button
   ======================================== */

/* הסתרת הכפתור כברירת מחדל */
.md-classic-mode-btn {
  display: none !important;
}

/* הצגת הכפתור בערכות כהות בלבד */
:root[data-theme="custom"] .md-classic-mode-btn,
:root[data-theme^="shared:"] .md-classic-mode-btn,
:root[data-theme="dark"] .md-classic-mode-btn,
:root[data-theme="dim"] .md-classic-mode-btn,
:root[data-theme="nebula"] .md-classic-mode-btn {
  display: inline-flex !important;
}

/* עיצוב הכפתור */
.md-classic-mode-btn {
  gap: 0.4rem;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 14px;
  transition: all 0.2s ease;
  white-space: nowrap;
}

/* מצב פעיל (כשבמצב קלאסי) */
.md-classic-mode-btn.is-active {
  background: rgba(255, 255, 255, 0.2);
  border-color: rgba(255, 255, 255, 0.4);
}

/* ========================================
   מצב קלאסי - Classic Mode Overrides
   ========================================
   
   הסבר: בערכות כהות (custom, shared:*, dark, dim, nebula)
   הטקסט מוגדר כ-color: var(--text-primary) שהוא בהיר.
   כאשר מפעילים מצב קלאסי, חייבים לדרוס את כל הצבעים
   עם !important כדי לגבור על הגדרות הערכה.
   ======================================== */

/* === 1. צבעי בסיס - רקע וטקסט ראשי === */
#md-content.classic-mode-active {
  background: #ffffff !important;
  color: #111111 !important;
  
  /* משתני CSS מהערכה הקלאסית */
  --md-mark-bg: #fff2a8;
  --md-inline-code-bg: #f6f8fa;
  --md-inline-code-border: #d0d7de;
  --md-inline-code-color: #1f2328;
  --md-code-border: #d0d7de;
  --md-code-shell-bg: #e6edf4;
  --md-code-header-bg: #e6edf4;
  --md-code-header-text: #57606a;
  --md-code-bg: #f6f8fa;
  --md-code-text: #24292f;
  --md-code-shadow: 0 12px 24px rgba(15, 23, 42, 0.08);
  --md-code-copy-bg: #ffffff;
  --md-code-copy-border: #d0d7de;
  --md-code-copy-color: #57606a;
  --md-code-copy-hover-bg: #e6ebf1;
  --md-code-copy-success-color: #1a7f37;
  --md-code-copy-error-color: #b42318;
  --md-code-lang-bg: #dce3eb;
  --md-code-lang-text: #24292f;
  --hljs-text: #24292f;
  --hljs-keyword: #cf222e;
  --hljs-string: #0a3069;
  --hljs-function: #8250df;
  --hljs-comment: #6e7781;
  --hljs-number: #0550ae;
  --hljs-operator: #24292f;
  --hljs-addition-text: #1a7f37;
  --hljs-addition-bg: rgba(26, 127, 55, 0.12);
  --hljs-deletion-text: #cf222e;
  --hljs-deletion-bg: rgba(207, 34, 46, 0.15);
  --md-blockquote-bg: #eef2f7;
  --md-blockquote-border: #cbd5e1;
  --md-blockquote-color: #0f172a;
  --md-table-border: #e5e7eb;
  --md-table-header-bg: #f8fafc;
  --md-fold-bg: #f6f6f6;
  --md-fold-border: rgba(0,0,0,0.06);
}

/* === 2. כותרות - צבע כהה וגבולות === */
#md-content.classic-mode-active h1,
#md-content.classic-mode-active h2,
#md-content.classic-mode-active h3,
#md-content.classic-mode-active h4,
#md-content.classic-mode-active h5,
#md-content.classic-mode-active h6 {
  color: #111111 !important;
}

#md-content.classic-mode-active h1,
#md-content.classic-mode-active h2 {
  border-bottom-color: #e1e4e8 !important;
}

/* === 3. פסקאות ורשימות === */
#md-content.classic-mode-active p,
#md-content.classic-mode-active li,
#md-content.classic-mode-active span,
#md-content.classic-mode-active div {
  color: inherit !important;
}

/* === 4. קישורים - כחול קלאסי === */
#md-content.classic-mode-active a {
  color: #0366d6 !important;
}

#md-content.classic-mode-active a:hover {
  color: #0256c7 !important;
}

#md-content.classic-mode-active a::after {
  background: #0366d6 !important;
}

/* === 5. קוד inline === */
#md-content.classic-mode-active code:not(pre code) {
  background: #f6f8fa !important;
  color: #1f2328 !important;
  border: 1px solid #d0d7de !important;
}

/* === 6. בלוקי קוד (pre) === */
#md-content.classic-mode-active pre {
  background: #f6f8fa !important;
  border: 1px solid #d0d7de !important;
  box-shadow: 0 12px 24px rgba(15, 23, 42, 0.08) !important;
}

#md-content.classic-mode-active pre code,
#md-content.classic-mode-active code.hljs {
  color: #24292f !important;
  background: transparent !important;
}

/* === 7. Syntax Highlighting (highlight.js) === */
#md-content.classic-mode-active .hljs-keyword { color: #cf222e !important; }
#md-content.classic-mode-active .hljs-string { color: #0a3069 !important; }
#md-content.classic-mode-active .hljs-function,
#md-content.classic-mode-active .hljs-title { color: #8250df !important; }
#md-content.classic-mode-active .hljs-comment { color: #6e7781 !important; }
#md-content.classic-mode-active .hljs-number { color: #0550ae !important; }
#md-content.classic-mode-active .hljs-operator { color: #24292f !important; }
#md-content.classic-mode-active .hljs-variable { color: #953800 !important; }
#md-content.classic-mode-active .hljs-built_in { color: #0550ae !important; }
#md-content.classic-mode-active .hljs-attr { color: #0550ae !important; }
#md-content.classic-mode-active .hljs-tag { color: #116329 !important; }
#md-content.classic-mode-active .hljs-name { color: #116329 !important; }
#md-content.classic-mode-active .hljs-selector-tag { color: #116329 !important; }
#md-content.classic-mode-active .hljs-selector-class { color: #6639ba !important; }
#md-content.classic-mode-active .hljs-addition { 
  color: #1a7f37 !important;
  background: rgba(26, 127, 55, 0.12) !important;
}
#md-content.classic-mode-active .hljs-deletion { 
  color: #cf222e !important;
  background: rgba(207, 34, 46, 0.15) !important;
}

/* === 8. ציטוטים (blockquote) === */
#md-content.classic-mode-active blockquote {
  background: #eef2f7 !important;
  border-inline-start-color: #cbd5e1 !important;
  color: #0f172a !important;
}

/* === 9. טבלאות === */
#md-content.classic-mode-active table {
  border-color: #e5e7eb !important;
}

#md-content.classic-mode-active table th,
#md-content.classic-mode-active table td {
  border-color: #e5e7eb !important;
  color: #111111 !important;
}

#md-content.classic-mode-active table thead {
  background: #f8fafc !important;
}

#md-content.classic-mode-active table thead th {
  color: #111111 !important;
}

/* === 10. רשימות משימות (checkboxes) === */
#md-content.classic-mode-active input[type="checkbox"] {
  accent-color: #0366d6 !important;
}

/* === 11. קווים אופקיים (hr) === */
#md-content.classic-mode-active hr {
  border-color: #e1e4e8 !important;
  background: #e1e4e8 !important;
}

/* === 12. הדגשה (mark) === */
#md-content.classic-mode-active mark {
  background: #fff2a8 !important;
  color: #111111 !important;
}

/* === 13. Admonitions/Callouts === */
#md-content.classic-mode-active .admonition,
#md-content.classic-mode-active .callout {
  color: #111111 !important;
}

/* === 14. כותרת בלוק קוד (שם קובץ/שפה) === */
#md-content.classic-mode-active .code-block-header,
#md-content.classic-mode-active .code-header {
  background: #e6edf4 !important;
  color: #57606a !important;
}

#md-content.classic-mode-active .code-lang-badge {
  background: #dce3eb !important;
  color: #24292f !important;
}

/* === 15. כפתור העתקה בבלוקי קוד === */
#md-content.classic-mode-active .copy-btn,
#md-content.classic-mode-active .code-copy-btn {
  background: #ffffff !important;
  border-color: #d0d7de !important;
  color: #57606a !important;
}

#md-content.classic-mode-active .copy-btn:hover,
#md-content.classic-mode-active .code-copy-btn:hover {
  background: #e6ebf1 !important;
}

/* === 16. קיפולים (details/summary) === */
#md-content.classic-mode-active details {
  border-color: rgba(0,0,0,0.1) !important;
}

#md-content.classic-mode-active details > summary {
  color: #111111 !important;
}

#md-content.classic-mode-active details > .md-section-content {
  background: #f6f6f6 !important;
}

/* ========================================
   צבעי רקע חומים במצב קלאסי
   (משחזר את כל גווני הטקסט לכהים)
   ======================================== */

/* --- נייר חם (Sepia) --- */
#md-content.classic-mode-active.bg-sepia {
  background: #fdf6e3 !important;
  color: #586e75 !important;
  --md-code-bg: #eee8d5;
  --md-code-text: #657b83;
  --hljs-text: #657b83;
  --hljs-keyword: #859900;
  --hljs-string: #2aa198;
  --hljs-function: #268bd2;
  --hljs-comment: #93a1a1;
  --hljs-number: #b58900;
  --md-fold-bg: #fff3dc;
}

#md-content.classic-mode-active.bg-sepia h1,
#md-content.classic-mode-active.bg-sepia h2,
#md-content.classic-mode-active.bg-sepia h3,
#md-content.classic-mode-active.bg-sepia h4 {
  color: #073642 !important;
}

#md-content.classic-mode-active.bg-sepia code:not(pre code) {
  background: rgba(255, 255, 255, 0.45) !important;
  border-color: rgba(0, 0, 0, 0.08) !important;
  color: #2c2520 !important;
}

#md-content.classic-mode-active.bg-sepia pre {
  background: #eee8d5 !important;
  border-color: #d3cbb7 !important;
}

#md-content.classic-mode-active.bg-sepia blockquote {
  background: rgba(255, 255, 255, 0.3) !important;
  border-inline-start-color: rgba(0, 0, 0, 0.2) !important;
}

#md-content.classic-mode-active.bg-sepia table thead {
  background: rgba(255, 255, 255, 0.3) !important;
}

#md-content.classic-mode-active.bg-sepia table th,
#md-content.classic-mode-active.bg-sepia table td {
  border-color: rgba(0, 0, 0, 0.1) !important;
  color: #586e75 !important;
}

/* --- חום בהיר --- */
#md-content.classic-mode-active.bg-light {
  background: #f5e6d3 !important;
  color: #2b2b2b !important;
  --md-code-bg: #eddcc4;
  --md-code-text: #5a4a3a;
  --hljs-text: #5a4a3a;
  --hljs-keyword: #a67c52;
  --hljs-string: #6b8e23;
  --hljs-function: #4682b4;
  --hljs-comment: #8b7d6b;
  --hljs-number: #c97b63;
  --md-fold-bg: #fbf2e6;
}

#md-content.classic-mode-active.bg-light h1,
#md-content.classic-mode-active.bg-light h2,
#md-content.classic-mode-active.bg-light h3,
#md-content.classic-mode-active.bg-light h4 {
  color: #1a1a1a !important;
}

#md-content.classic-mode-active.bg-light code:not(pre code) {
  background: rgba(255, 255, 255, 0.4) !important;
  border-color: rgba(0, 0, 0, 0.1) !important;
  color: #2b2b2b !important;
}

#md-content.classic-mode-active.bg-light pre {
  background: #eddcc4 !important;
  border-color: #e6d4bc !important;
}

#md-content.classic-mode-active.bg-light pre code {
  color: #5a4a3a !important;
}

#md-content.classic-mode-active.bg-light blockquote {
  background: rgba(255, 255, 255, 0.3) !important;
  border-inline-start-color: rgba(0, 0, 0, 0.2) !important;
}

#md-content.classic-mode-active.bg-light table thead {
  background: rgba(255, 255, 255, 0.3) !important;
}

#md-content.classic-mode-active.bg-light table th,
#md-content.classic-mode-active.bg-light table td {
  border-color: rgba(0, 0, 0, 0.1) !important;
  color: #2b2b2b !important;
}

/* --- חום בינוני --- */
#md-content.classic-mode-active.bg-medium {
  background: #e8d4b0 !important;
  color: #1f1f1f !important;
  --md-code-bg: #dcc9a8;
  --md-code-text: #4a3d2f;
  --hljs-text: #4a3d2f;
  --hljs-keyword: #8b6914;
  --hljs-string: #2e8b57;
  --hljs-function: #4169e1;
  --hljs-comment: #7a6e5d;
  --hljs-number: #c97b63;
  --md-fold-bg: #f2e2c8;
}

#md-content.classic-mode-active.bg-medium h1,
#md-content.classic-mode-active.bg-medium h2,
#md-content.classic-mode-active.bg-medium h3,
#md-content.classic-mode-active.bg-medium h4 {
  color: #111111 !important;
}

#md-content.classic-mode-active.bg-medium code:not(pre code) {
  background: rgba(255, 255, 255, 0.35) !important;
  border-color: rgba(0, 0, 0, 0.12) !important;
  color: #2b241b !important;
}

#md-content.classic-mode-active.bg-medium pre {
  background: #dcc9a8 !important;
  border-color: #d4c19c !important;
}

#md-content.classic-mode-active.bg-medium pre code {
  color: #4a3d2f !important;
}

#md-content.classic-mode-active.bg-medium blockquote {
  background: rgba(255, 255, 255, 0.3) !important;
  border-inline-start-color: rgba(0, 0, 0, 0.2) !important;
}

#md-content.classic-mode-active.bg-medium table thead {
  background: rgba(255, 255, 255, 0.3) !important;
}

#md-content.classic-mode-active.bg-medium table th,
#md-content.classic-mode-active.bg-medium table td {
  border-color: rgba(0, 0, 0, 0.1) !important;
  color: #1f1f1f !important;
}

/* --- חום כהה --- */
#md-content.classic-mode-active.bg-dark {
  background: #d4b896 !important;
  color: #111111 !important;
  --md-code-bg: #c9ae88;
  --md-code-text: #3d3020;
  --hljs-text: #3d3020;
  --hljs-keyword: #8b4513;
  --hljs-string: #228b22;
  --hljs-function: #4682b4;
  --hljs-comment: #6b5d4f;
  --hljs-number: #d2691e;
  --md-fold-bg: #e8d2b4;
}

#md-content.classic-mode-active.bg-dark h1,
#md-content.classic-mode-active.bg-dark h2,
#md-content.classic-mode-active.bg-dark h3,
#md-content.classic-mode-active.bg-dark h4 {
  color: #0a0a0a !important;
}

#md-content.classic-mode-active.bg-dark code:not(pre code) {
  background: rgba(255, 255, 255, 0.3) !important;
  border-color: rgba(0, 0, 0, 0.15) !important;
  color: #2b1f16 !important;
}

#md-content.classic-mode-active.bg-dark pre {
  background: #c9ae88 !important;
  border-color: #c4a882 !important;
}

#md-content.classic-mode-active.bg-dark pre code {
  color: #3d3020 !important;
}

#md-content.classic-mode-active.bg-dark blockquote {
  background: rgba(255, 255, 255, 0.3) !important;
  border-inline-start-color: rgba(0, 0, 0, 0.2) !important;
}

#md-content.classic-mode-active.bg-dark table thead {
  background: rgba(255, 255, 255, 0.3) !important;
}

#md-content.classic-mode-active.bg-dark table th,
#md-content.classic-mode-active.bg-dark table td {
  border-color: rgba(0, 0, 0, 0.1) !important;
  color: #111111 !important;
}

/* ========================================
   הצגת כפתור צבע רקע במצב קלאסי
   ======================================== */
#mdCard.classic-mode-enabled #bgColorSwitcher {
  display: inline-flex !important;
}
```

#### ג. הוספת JavaScript (בסוף הקובץ, לפני `{% endblock %}`)

```javascript
// ========================================
// Classic Mode Toggle - מצב קלאסי
// ========================================
(function initClassicModeToggle() {
  const STORAGE_KEY = 'md_classic_mode_enabled';
  const DARK_THEMES = new Set(['custom', 'dark', 'dim', 'nebula']);
  
  const classicBtn = document.getElementById('mdClassicModeBtn');
  const mdContent = document.getElementById('md-content');
  const mdCard = document.getElementById('mdCard');
  const bgColorSwitcher = document.getElementById('bgColorSwitcher');
  
  if (!classicBtn || !mdContent) return;
  
  // בדיקה אם הערכה הנוכחית היא כהה
  function isDarkTheme() {
    const currentTheme = document.documentElement.getAttribute('data-theme') || '';
    if (DARK_THEMES.has(currentTheme)) return true;
    if (currentTheme.startsWith('shared:')) return true;
    return false;
  }
  
  // הצגת/הסתרת הכפתור לפי הערכה
  function updateButtonVisibility() {
    if (isDarkTheme()) {
      classicBtn.style.display = 'inline-flex';
    } else {
      classicBtn.style.display = 'none';
      // אם לא בערכה כהה, נקה מצב קלאסי
      disableClassicMode();
    }
  }
  
  // קריאת מצב שמור
  function getSavedState() {
    try {
      return localStorage.getItem(STORAGE_KEY) === 'true';
    } catch(_) {
      return false;
    }
  }
  
  // שמירת מצב
  function saveState(enabled) {
    try {
      if (enabled) {
        localStorage.setItem(STORAGE_KEY, 'true');
      } else {
        localStorage.removeItem(STORAGE_KEY);
      }
    } catch(_) {}
  }
  
  // הפעלת מצב קלאסי
  function enableClassicMode() {
    mdContent.classList.add('classic-mode-active');
    if (mdCard) mdCard.classList.add('classic-mode-enabled');
    classicBtn.classList.add('is-active');
    
    // עדכון טקסט הכפתור
    const icon = classicBtn.querySelector('.classic-mode-icon');
    const label = classicBtn.querySelector('.classic-mode-label');
    if (icon) icon.textContent = '🌙';
    if (label) label.textContent = 'חזור לערכה';
    classicBtn.title = 'חזור לתצוגת הערכה הכהה';
    
    // הצגת כפתור צבע רקע
    if (bgColorSwitcher) {
      bgColorSwitcher.style.display = 'inline-flex';
    }
    
    // טעינת צבע רקע שמור (אם יש)
    const savedBgColor = localStorage.getItem('md_bg_color_preference');
    if (savedBgColor && typeof applyBackgroundColor === 'function') {
      applyBackgroundColor(savedBgColor);
    }
    
    saveState(true);
  }
  
  // כיבוי מצב קלאסי
  function disableClassicMode() {
    mdContent.classList.remove('classic-mode-active');
    mdContent.classList.remove('bg-sepia', 'bg-light', 'bg-medium', 'bg-dark');
    if (mdCard) mdCard.classList.remove('classic-mode-enabled');
    classicBtn.classList.remove('is-active');
    
    // עדכון טקסט הכפתור
    const icon = classicBtn.querySelector('.classic-mode-icon');
    const label = classicBtn.querySelector('.classic-mode-label');
    if (icon) icon.textContent = '🎨';
    if (label) label.textContent = 'קלאסי';
    classicBtn.title = 'עבור לתצוגה קלאסית';
    
    // הסתרת כפתור צבע רקע (רק בערכות כהות)
    if (bgColorSwitcher && isDarkTheme()) {
      bgColorSwitcher.style.display = 'none';
    }
    
    saveState(false);
  }
  
  // Toggle
  function toggleClassicMode() {
    if (mdContent.classList.contains('classic-mode-active')) {
      disableClassicMode();
    } else {
      enableClassicMode();
    }
  }
  
  // אתחול
  function init() {
    updateButtonVisibility();
    
    // שחזור מצב שמור
    if (isDarkTheme() && getSavedState()) {
      enableClassicMode();
    }
    
    // האזנה ללחיצה
    classicBtn.addEventListener('click', toggleClassicMode);
    
    // האזנה לשינוי ערכה (אם המשתמש מחליף ערכה)
    const observer = new MutationObserver((mutations) => {
      mutations.forEach((mutation) => {
        if (mutation.attributeName === 'data-theme') {
          updateButtonVisibility();
        }
      });
    });
    
    observer.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ['data-theme']
    });
  }
  
  // הפעלה
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
```

---

## סיכום שינויים נדרשים

### HTML
1. הוספת `<div class="md-toolbar-actions">` לעטיפת כפתורי הפעולה
2. הוספת כפתור `#mdClassicModeBtn` לפני כפתור מסך מלא

### CSS
1. כללי הסתרה/הצגה לכפתור לפי ערכה
2. מחלקה `.classic-mode-active` עם כל המשתנים של הערכה הקלאסית
3. תמיכה בצבעי רקע חומים במצב קלאסי
4. כלל להצגת `#bgColorSwitcher` במצב קלאסי

### JavaScript
1. פונקציות `enableClassicMode()` ו-`disableClassicMode()`
2. שמירת המצב ב-localStorage
3. שחזור מצב בטעינת הדף
4. MutationObserver לזיהוי שינוי ערכה

---

## בדיקות נדרשות

### תרחישי בדיקה

| # | תרחיש | תוצאה צפויה |
|---|-------|-------------|
| 1 | טעינת עמוד בערכה קלאסית | כפתור "קלאסי" **לא מוצג** |
| 2 | טעינת עמוד בערכה כהה | כפתור "קלאסי" **מוצג** |
| 3 | לחיצה על "קלאסי" | רקע לבן, כפתור צבע רקע מופיע |
| 4 | בחירת צבע רקע חום | הרקע משתנה, נשמר |
| 5 | לחיצה על "חזור לערכה" | חזרה לצבעי הערכה הכהה |
| 6 | רענון דף לאחר הפעלת מצב קלאסי | המצב משוחזר אוטומטית |
| 7 | החלפת ערכה מכהה לבהירה | הכפתור נעלם, מצב קלאסי מתבטל |

### ערכות לבדיקה
- `custom` (ערכה מותאמת אישית)
- `shared:*` (ערכה ציבורית)
- `dark`, `dim`, `nebula`
- `classic`, `ocean`, `rose-pine-dawn` (לוודא שהכפתור לא מופיע)

---

## הערות טכניות

### 1. עדיפות CSS
השימוש ב-`!important` הכרחי כדי לדרוס את ערכי הערכה הכהה שמוגדרים עם specificity גבוה.

### 2. תאימות עם כפתור צבע רקע
הקוד הקיים של צבע הרקע (`ALLOWED_THEMES`) צריך להתעדכן כדי לתמוך גם במצב קלאסי:

```javascript
// שורה ~3097 - עדכון התנאי
const ALLOWED_THEMES = new Set(['classic', 'ocean', 'rose-pine-dawn']);

// הוספה: בדיקה גם למצב קלאסי פעיל
const isClassicModeActive = document.getElementById('md-content')?.classList.contains('classic-mode-active');
if (!ALLOWED_THEMES.has(currentTheme) && !isClassicModeActive) {
  // הסתר כפתור
}
```

### 3. שמירת מצב
- מצב קלאסי: `localStorage.setItem('md_classic_mode_enabled', 'true')`
- צבע רקע: `localStorage.setItem('md_bg_color_preference', 'light')`

שני הערכים נשמרים בנפרד כדי לאפשר העדפות עצמאיות.

---

## דוגמת שימוש

### למשתמש
1. נכנס לתצוגת Markdown של מסמך
2. אם בערכה כהה (למשל ערכה מיובאת סגולה)
3. לוחץ על כפתור "🎨 קלאסי"
4. התצוגה עוברת לרקע לבן קריא
5. לוחץ על "צבע רקע" ובוחר "חום בהיר"
6. ממשיך לקרוא בנוחות
7. בסיום, לוחץ "🌙 חזור לערכה" (או פשוט עוזב - המצב נשמר)

---

## סיכום

הפיצ'ר מאפשר למשתמשים בערכות כהות ליהנות מתצוגת Markdown קריאה יותר מבלי לשנות את הערכה הכללית שלהם. זהו פתרון נוח במיוחד עבור:

- משתמשים שאוהבים ערכות כהות אבל מעדיפים לקרוא טקסט על רקע בהיר
- מסמכים ארוכים שקשה לקרוא ברקע כהה
- מעבר מהיר בין מצבים ללא שינוי הגדרות גלובליות

---

*מדריך זה נכתב כהנחיה למימוש. יש לבדוק תאימות עם שאר הקוד לפני הטמעה.*
