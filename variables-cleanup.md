# Variables Cleanup Plan

תוכנית זו מבוססת על ניתוח הקוד הקיים ב-`webapp/static/css` ודוח הביקורת `css-audit-report-filtered.md`. המטרה היא לפשט את ניהול הצבעים, למנוע כפילויות, ולשפר את העקביות.

## 1. משתנים כפולים (Duplicate Variables)

נמצאו מספר קבוצות של משתנים המגדירים את אותם ערכים תחת שמות שונים, או משתנים עם אותו שם אך ערכים סותרים שניתן לאחד.

### --bookmarks-border-color (6 הגדרות)
**מיקומים:**
- `bookmarks.css` (מוגדר ב-6 מקומות שונים לפי Themes):
  - `rgba(0, 0, 0, 0.06)`
  - `rgba(255, 255, 255, 0.1)`
  - `rgba(49, 130, 206, 0.25)`
  - ועוד...

**הצעה:**
- שם מאוחד: `--border-color`
- ערך ברירת מחדל: `rgba(255, 255, 255, 0.1)` (תואם לשימוש הנפוץ ביותר של Glassmorphism)
- **פעולה:** הסרת המשתנה הספציפי והחלפתו ב-`--border-color` הגלובלי, כאשר כל Theme יעדכן את `--border-color` במקום משתנה ייעודי לבוקמארקס.

### --search-highlight-text (6 הגדרות)
**מיקומים:**
- `global_search.css`: מוגדר 6 פעמים עם ערכים שונים (`#1a202c`, `#ffffff`, `#000000`...)

**הצעה:**
- שימוש במשתנה קיים: `--text-on-light` או `--text-on-dark` בהתאם לרקע.
- אם הרקע משתנה (Highlight), יש להשתמש ב-`--text-highlight` (שם חדש) שיוגדר גלובלית.

### שפות תכנות (--lang-js, --lang-ts, וכו')
**בעיה:**
כל שפה מוגדרת בנפרד עם 6 וריאציות (Themes). בנוסף, יש כפילויות בערכים (למשל `#00ffff` משמש גם ל-Markdown, TS, Go, CSS, React ב-High Contrast).

**הצעה:**
- איחוד לקבוצת צבעים סמנטית ב-`variables.css`:
  - `--syntax-string`
  - `--syntax-keyword`
  - `--syntax-function`
  - `--syntax-comment`
- שיוך השפות לצבעים הסמנטיים במקום משתנה לכל שפה, אלא אם כן יש צורך מובהק בצבע אייקון ייחודי.

---

## 2. משתנים ספציפיים מדי (Over-specific Variables)

משתנים אלו מוגבלים לרכיב ספציפי (Prefix) אך מחזיקים ערכים גנריים.

### --bookmarks-panel-bg, --search-card-bg
**מיקומים:**
- `bookmarks.css`: `rgba(255, 255, 255, 0.97)`, `#000000`, וכו'.
- `global_search.css`: `var(--card-bg, rgba(255,255,255,0.12))`, `#000000`.

**הצעה:**
- איחוד ל: `--panel-bg` או שימוש ב-`--card-bg` הקיים.
- **יתרון:** אחידות בין החלונית של החיפוש לחלונית הבוקמארקס. כרגע החיפוש שקוף יותר (0.12) והבוקמארקס אטום יותר (0.97/0.98). יש להחליט על עיצוב אחיד (למשל `--surface-overlay`).

### --search-card-shadow, --bookmarks-panel-shadow
**מיקומים:**
- שניהם מגדירים צללים דומים מאוד (`0 20px 45px ...`).

**הצעה:**
- איחוד ל: `--shadow-xl` או `--shadow-overlay`.
- **יתרון:** מניעת "Magic Numbers" של צללים בקוד.

### --bookmarks-text-primary, --search-code-text
**מיקומים:**
- שניהם משתמשים בוריאציות של צבע טקסט ראשי (`#ffffff`, `#212529`).

**הצעה:**
- החלפה ב: `--text-main` ו-`--text-secondary`.

---

## 3. משתנים חסרים (Missing Variables)

על בסיס `css-audit-report-filtered.md`, הצבעים הבאים מופיעים המון כ-Hard-coded וחסרים משתנה.

### #ffffff (131 מופעים)
**שימוש:** טקסט ראשי, אייקונים, גבולות בקונטרסט גבוה.
**הצעה:**
- שם: `--text-main` (כבר קיים חלקית, יש לאכוף שימוש).
- שם נוסף: `--text-on-dark` (לשימוש על רקעים כהים במפורש).

### rgba(255, 255, 255, 0.08) (32 מופעים)
**שימוש:** רקעים של כרטיסים, גבולות עדינים (Glassmorphism).
**הצעה:**
- שם: `--glass-surface`
- ערך: `rgba(255, 255, 255, 0.08)`

### rgba(255, 255, 255, 0.05) (25 מופעים)
**שימוש:** רקעים משניים, Hover states עדינים.
**הצעה:**
- שם: `--glass-surface-subtle` או `--hover-overlay`
- ערך: `rgba(255, 255, 255, 0.05)`

### #000000 (24 מופעים)
**שימוש:** רקעים ב-High Contrast, רקע לטרמינל/קוד.
**הצעה:**
- שם: `--black` (צבע בסיס)
- שם סמנטי: `--bg-terminal`

---

## 4. סיכום והמלצות

### מבנה מוצע לקובץ `variables.css`

קובץ זה יחליף את ההגדרות המפוזרות ויהווה את המקור היחיד לאמת (SSOT), למעט דריסות ב-Theme ספציפי.

```css
:root {
  /* --- Base Colors --- */
  --black: #000000;
  --white: #ffffff;
  --primary-color: #667eea;
  --primary-color-hover: #7c8fea;
  
  /* --- Semantic Backgrounds --- */
  --bg-app: #1a1a2e;       /* היה --bg-primary */
  --bg-panel: #16213e;     /* היה --bg-secondary */
  --bg-card: #252d48;      /* היה --card-bg */
  --bg-overlay: rgba(20, 23, 30, 0.95); /* איחוד של פאנלים */

  /* --- Text --- */
  --text-main: var(--white);
  --text-secondary: #b0b3c1;
  --text-muted: #6c7293;

  /* --- Glassmorphism System --- */
  --glass-surface: rgba(255, 255, 255, 0.08);       /* הנפוץ ביותר */
  --glass-surface-hover: rgba(255, 255, 255, 0.12);
  --glass-border: rgba(255, 255, 255, 0.1);
  --glass-blur: 10px;

  /* --- Borders & Shadows --- */
  --border-subtle: rgba(255, 255, 255, 0.1);
  --shadow-overlay: 0 20px 45px rgba(0, 0, 0, 0.2);

  /* --- Status --- */
  --color-success: #2cb67d;
  --color-error: #ef4444;
  --color-warning: #f59e0b;
}
```

### סדר ביצוע מומלץ (Action Plan)

1.  **שלב א' - יצירת התשתית:**
    *   יצירת קובץ `variables.css` מרכזי (או עדכון `base.css`).
    *   הגדרת כל המשתנים מהרשימה הנ"ל.

2.  **שלב ב' - Refactor של משתנים ספציפיים:**
    *   חיפוש והחלפה של `--bookmarks-panel-bg` ו-`--search-card-bg` ב-`--bg-overlay` (או משתנה מתאים אחר).
    *   חיפוש והחלפה של `--bookmarks-border-color` ב-`--glass-border`.
    *   מחיקת ההגדרות הישנות מקבצי ה-CSS הספציפיים (`bookmarks.css`, `global_search.css`).

3.  **שלב ג' - טיפול ב-Hard-coded Values:**
    *   מעבר על המופעים של `rgba(255, 255, 255, 0.08)` והחלפתם ב-`var(--glass-surface)`.
    *   מעבר על המופעים של `#ffffff` (במקומות הרלוונטיים) והחלפתם ב-`var(--text-main)`.

4.  **שלב ד' - ניקוי סופי:**
    *   מחיקת משתנים כפולים שלא בשימוש.
    *   וידוא שקבצי ה-Theme (`theme-ocean.css` וכו') דורסים רק את המשתנים הסמנטיים (`--bg-app`, `--text-main`) ולא מגדירים משתנים פרטיים משלהם.
