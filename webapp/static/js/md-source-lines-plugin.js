/**
 * md-source-lines-plugin.js — תוסף markdown-it שמסמן כל בלוק מרונדר בשורות המקור שלו: ``data-source-line`` (השורה
 * הראשונה, 0-based) ו-``data-source-line-end`` (השורה שאחרי האחרונה). תא בטבלה מקבל במקום זה ``data-row-line``
 * (השורה של השורה שלו בטבלה) ו-``data-col`` (מספר העמודה, 0-based).
 *
 * **מי משתמש בזה.**
 *
 * - **תצוגת המסמך** (``md_preview.html``): "העתק כמארקדאון" מתרגם בחירה בתצוגה לשורות במקור, והפתקים הדביקים
 *   מעוגנים לשורת מקור.
 * - **התצוגה החיה בעמודי העורך** (הווריאנט ``livePreview`` ב-``live-preview.js``): לחיצה על צ'קבוקס של משימה
 *   משנה את השורה שלו בעורך, והגלילה המסונכרנת בין העורך לתצוגה (``live-preview-scroll-sync.js``) מתאימה כל
 *   מקום בעורך למקום בתצוגה.
 *
 * דפדפן הריפו וכרטיסי החיפוש בתיעוד (הווריאנט ``default``) לא מתקינים אותו.
 *
 * **למה קובץ משותף.** התוסף היה כתוב בתוך ``md_preview.html``, והתצוגה החיה החזיקה כלל משלה שסימן רק פריטי
 * משימה (``task-source-lines``). הגלילה המסונכרנת צריכה את הסימון על כל בלוק, ולכן שני הרנדררים טוענים את
 * הקובץ הזה, והכלל של התצוגה החיה הוסר. ``md_preview.html`` מקבל ממנו בדיוק את אותו HTML כמו קודם.
 *
 * **מפת השורות (``env.sourceLineMap``).** התצוגה החיה מסירה לפני הפענוח שורות שכל מה שיש בהן הוא עוגן
 * (``MdAnchors.extractExplicitAnchors`` ב-``md-anchors.js``), ולכן מספרי השורות ש-markdown-it רואה זזים ממספרי
 * השורות בעורך. ``renderMarkdownSource`` ב-``live-preview.js`` מעביר את המפה ב-``env``, והתוסף מתרגם דרכה כל
 * מספר לשורה בעורך. בלי מפה (``md_preview.html`` לא מעביר אותה) המספרים הם של הטקסט שפוענח.
 *
 * **איך.** התוסף עוטף את כללי הרינדור של סוגי הבלוקים שב-``BLOCK_OPEN_TYPES`` ומציב את המאפיינים על הטוקן לפני
 * שהכלל המקורי מרנדר אותו. לכן הוא חייב להיות **מותקן אחרי** כל תוסף שמחליף כלל רינדור של אחד הסוגים האלה
 * (למשל ``math_block`` של ``md-math-plugin.js``): תוסף שיותקן אחריו ויחליף כלל, ידרוס את העטיפה. ומאפיין מגיע
 * ל-HTML רק כשהכלל המקורי מרנדר את מאפייני הטוקן (``renderAttrs``) — הכללים של markdown-it עצמו עושים זאת, וגם
 * ``math_block``. ב-``fence`` של markdown-it (נבדק בגרסה 14.1.0) הם נכתבים על ה-``<code>`` שבתוך ה-``<pre>``.
 * הקונטיינרים (``::: note``, ``::: details``) מרונדרים בפונקציות משלהם ולא מקבלים סימון; הבלוקים שבתוכם כן.
 *
 * **טבלאות.** ב-markdown-it ‏(14.x) ל-``th_open`` / ``td_open`` אין ``map`` (``null``). לכן תא יורש את השורה של
 * ה-``tr_open`` שלפניו, ומקבל את מספר העמודה, כדי ש"העתק כמארקדאון" יוכל לחלץ תא בודד מהמקור.
 *
 * שימוש:
 *     md.use(window.MdSourceLines.plugin);                        // דפדפן
 *     md.use(require('.../md-source-lines-plugin').plugin);       // Node
 */
(function (root) {
  'use strict';

  /** סוגי הטוקנים שמקבלים ``data-source-line`` ו-``data-source-line-end``. לכולם יש ``map`` ב-markdown-it. */
  var BLOCK_OPEN_TYPES = [
    'paragraph_open',
    'heading_open',
    'blockquote_open',
    'bullet_list_open',
    'ordered_list_open',
    'list_item_open',
    'table_open',
    'thead_open',
    'tbody_open',
    'tr_open',
    'fence',
    'code_block',
    'hr',
    'math_block',
  ];

  /** תאי טבלה: בלי ``map`` משלהם, ולכן ``data-row-line`` ו-``data-col``. */
  var CELL_OPEN_TYPES = ['th_open', 'td_open'];

  function lineMapOf(env) {
    return env && Array.isArray(env.sourceLineMap) ? env.sourceLineMap : null;
  }

  /** השורה במקור של שורה בטקסט שפוענח (0-based), או ``undefined`` כשהמפה לא מכירה אותה. */
  function sourceLine(parsedLine, lineMap) {
    return lineMap ? lineMap[parsedLine] : parsedLine;
  }

  /** הקצה הבלעדי במקור של טווח שנגמר לפני ``parsedEnd``: השורה שאחרי השורה האחרונה של הטווח. */
  function sourceLineEnd(parsedEnd, lineMap) {
    return lineMap ? lineMap[parsedEnd - 1] + 1 : parsedEnd;
  }

  function wrapRule(md, type, decorate) {
    var originalRule = md.renderer.rules[type];
    md.renderer.rules[type] = function (tokens, idx, options, env, self) {
      decorate(tokens, idx, lineMapOf(env));
      if (originalRule) {
        return originalRule(tokens, idx, options, env, self);
      }
      return self.renderToken(tokens, idx, options);
    };
  }

  function sourceLinesPlugin(md) {
    BLOCK_OPEN_TYPES.forEach(function (type) {
      wrapRule(md, type, function (tokens, idx, lineMap) {
        var token = tokens[idx];
        if (!token.map || token.map.length < 2) return;
        var start = sourceLine(token.map[0], lineMap);
        var end = sourceLineEnd(token.map[1], lineMap);
        if (Number.isInteger(start)) token.attrSet('data-source-line', String(start));
        if (Number.isInteger(end)) token.attrSet('data-source-line-end', String(end));
      });
    });

    CELL_OPEN_TYPES.forEach(function (type) {
      wrapRule(md, type, function (tokens, idx, lineMap) {
        var token = tokens[idx];
        // השורה בטבלה: מה-``tr_open`` הקרוב שלפני התא.
        var rowLine = null;
        for (var i = idx - 1; i >= 0; i -= 1) {
          if (tokens[i].type === 'tr_open') {
            if (tokens[i].map && tokens[i].map.length >= 2) {
              rowLine = sourceLine(tokens[i].map[0], lineMap);
            }
            break;
          }
        }
        // העמודה: כמה תאים מאותו סוג יש מאז ה-``tr_open``.
        var colIndex = 0;
        for (var j = idx - 1; j >= 0; j -= 1) {
          if (tokens[j].type === 'tr_open') break;
          if (tokens[j].type === type) colIndex += 1;
        }
        if (Number.isInteger(rowLine)) token.attrSet('data-row-line', String(rowLine));
        token.attrSet('data-col', String(colIndex));
      });
    });
  }

  var api = { plugin: sourceLinesPlugin, BLOCK_OPEN_TYPES: BLOCK_OPEN_TYPES };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;   // לבדיקות מ-Node
  }
  if (root) {
    root.MdSourceLines = api; // שימוש בדפדפן
  }
})(typeof window !== 'undefined' ? window : null);
