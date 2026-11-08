# מה VS Code עושה עם אותו קוד — הערכים הצפויים של צבעי התחביר

הטסטים של צבעי התחביר (`tests/test_vscode_token_theme.py`, `tests/test_syntax_colors_vscode_browser.py`) משווים את מה שהמחוללים שלנו כותבים למה ש-VS Code עצמו מציג. מה ש-VS Code מציג נמצא ב-`tests/fixtures/syntax_colors_vscode_reference.json`, והתיקייה הזו מייצרת אותו.

## מה יש בקובץ

לכל דוגמת קוד ב-`samples/` (פייתון ו-JavaScript), הקוד מחולק למקטעים. לכל מקטע:

- שרשרת ה-scopes ש-VS Code נותן לו — vscode-textmate, הספרייה ש-VS Code צובע בה, עם הדקדוקים של VS Code כפי ש-tm-grammars אורז אותם (MagicPython ו-JavaScript מריפו microsoft/vscode).
- המחלקות ש-highlight.js נותן לו — הגרסה שב-`node_modules` של הריפו, שהבאנדל של התצוגה נבנה ממנה.
- המחלקות וה-tags ש-CodeMirror נותן לו (`@lezer/highlight` ו-`@codemirror/lang-*` מאותו מקום).

ולכל ערכת ייצוא שנבנתה מערכת VS Code (`services/styled_export_service.py`): הצבע והגופן ש-VS Code נותן לכל שרשרת. `null` הוא צבע הטקסט של העורך.

## איך מריצים

משורש הריפו, עם Node:

```bash
npm ci --prefix scripts/syntax_colors
```

```bash
python scripts/syntax_colors/generate_reference.py
```

`generate_reference.py` שולח ל-`reference.mjs` את הדוגמאות ואת ה-`tokenColors` של הערכות, ושומר את התשובה יחד עם ה-hash של כל קלט. הטסט נכשל כשה-hash כבר לא תואם — כלומר כששינו ערכה או דוגמה ולא יצרו את הקובץ מחדש.

## למה יש לתיקייה תלויות משלה

vscode-textmate, vscode-oniguruma ו-tm-grammars משמשים רק את הסקריפט הזה, לא את האתר. ה-`node_modules` שבשורש הריפו נמצא בגיט, וה-CI לא מתקין חבילות Node, ולכן התלויות האלה מותקנות כאן, לפי ה-`package-lock.json` שלידן, וה-`node_modules` של התיקייה ב-`.gitignore`. הטסטים עצמם קוראים רק את הקובץ שנוצר, ולא צריכים Node.
