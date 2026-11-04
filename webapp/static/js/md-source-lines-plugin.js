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
 *
 * **קונטיינרים ואלרטים — רק כשמבקשים (``extraBlockTypes``).** ``::: note`` / ``::: details`` (markdown-it-container)
 * ו-``!!! note`` (markdown-it-admonition) הם בלוק עם כותרת שתופסת גובה, ובלי סימון הגלילה המסונכרנת לא ידעה איפה
 * הם מתחילים: כשהעורך עמד על שורת הפתיחה, הכותרת בתצוגה הייתה 14 עד 33px מהמקום (נמדד ב-4.11.2026 על טקסט
 * ההדגמה, ``test_scrolling_the_editor_brings_the_preview_to_each_container``). התצוגה החיה מעבירה את סוגי הטוקנים
 * שלהם (``container_<סוג>_open``, ``admonition_open``) ב-``extraBlockTypes``, והכותרת שהיא מרנדרת לקונטיינר כותבת את
 * המאפיינים (``renderAttrs``). ``md_preview.html`` לא מעביר אותם: "העתק כמארקדאון" והעיגון של הפתקים שם נבנו על
 * הסימונים הקיימים, וסימון חדש היה משנה את מה שהם נצמדים אליו. ב-markdown-it-admonition ‏(1.0.4) הכלל של
 * ``admonition_open`` מרנדר את מאפייני הטוקן בעצמו (``renderToken``), ולכן שם אין צורך בשינוי.
 *
 * **טבלאות.** ב-markdown-it ‏(14.x) ל-``th_open`` / ``td_open`` אין ``map`` (``null``). לכן תא יורש את השורה של
 * ה-``tr_open`` שלפניו, ומקבל את מספר העמודה, כדי ש"העתק כמארקדאון" יוכל לחלץ תא בודד מהמקור. השורה והעמודה של
 * כל התאים מחושבות במעבר אחד על הטוקנים, בפעם הראשונה שתא מרונדר (``cellPositions``). עד נובמבר 2026 כל תא סרק
 * לאחור את התאים שלפניו בשורה שלו, ולכן העבודה על שורה גדלה בריבוע של מספר העמודות — ואחרי שהתוסף נכנס לתצוגה
 * החיה, זה רץ בכל רינדור.
 *
 * שימוש:
 *     md.use(window.MdSourceLines.plugin);                                          // דפדפן
 *     md.use(window.MdSourceLines.plugin, { extraBlockTypes: ['admonition_open'] }); // עם סוגים נוספים
 *     md.use(require('.../md-source-lines-plugin').plugin);                         // Node
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

  /**
   * השורה בטבלה והעמודה של כל תא, לפי האינדקס של ה-``th_open`` / ``td_open`` שלו — במעבר אחד על הטוקנים.
   *
   * השורה היא של ה-``tr_open`` האחרון שלפני התא (``null`` כשאין לו ``map``, או כשאין ``tr_open`` לפניו), והעמודה
   * היא כמה תאים מאותו סוג היו מאז ה-``tr_open`` הזה — או מתחילת הטוקנים, כשאין כזה.
   */
  function cellPositions(tokens, lineMap) {
    var positions = {};
    var rowLine = null;
    var thCount = 0;
    var tdCount = 0;
    for (var i = 0; i < tokens.length; i += 1) {
      var type = tokens[i].type;
      if (type === 'tr_open') {
        var map = tokens[i].map;
        rowLine = map && map.length >= 2 ? sourceLine(map[0], lineMap) : null;
        thCount = 0;
        tdCount = 0;
      } else if (type === 'th_open') {
        positions[i] = { rowLine: rowLine, col: thCount };
        thCount += 1;
      } else if (type === 'td_open') {
        positions[i] = { rowLine: rowLine, col: tdCount };
        tdCount += 1;
      }
    }
    return positions;
  }

  /**
   * ``options.extraBlockTypes`` — סוגי טוקנים נוספים שמקבלים ``data-source-line`` / ``data-source-line-end``, מעבר
   * ל-``BLOCK_OPEN_TYPES`` (ההסבר בראש הקובץ, בפסקה על קונטיינרים ואלרטים).
   */
  function sourceLinesPlugin(md, options) {
    var extra = options && Array.isArray(options.extraBlockTypes) ? options.extraBlockTypes : [];
    var blockTypes = BLOCK_OPEN_TYPES.concat(extra.filter(function (type, i) {
      return BLOCK_OPEN_TYPES.indexOf(type) === -1 && extra.indexOf(type) === i;
    }));
    blockTypes.forEach(function (type) {
      wrapRule(md, type, function (tokens, idx, lineMap) {
        var token = tokens[idx];
        if (!token.map || token.map.length < 2) return;
        var start = sourceLine(token.map[0], lineMap);
        var end = sourceLineEnd(token.map[1], lineMap);
        if (Number.isInteger(start)) token.attrSet('data-source-line', String(start));
        if (Number.isInteger(end)) token.attrSet('data-source-line-end', String(end));
      });
    });

    // המיקומים של התאים נשמרים לכל מערך טוקנים — כל רינדור מפענח מערך חדש — ולמפת השורות שאיתה חושבו.
    var cellCache = new WeakMap();
    CELL_OPEN_TYPES.forEach(function (type) {
      wrapRule(md, type, function (tokens, idx, lineMap) {
        var cached = cellCache.get(tokens);
        if (!cached || cached.lineMap !== lineMap) {
          cached = { lineMap: lineMap, positions: cellPositions(tokens, lineMap) };
          cellCache.set(tokens, cached);
        }
        var position = cached.positions[idx];
        if (!position) return;
        if (Number.isInteger(position.rowLine)) tokens[idx].attrSet('data-row-line', String(position.rowLine));
        tokens[idx].attrSet('data-col', String(position.col));
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
