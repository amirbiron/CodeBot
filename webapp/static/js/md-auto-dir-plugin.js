/**
 * md-auto-dir-plugin.js — תוסף markdown-it: כל קוד בתוך שורה וכל תא בטבלה מקבלים ``dir="auto"``, כדי שהכיוון שלהם
 * ייקבע לפי התוכן שלהם ולא לפי העמוד.
 *
 * **מה היה שבור.** העמודים בוובאפ הם ``dir="rtl"`` (``base.html``), וכל אלמנט יורש את הכיוון הזה. קוד בתוך שורה עברית
 * ותא בטבלה הם קטעים שנכתבים לרוב משמאל לימין, ובלי הכרזה משלהם אלגוריתם הכיווניות של הדפדפן מסדר אותם לפי העברית
 * שמסביב: סימנים בקצה הקטע עוברים לצד הלא נכון. נמדד בכרומיום: ``--flag`` הוצג ``flag--``, ``foo()`` הוצג ``()foo``,
 * ``#md-content`` הוצג עם הסולמית בסוף, ובטבלה ``C++`` הוצג ``++C``. ``tests/test_md_auto_dir_browser.py`` מודד את זה
 * בכל המשטחים, בעמודים האמיתיים.
 *
 * **למה ``dir="auto"`` ולא ``direction: ltr``.** ``dir="auto"`` מחליט לכל קטע בנפרד לפי האות החזקה הראשונה שבו (תקן
 * HTML, "The dir attribute"): קוד שמתחיל באות לטינית מוצג משמאל לימין, וקוד שמתחיל באות עברית — מימין לשמאל. החלופה
 * שממומשת בפתקים הדביקים (``.sticky-md-code``: ``direction: ltr`` עם ``unicode-bidi: embed``) נמדדה מול שלושה מצבים,
 * על 11 משפטים: היא תיקנה את אותם מקרים בדיוק, אבל הפכה כל קוד בשורה לקטע משמאל לימין — ובשם קובץ בעברית,
 * ``הפניות-שלא-חלו.md``, הסיומת עברה לצד ימין, לפני השם. ``dir="auto"`` השאיר אותו כמו בלי שום כלל. בתא בטבלה זו אותה
 * החלטה שכבר ממומשת בפתקים (``cell.setAttribute('dir', 'auto')`` ב-``sticky-notes.js``).
 *
 * **בלי CSS.** לאלמנט שיש עליו ``dir`` גיליון הסגנון של הדפדפן נותן ``unicode-bidi: isolate`` (תקן HTML, "Bidirectional
 * text" בפרק ה-Rendering; נמדד בכל המשטחים: ``isolate`` על קוד בשורה ועל תא), ולכן הקטע מבודד מהשורה שסביבו בלי שורת CSS. אותו
 * מנגנון כמו העטיפות של ``utils/rtl-code.js``. **ומאותה סיבה, כלל CSS של האתר שמצהיר ``direction`` על אותו אלמנט גובר
 * על התכונה בשקט** (נמדד על תא בטבלה) — ולכן אין לכתוב ``direction`` על קוד בשורה או על תאים במשטחים שמציגים Markdown.
 * היישור של תא לפי הכיוון שנקבע לו הוא ``text-align: start``, בכלל הטבלה של כל משטח.
 *
 * **איך.** כלל ליבה (``md.core.ruler.push``) שרץ אחרי כל כללי הליבה של markdown-it, ולכן אחרי ``inline``, שבו נוצרים
 * הטוקנים של קוד בשורה (``code_inline``, ``rules_inline/backticks.mjs``). התאים (``th_open`` / ``td_open``,
 * ``rules_block/table.mjs``) נוצרים כבר בשלב ``block``. המאפיין נכתב על הטוקן, והכלל של markdown-it מרנדר את מאפייני
 * הטוקן: ``code_inline`` ב-``renderer.mjs`` (``slf.renderAttrs(token)``), והתאים ב-``renderToken``. כך זה עובד גם יחד
 * עם ``md-source-lines-plugin.js``, שעוטף את כללי הרינדור של התאים, מוסיף ``data-row-line`` ו-``data-col``, ומעביר הלאה
 * ל-``renderToken``. **רנדרר שמחליף את כלל ``code_inline`` בכלל שאינו קורא ל-``renderAttrs`` מוחק את ``dir`` בשקט** — כך
 * היה ב-``live-preview.js`` עד שהכלל שם הוסר (נובמבר 2026); ``tests/md-auto-dir-plugin.test.js`` בודק שאין עוד כזה.
 *
 * **למה קובץ משותף.** כל מקום שיוצר את markdown-it בוובאפ מתקין אותו — ``md_preview.html``, ``live-preview.js``
 * (``ensureRenderer``, שמשמש את התצוגה החיה, את הייצוא המעוצב, את דפדפן הריפו ואת כרטיסי החיפוש בתיעוד) ומסלול הגיבוי
 * ב-``repo-browser.js`` (``renderMarkdownFallback``) — ולכן ההחלטה וההסבר כתובים פעם אחת. ``tests/md-auto-dir-plugin.test.js``
 * בודק שכל מקום שיוצר את markdown-it מתקין אותו, ושכל תבנית שמארחת רנדרר טוענת אותו.
 *
 * שימוש:
 *     md.use(window.MdAutoDirPlugin);
 * הבדיקות טוענות את הקובץ כמו הדפדפן, כ-script קלאסי בתוך ``vm``: ``package.json`` מוגדר ``"type": "module"``, ולכן
 * ``require`` לא היה עובד עליו.
 *
 * מקור לכל מה שכתוב כאן: markdown-it@14.1.0 (``package-lock.json``) — ``lib/parser_core.mjs`` (סדר כללי הליבה),
 * ``lib/renderer.mjs``, ``lib/token.mjs`` (``attrSet``) והקבצים שצוינו למעלה.
 */
(function (root) {
  'use strict';

  var CELL_OPEN_TYPES = ['th_open', 'td_open'];

  function autoDir(state) {
    var tokens = state.tokens;
    for (var i = 0; i < tokens.length; i += 1) {
      var token = tokens[i];
      if (CELL_OPEN_TYPES.indexOf(token.type) >= 0) {
        token.attrSet('dir', 'auto');
      } else if (token.type === 'inline' && token.children) {
        for (var j = 0; j < token.children.length; j += 1) {
          if (token.children[j].type === 'code_inline') token.children[j].attrSet('dir', 'auto');
        }
      }
    }
  }

  function autoDirPlugin(md) {
    md.core.ruler.push('md_auto_dir', autoDir);
  }

  if (root) {
    root.MdAutoDirPlugin = autoDirPlugin;
  }
})(typeof window !== 'undefined' ? window : null);
