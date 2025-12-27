# Theme Matrix (תצוגה מקוצרת)

הטבלה הזו מהווה חיבור מהיר בין פלטות הצבעים לבין מדריך היישום. היא לא מחליפה את המסמכים המלאים אלא עוזרת לסמן במהירות אילו טוקנים קריטיים לכל ערכת נושא.

> **מקורות:**  
> - מדריך ארכיטקטורה: [`docs/webapp/theming_and_css.rst`](../docs/webapp/theming_and_css.rst)  
> - פירוט פלטות: [`webapp/FEATURE_SUGGESTIONS/webapp_theme_palettes.md`](../webapp/FEATURE_SUGGESTIONS/webapp_theme_palettes.md)

## כיסוי טוקנים חובה

| קבוצה | Dark / Dim / Nebula | Classic | Ocean | Forest | Rose Pine Dawn | High Contrast | **Custom** |
| --- | --- | --- | --- | --- | --- | --- | --- |
| ``--bg-*`` + ``--text-*`` | מוגדרים מלא ב-`:root[data-theme]` | ✔️ | ✔️ (חובה בגרסאות כחול) | ✔️ (ירוק מלא) | ✔️ (ערכי ורוד/קרם) | נתון ב-`high-contrast.css` בלבד | ✔️ (נקבע ע"י Theme Builder) |
| ``--card-*`` | ✔️ | ✔️ | ✔️ | ✔️ | ✔️ | ✔️ (שחור/לבן) | ✔️ + ``--card-border`` אוטומטי |
| ``--glass*`` | ✔️ (הלוגיקה ב-`dark-mode.css`) | משתמש בברירת המחדל השקופה | Override חצי שקוף כחול | Override חצי שקוף ירוק | Override ורוד שקוף | לבן שקוף + גבול לבן | ✔️ **מבוסס על ``--card-bg`` (תמיכה ב-HEX/HEXA/RGBA)** |
| ``--btn-primary-*`` | `color-mix` על סמך ``--bg-tertiary`` | טקסט כהה על לבן | טקסט כחול כהה על לבן | טקסט ירוק כהה על לבן | `color-mix` עם ורוד | שחור/לבן/צהוב בלבד | ✔️ (נקבע ע"י Theme Builder) |
| ``--md-surface`` / ``--md-text`` | כהה אחיד | כהה מותאם (`#15141f`) | כהה כחול (`#1a365d`) | כהה ירוק (`#1a4731`) | נשאר כהה כדי להגן על Highlight | שחור/לבן בהתאם לחוקים | ✔️ (נקבע ע"י Theme Builder) |
| ``--split-preview-*`` | מוגדר בערכי ברירת מחדל ב-`split-view.css` | ✔️ | ✔️ (rgba בגוון כחול) | ✔️ (rgba ירוק) | ✔️ (rgba סגלגל) | ✔️ (שחור/לבן/צהוב) | משתמש בברירת מחדל |
| ``--search-*`` | משתמש בערכי ברירת מחדל כהים | צל ייחודי `rgba(7,7,31,0.35)` | צל כחול + הדגשת info | צל ירוק | מדגיש צבעי עץ | שחור/לבן עם צהוב (WCAG) | משתמש בברירת מחדל |

## בדיקות רגרסיה

- **FOUC** – ודאו ש־`<html data-theme>` נקבע לפני טעינת CSS (ראו הסקריפט ב‑`base.html`).  
- **Live Preview** – טוען `--md-*` + `--split-*` גם כאשר Theme בהיר.  
- **High Contrast** – אסור להשתמש ב־`rgba` מלבד הערכים המוגדרים בקובץ הייעודי.  
- **Custom Theme** – ברגע שמזריקים ערכים ל‑``<style id="user-custom-theme">`` חובה לכסות את הטוקנים מהרשימה לעיל.
- **Color Selection (8-char HEX)** – ודאו שבחירת צבע עם שקיפות ב‑Pickr (פורמט HEXA) לא גורמת ל‑Glass לחזור ללבן ברירת מחדל.

## עדכון דצמבר 2025: תיקון בעיית "רכיבים לבנים" בערכות מותאמות

### הבעיה שתוקנה
ערכות מותאמות אישית (Custom Themes) הציגו כרטיסים, navbar וכפתורים משניים בצבע לבן במקום הצבעים שהוגדרו, במיוחד בערכות בהירות כמו Rose Pine Dawn.

### הסיבה
1. **חסרו CSS rules עבור `[data-theme="custom"]`** - בקובץ `dark-mode.css` היו עיצובים עבור `dark`, `dim`, ו-`nebula` אבל לא עבור ערכות מותאמות
2. **Theme Builder ייצר `--glass` עם בסיס לבן קבוע** - `rgba(255, 255, 255, opacity)` במקום להשתמש בצבע הרקע שהמשתמש הגדיר

### התיקון
1. **`dark-mode.css`** - נוספו selectors של `[data-theme="custom"]` לכל הרכיבים הרלוונטיים:
   - `.glass-card` - משתמש ב-`--card-bg` במקום `--glass`
   - `.btn-secondary` - תואם לערכת הנושא
   - `.navbar`, `.file-card`, inputs, typography ועוד

2. **Theme Builder (`theme_builder.html`)** - שינויים ב-JavaScript:
   - פונקציה חדשה `parseColorToRgb()` שמפרסרת צבעים בפורמט HEX או RGBA
   - `collectThemeValues()` מייצר כעת `--glass*` בהתאם לצבע `--card-bg` (לא לבן קבוע)
   - `--card-border` נוצר אוטומטית לעקביות
   - **איחוד לוגיקת צבעים:** יש להשתמש ב‑`parseColorToRgb` כפונקציה יחידה (במקום כפילויות כמו `_hexToRgb`). על קלט לא תקין הפונקציה מחזירה `null` כדי למנוע ערכי NaN שנכנסים ל‑CSS.

### טוקנים שנוספו/שונו
| טוקן | שינוי |
| --- | --- |
| `--glass` | נוצר על בסיס צבע `--card-bg` במקום לבן קבוע (תמיכה ב-HEX/HEXA/RGBA) |
| `--glass-border` | נוצר על בסיס צבע `--card-bg` במקום לבן קבוע (תמיכה ב-HEX/HEXA/RGBA) |
| `--glass-hover` | נוצר על בסיס צבע `--card-bg` במקום לבן קבוע (תמיכה ב-HEX/HEXA/RGBA) |
| `--card-border` | נוצר אוטומטית מ-`--glass-border` |

הטבלה תעודכן בכל פעם שטוקן חדש נכנס לאחת הערכות. לצרכי עריכה, פתחו Issue קצר עם הפער והפנו אליו מה‑PR.
