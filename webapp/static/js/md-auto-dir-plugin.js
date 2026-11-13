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
 * שהייתה ממומשת בפתקים הדביקים עד נובמבר 2026 (``direction: ltr`` עם ``unicode-bidi: embed`` על ``.sticky-md-code``)
 * נמדדה מול שלושה מצבים, על 11 משפטים: היא תיקנה את אותם מקרים בדיוק, אבל הפכה כל קוד בשורה לקטע משמאל לימין — ובשם
 * קובץ בעברית, ``הפניות-שלא-חלו.md``, הסיומת עברה לצד ימין, לפני השם. ``dir="auto"`` השאיר אותו כמו בלי שום כלל. מאז
 * גם הפתקים כותבים ``dir="auto"`` על קוד בשורה (``_appendInlineSegments`` ב-``sticky-notes.js``), ועל תא בטבלה הם כתבו
 * אותו עוד קודם (``cell.setAttribute('dir', 'auto')`` שם).
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
 * **שם קובץ עברי: ``dir="rtl"`` והסיומת ב-``<bdi>``.** ב-``מדריך-תצוגת-Markdown-RTL.md`` הנקודה יושבת בין שתי אותיות
 * לטיניות ונדבקת אליהן, ולכן גם עם ``dir="auto"`` הסיומת מוצגת באמצע השם, צמודה לעברית. קוד בשורה ש-
 * ``RtlCode.fileNameParts`` (``utils/rtl-code.js``) מפרק מקבל ``dir="rtl"``, והכלל של ``code_inline`` שהתוסף מתקין כותב
 * את הסיומת ב-``<bdi>`` — והיא עוברת לקצה השמאלי. ההחלטה מתי מפרקים, והמדידה, כתובות שם פעם אחת: הפתקים והכרטיסים של
 * פתקים בונים את אותו מבנה כצמתים (``RtlCode.fillInlineCode``), ו-``tests/sticky-notes-target.test.js`` משווה ביניהם.
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
  var warnedNoRtlCode = false;

  /**
   * הפירוק של שם קובץ עברי שהדפדפן היה מציג עם הסיומת באמצע — ``RtlCode.fileNameParts`` ב-``utils/rtl-code.js``
   * (ההחלטה וההסבר שם, משותפים לפתקים ולכרטיסי הפתקים), או ``null``. **היעדר ``window.RtlCode`` הוא היעדר יכולת
   * סטטי** — כל תבנית שטוענת את התוסף טוענת גם אותו, ו-``tests/md-auto-dir-plugin.test.js`` בודק את זה — ולכן הקוד
   * מוצג אז כמו לפני הפירוק, עם ``dir="auto"``, ואזהרה אחת בקונסול אומרת למה.
   */
  function fileNameParts(text) {
    var rtl = root && root.RtlCode;
    if (rtl && typeof rtl.fileNameParts === 'function') return rtl.fileNameParts(text);
    if (!warnedNoRtlCode && typeof console !== 'undefined') {
      warnedNoRtlCode = true;
      console.warn('md-auto-dir-plugin: utils/rtl-code.js לא נטען — שם קובץ עברי בקוד בשורה יוצג עם הסיומת באמצע');
    }
    return null;
  }

  function autoDir(state) {
    var tokens = state.tokens;
    for (var i = 0; i < tokens.length; i += 1) {
      var token = tokens[i];
      if (CELL_OPEN_TYPES.indexOf(token.type) >= 0) {
        token.attrSet('dir', 'auto');
      } else if (token.type === 'inline' && token.children) {
        for (var j = 0; j < token.children.length; j += 1) {
          var child = token.children[j];
          if (child.type !== 'code_inline') continue;
          var parts = fileNameParts(child.content);
          child.attrSet('dir', parts ? 'rtl' : 'auto');
          if (parts) {
            child.meta = child.meta || {};
            child.meta.fileName = parts;
          }
        }
      }
    }
  }

  /**
   * קוד בשורה שהוא שם קובץ עברי: ``stem + '.'`` כטקסט, והסיומת ב-``<bdi>`` — בדיוק מה ש-``RtlCode.fillInlineCode`` בונה
   * כצמתים בפתק. כל קוד אחר עובר לכלל שהיה מותקן לפני התוסף (ב-markdown-it, ``default_rules.code_inline`` ב-
   * ``lib/renderer.mjs``). **``slf.renderAttrs``, ולא תגית שנכתבת ביד** — אחרת ``dir`` שנכתב על הטוקן נמחק בשקט, כמו
   * בכלל שישב ב-``live-preview.js`` עד נובמבר 2026; הסורק ב-``tests/md-auto-dir-plugin.test.js`` בודק את זה.
   */
  function autoDirPlugin(md) {
    md.core.ruler.push('md_auto_dir', autoDir);
    var renderCode = md.renderer.rules.code_inline;
    md.renderer.rules.code_inline = function (tokens, idx, options, env, slf) {
      var token = tokens[idx];
      var parts = token.meta && token.meta.fileName;
      if (!parts) return renderCode(tokens, idx, options, env, slf);
      return '<code' + slf.renderAttrs(token) + '>' + md.utils.escapeHtml(parts.stem) + '.<bdi>' +
        md.utils.escapeHtml(parts.extension) + '</bdi></code>';
    };
  }

  if (root) {
    root.MdAutoDirPlugin = autoDirPlugin;
  }
})(typeof window !== 'undefined' ? window : null);
