# Theme Matrix (תצוגה מקוצרת)

הטבלה הזו מהווה חיבור מהיר בין פלטות הצבעים לבין מדריך היישום. היא לא מחליפה את המסמכים המלאים אלא עוזרת לסמן במהירות אילו טוקנים קריטיים לכל ערכת נושא.

> **מקורות:**  
> - מדריך ארכיטקטורה: [`docs/webapp/theming_and_css.rst`](../docs/webapp/theming_and_css.rst)  
> - פירוט פלטות: [`webapp/FEATURE_SUGGESTIONS/webapp_theme_palettes.md`](../webapp/FEATURE_SUGGESTIONS/webapp_theme_palettes.md)  
> - ערכות מותאמות: [`docs/webapp/custom_themes_guide.rst`](../docs/webapp/custom_themes_guide.rst) (כולל Shared Themes ו-color-mix)

## כיסוי טוקנים חובה

| קבוצה | Dark / Dim / Nebula | Classic | Ocean | Forest | Rose Pine Dawn | High Contrast | Custom / Shared |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ``--bg-*`` + ``--text-*`` | מוגדרים מלא ב-`:root[data-theme]` | ✔️ | ✔️ (חובה בגרסאות כחול) | ✔️ (ירוק מלא) | ✔️ (ערכי ורוד/קרם) | נתון ב-`high-contrast.css` בלבד | מיובא מ-VS Code או מוגדר ידנית |
| ``--card-*`` | ✔️ | ✔️ | ✔️ | ✔️ | ✔️ | ✔️ (שחור/לבן) | ✔️ |
| ``--glass*`` | ✔️ (הלוגיקה ב-`dark-mode.css`) | משתמש בברירת המחדל השקופה | Override חצי שקוף כחול | Override חצי שקוף ירוק | Override ורוד שקוף | לבן שקוף + גבול לבן | ✔️ |
| ``--btn-primary-*`` | `color-mix` על סמך ``--bg-tertiary`` | טקסט כהה על לבן | טקסט כחול כהה על לבן | טקסט ירוק כהה על לבן | `color-mix` עם ורוד | שחור/לבן/צהוב בלבד | ✔️ |
| ``--md-surface`` / ``--md-text`` | כהה אחיד | כהה מותאם (`#15141f`) | כהה כחול (`#1a365d`) | כהה ירוק (`#1a4731`) | נשאר כהה כדי להגן על Highlight | שחור/לבן בהתאם לחוקים | ✔️ |
| ``--md-inline-code-bg`` | — | — | — | — | — | — | `color-mix` 12% ⬅️ |
| ``--md-table-*`` | — | — | — | — | — | — | `color-mix` 8-10% ⬅️ |
| ``--md-mermaid-*`` | — | — | — | — | — | — | `color-mix` 6-10% ⬅️ |
| ``--split-preview-*`` | מוגדר בערכי ברירת מחדל ב-`split-view.css` | ✔️ | ✔️ (rgba בגוון כחול) | ✔️ (rgba ירוק) | ✔️ (rgba סגלגל) | ✔️ (שחור/לבן/צהוב) | ✔️ |
| ``--search-*`` | משתמש בערכי ברירת מחדל כהים | צל ייחודי `rgba(7,7,31,0.35)` | צל כחול + הדגשת info | צל ירוק | מדגיש צבעי עץ | שחור/לבן עם צהוב (WCAG) | ✔️ |

## שמירת משתנים בפרסום ערכות

כשמפרסמים ערכה מותאמת לציבורית, חשוב לשמור את **כל** הנתונים המקוריים:

```javascript
// ב-theme_builder.html - שמירת נתונים בטעינת ערכה
let currentThemeOriginalVariables = { ...theme.variables };
let currentThemeSyntaxCss = theme.syntax_css || '';
let currentThemeSyntaxColors = theme.syntax_colors || {};

// בפרסום - מיזוג (ערכי טופס דורסים מקוריים)
const colors = { ...currentThemeOriginalVariables, ...collectThemeValues() };
```

**Whitelist:** משתני `--md-*` חייבים להיות ב-`theme_parser_service.py`:
```python
"--md-inline-code-bg", "--md-inline-code-border", "--md-inline-code-color",
"--md-table-bg", "--md-table-border", "--md-table-header-bg",
"--md-mermaid-bg",
```

> **טיפ:** אם ערכה לא מגדירה `--md-*`, אפשר לחשב עם `color-mix` (12% inline, 10% headers, 8% bg, 6% mermaid).

## Shared Themes ו-CSS Selectors

ערכות משותפות משתמשות ב-`data-theme="shared:slug"` אבל צריכות להתנהג כמו custom.

**הפתרון:** שימוש ב-`data-theme-type="custom"` בנוסף ל-selector הרגיל:

```css
/* תומך גם ב-custom וגם ב-shared */
[data-theme="custom"] .btn-primary,
[data-theme-type="custom"] .btn-primary {
    background: var(--btn-primary-bg);
}
```

## בדיקות רגרסיה

- **FOUC** – ודאו ש־`<html data-theme>` נקבע לפני טעינת CSS (ראו הסקריפט ב‑`base.html`).  
- **Live Preview** – טוען `--md-*` + `--split-*` גם כאשר Theme בהיר.  
- **High Contrast** – אסור להשתמש ב־`rgba` מלבד הערכים המוגדרים בקובץ הייעודי.  
- **Custom Theme** – ברגע שמזריקים ערכים ל‑``<style id="user-custom-theme">`` חובה לכסות את הטוקנים מהרשימה לעיל.
- **Shared Themes** – ודאו שכל selector של `[data-theme="custom"]` כולל גם `[data-theme-type="custom"]`.

הטבלה תעודכן בכל פעם שטוקן חדש נכנס לאחת הערכות. לצרכי עריכה, פתחו Issue קצר עם הפער והפנו אליו מה‑PR.
