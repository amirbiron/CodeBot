# Variables Cleanup Plan (Approved)

תוכנית זו עודכנה בהתאם למשוב ואושרה לביצוע. היא מתמקדת ביצירת מערכת משתנים היררכית, תמיכה ב-Themes, ומיגרציה מדורגת.

## 1. מבנה המשתנים החדש

### Glassmorphism System (3 רמות)
במקום ערכים בודדים, ניצור מערכת מדורגת לשקיפויות:
-   `--glass-subtle`: `rgba(255, 255, 255, 0.05)` (עבור רקעים משניים, hover עדין)
-   `--glass-normal`: `rgba(255, 255, 255, 0.08)` (הערך הנפוץ ביותר - כרטיסים, פאנלים)
-   `--glass-strong`: `rgba(255, 255, 255, 0.12)` (עבור מצבי hover חזקים, אלמנטים מודגשים)

### Dynamic Shadows
שימוש במשתנה צבע בסיס לצללים כדי לאפשר התאמה ל-Themes (למשל צל כחול ב-Ocean Theme):
-   `--shadow-color`: `rgba(0, 0, 0, 0.2)` (בסיס)
-   `--shadow-overlay`: `0 20px 45px var(--shadow-color)`
-   `--shadow-card`: `0 4px 12px var(--shadow-color)`

### Programming Languages
הפרדה ברורה בין צבעי קוד לצבעי מותג:
1.  **Syntax Highlighting:** צבעים לשימוש בתוך עורך הקוד (`--syntax-keyword`, `--syntax-string`).
2.  **Language Brand Colors:** צבעים לשימוש באייקונים, תגיות וממשק (`--lang-js`, `--lang-python`).

---

## 2. משתנים כפולים וספציפיים לטיפול

### משתנים לביטול (Deprecated)
המשתנים הבאים יוחלפו במקביליהם הגלובליים:

| משתנה ישן | משתנה חדש (גלובלי) | הערות |
|-----------|-------------------|-------|
| `--bookmarks-panel-bg` | `--bg-overlay` / `--bg-panel` | תלוי בהקשר (Overlay מלא או צדדי) |
| `--bookmarks-border-color` | `--glass-border` | |
| `--bookmarks-hover-bg` | `--glass-subtle` | |
| `--bookmarks-text-primary` | `--text-main` | |
| `--bookmarks-text-secondary`| `--text-secondary` | |
| `--bookmarks-panel-shadow` | `--shadow-overlay` | |
| `--search-card-bg` | `--bg-card` | |
| `--search-highlight-text` | `--text-main` / `--text-inverse`| |

---

## 3. אסטרטגיית המרה (Migration Strategy)

התהליך יבוצע בשלבים כדי למנוע רגרסיה.

### שלב 1: Bookmarks Refactor
**מטרה:** ניקוי מלא של `bookmarks.css` והתבססות על `variables.css`.
1.  הוספת `variables.css` לפרויקט.
2.  מחיקת הגדרות המשתנים המקומיות ב-`bookmarks.css`.
3.  החלפת השימושים ב-`bookmarks.css` למשתנים הגלובליים.
4.  בדיקה ויזואלית של הבוקמארקס בכל ה-Themes.

### שלב 2: Global Search Refactor
1.  החלפת משתני `--search-*` במשתנים הגלובליים.
2.  שימוש במשתני `--syntax-*` ו-`--lang-*` החדשים.

### שלב 3: General Cleanup
1.  מעבר על `templates` והחלפת Inline Styles.
2.  ניקוי משתנים כפולים מ-`main.css` וקבצים אחרים.

---

## 4. סיכום
קובץ `variables.css` יהווה את המקור היחיד לאמת (SSOT). כל Theme (כמו `theme-ocean.css`) יצטרך רק לדרוס את המשתנים הסמנטיים (כמו `--bg-app`, `--shadow-color`) ולא להגדיר משתנים חדשים.
