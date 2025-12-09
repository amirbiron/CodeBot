# Migration Plan: Step 1 (Bookmarks)

תוכנית זו מתמקדת במיגרציה של מודול ה-Bookmarks בלבד לשימוש ב-`variables.css`.

## יעד
**קובץ מטרה:** `webapp/static/css/bookmarks.css`
**סטטוס:** יש לשכתב את הקובץ לשימוש במשתנים הגלובליים ולמחוק את המשתנים המקומיים.

---

## 1. Pre-requisites
- [ ] ודא ש-`variables.css` נטען ב-`base.html` (או בקובץ הראשי שנטען בכל עמוד) **לפני** `bookmarks.css`.

## 2. Variables Mapping

בצע חיפוש והחלפה (Find & Replace) בקובץ `bookmarks.css`:

| חפש את... | והחלף ב... | הערות |
|-----------|------------|-------|
| `var(--bookmarks-panel-bg)` | `var(--bg-panel)` | |
| `var(--bookmarks-panel-shadow)` | `var(--shadow-overlay)` | |
| `var(--bookmarks-hover-bg)` | `var(--glass-subtle)` | בדיקה: האם 0.05 מספיק? |
| `var(--bookmarks-border-color)` | `var(--glass-border)` | |
| `var(--bookmarks-text-primary)` | `var(--text-main)` | |
| `var(--bookmarks-text-secondary)`| `var(--text-secondary)` | |
| `var(--bookmarks-notification-bg)`| `var(--bg-card)` | או `--bg-overlay` אם רוצים כהה יותר |
| `var(--bookmarks-notification-color)`| `var(--text-main)` | |
| `var(--bookmarks-success-color)` | `var(--color-success)` | |
| `var(--bookmarks-error-color)` | `var(--color-error)` | |
| `var(--bookmarks-warning-color)` | `var(--color-warning)` | |
| `var(--bookmarks-info-color)` | `var(--color-info)` | |

## 3. Delete Definitions

לאחר ההחלפה, יש **למחוק** את כל בלוקי הגדרת המשתנים מ-`bookmarks.css`:

1.  מחק את כל הבלוק `:root { ... }` בתחילת הקובץ (שורות 2-22).
2.  מחק את כל הבלוקים של `:root[data-theme="..."]` (שורות 24-73).
    *   **שים לב:** אם יש משתנים ייחודיים שלא הוגדרו ב-`variables.css` (כמו צבעי הסימניות `--bookmark-yellow` וכו'), יש להעביר אותם ל-`variables.css` או להשאיר ב-`bookmarks.css` תחת `:root` בלבד (ללא overrides, אלא אם כן הצבעים משתנים לפי theme).
    *   *המלצה:* את `--bookmark-yellow` ודומיו כדאי להשאיר כרגע ב-`bookmarks.css` כי הם ספציפיים למודול זה, או להעביר ל-`variables.css` תחת קטגוריית "Module specific". בתוכנית זו נניח שמשאירים אותם ב-`bookmarks.css` (רק את הצבעים, ללא הפאנל/צללים).

## 4. Specific Adjustments

-   **Toggle Button:**
    -   `border: 1px solid rgba(0, 0, 0, 0.12)` -> `border: 1px solid var(--glass-border)`
    -   `background: radial-gradient(...)` -> לבדוק אם צריך התאמה ל-Dark Mode.

-   **Line Highlight:**
    -   `rgba(255, 215, 0, 0.3)` -> אולי משתנה `--highlight-bg`? (לשקול לשלב הבא).

## 5. Verification
-   פתח את הפאנל ב-Dark Theme וודא שהרקע כהה (`#16213e`).
-   עבור ל-Ocean Theme וודא שהרקע כחלחל והצללים כחולים.
-   עבור ל-High Contrast וודא שהרקע שחור מוחלט.
