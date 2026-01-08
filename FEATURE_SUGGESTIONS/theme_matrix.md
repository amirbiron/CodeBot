# Theme Matrix (תצוגה מקוצרת)

הטבלה הזו מהווה חיבור מהיר בין פלטות הצבעים לבין מדריך היישום. היא לא מחליפה את המסמכים המלאים אלא עוזרת לסמן במהירות אילו טוקנים קריטיים לכל ערכת נושא.

> **מקורות:**  
> - מדריך ארכיטקטורה: [`docs/webapp/theming_and_css.rst`](../docs/webapp/theming_and_css.rst)  
> - פירוט פלטות: [`webapp/FEATURE_SUGGESTIONS/webapp_theme_palettes.md`](../webapp/FEATURE_SUGGESTIONS/webapp_theme_palettes.md)

## כיסוי טוקנים חובה

| קבוצה | Dark / Dim / Nebula | Classic | Ocean | Forest | Rose Pine Dawn | High Contrast |
| --- | --- | --- | --- | --- | --- | --- |
| ``--bg-*`` + ``--text-*`` | מוגדרים מלא ב-`:root[data-theme]` | ✔️ | ✔️ (חובה בגרסאות כחול) | ✔️ (ירוק מלא) | ✔️ (ערכי ורוד/קרם) | נתון ב-`high-contrast.css` בלבד |
| ``--card-*`` | ✔️ | ✔️ | ✔️ | ✔️ | ✔️ | ✔️ (שחור/לבן) |
| ``--glass*`` | ✔️ (הלוגיקה ב-`dark-mode.css`) | משתמש בברירת המחדל השקופה | Override חצי שקוף כחול | Override חצי שקוף ירוק | Override ורוד שקוף | לבן שקוף + גבול לבן |
| ``--btn-primary-*`` | `color-mix` על סמך ``--bg-tertiary`` | טקסט כהה על לבן | טקסט כחול כהה על לבן | טקסט ירוק כהה על לבן | `color-mix` עם ורוד | שחור/לבן/צהוב בלבד |
| ``--md-surface`` / ``--md-text`` | כהה אחיד | כהה מותאם (`#15141f`) | כהה כחול (`#1a365d`) | כהה ירוק (`#1a4731`) | נשאר כהה כדי להגן על Highlight | שחור/לבן בהתאם לחוקים |
| ``--split-preview-*`` | מוגדר בערכי ברירת מחדל ב-`split-view.css` | ✔️ | ✔️ (rgba בגוון כחול) | ✔️ (rgba ירוק) | ✔️ (rgba סגלגל) | ✔️ (שחור/לבן/צהוב) |
| ``--search-*`` | משתמש בערכי ברירת מחדל כהים | צל ייחודי `rgba(7,7,31,0.35)` | צל כחול + הדגשת info | צל ירוק | מדגיש צבעי עץ | שחור/לבן עם צהוב (WCAG) |
| ``--lang-badge-*`` / ``--lang-hue-*`` | HSL עם Lightness נמוך (18%) | HSL עם Lightness גבוה (88%) | HSL עם Lightness נמוך (22%) | HSL עם Lightness נמוך (20%) | HSL עם Lightness גבוה (88%) | Saturation 100%, Lightness קיצוני |

## בדיקות רגרסיה

- **FOUC** – ודאו ש־`<html data-theme>` נקבע לפני טעינת CSS (ראו הסקריפט ב‑`base.html`).  
- **Live Preview** – טוען `--md-*` + `--split-*` גם כאשר Theme בהיר.  
- **High Contrast** – אסור להשתמש ב־`rgba` מלבד הערכים המוגדרים בקובץ הייעודי.  
- **Custom Theme** – ברגע שמזריקים ערכים ל‑``<style id="user-custom-theme">`` חובה לכסות את הטוקנים מהרשימה לעיל.

---

## שמירת משתנים בפרסום ערכה לציבורית

בעת פרסום ערכה אישית לציבורית, יש לוודא ששדות אלו נשמרים:

| שדה | תיאור | מקור |
|-----|-------|------|
| `colors` | משתני CSS | מיזוג: `originalVariables` + `formValues` |
| `syntax_css` | CSS להדגשת תחביר | `currentThemeSyntaxCss` |
| `syntax_colors` | מילון צבעים דינמי | `currentThemeSyntaxColors` |

### קוד המיזוג (theme_builder.html)

```javascript
// שמירת משתנים מקוריים בטעינת ערכה
currentThemeOriginalVariables = { ...theme.variables };
currentThemeSyntaxCss = theme.syntax_css || '';
currentThemeSyntaxColors = theme.syntax_colors || {};

// בפרסום - מיזוג
const colors = {
  ...currentThemeOriginalVariables,  // --link-color, --code-bg, etc.
  ...collectThemeValues(),           // ערכי הטופס
};
```

### Whitelist (משתנים מותרים)

רק משתנים אלו יישמרו (מוגדר ב-`theme_parser_service.py`):

```
# Level 1
--primary, --primary-hover, --primary-light, --secondary
--success, --warning, --error, --danger-bg, --danger-border
--glass, --glass-blur, --glass-border, --glass-hover

# Level 2 - רקע/טקסט
--bg-primary, --bg-secondary, --bg-tertiary
--text-primary, --text-secondary, --text-muted
--border-color, --shadow-color, --card-bg, --card-border
--navbar-bg, --input-bg, --input-border, --link-color
--code-bg, --code-text, --code-border

# Level 2 - כפתורים
--btn-primary-bg, --btn-primary-color, --btn-primary-border
--btn-primary-shadow, --btn-primary-hover-bg, --btn-primary-hover-color

# Level 2 - Markdown
--md-surface, --md-text
--md-inline-code-bg, --md-inline-code-border, --md-inline-code-color
--md-table-bg, --md-table-border, --md-table-header-bg
--md-mermaid-bg
--split-preview-bg, --split-preview-meta, --split-preview-placeholder

# Level 3 - Language Badges (ב-language-badges.css)
--lang-badge-saturation, --lang-badge-lightness-bg
--lang-badge-lightness-border, --lang-badge-lightness-text
--lang-hue-* (python, javascript, typescript, java, ועוד ~50 שפות)
```

> **הערה:** טוקני Language Badges משתמשים ב-HSL עם Hue קבוע לכל שפה. 
> ה-Saturation וה-Lightness משתנים לפי ערכת הנושא כדי לשמור על הבחנה ברורה בין שפות.

---

הטבלה תעודכן בכל פעם שטוקן חדש נכנס לאחת הערכות. לצרכי עריכה, פתחו Issue קצר עם הפער והפנו אליו מה‑PR.
