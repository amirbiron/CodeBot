/**
 * md-mark-plugin.js — תוסף markdown-it להדגשת "מארקר": ``==טקסט==`` ← ``<mark>טקסט</mark>``
 *
 * **למה הקובץ הזה קיים.** התוסף הזה היה כתוב ביד, פעמיים, זהה תו-בתו: פעם אחת מוטמע
 * בתוך ``webapp/templates/md_preview.html`` ופעם שנייה בתוך ``webapp/static/js/live-preview.js``.
 * הוא הפיל את כל תצוגת המארקדאון על כל מסמך שהכיל ``**מודגש**`` ואחריו ``==מארקר==``
 * באותה פסקה — למשל ``**Let's** give it a==shot==`` — והמשתמש ראה רק
 * "שגיאה ברינדור Markdown" בלי סיבה.
 *
 * **מה היה שבור, ולמה זה לא היה טעות קטנה.** הגרסה הישנה קראה, מתוך כלל inline:
 *
 *     state.md.inline.parse(inner, state.md, state.env, state.tokens);
 *
 * ``inline.parse`` היא נקודת כניסה עליונה, לא פונקציית עזר. היא מריצה את כל שלבי הסיום
 * (``ruler2``) על מערך הטוקנים **המשותף**, והאחרון שבהם — ``fragments_join`` — מסיים ב:
 *
 *     if (curr !== last) { tokens.length = last }
 *     // node_modules/markdown-it/lib/rules_inline/fragments_join.mjs
 *
 * כלומר הקריאה המקוננת **מקצרת את המערך**. הדלימיטרים של ה-``**`` החיצוני כבר רשמו
 * אינדקס טוקן, והאינדקסים האלה מצביעים עכשיו מעבר לסוף. ואז ``emphasis.postProcess``
 * עושה ``state.tokens[startDelim.token].type = ...`` על ``undefined`` וזורק.
 * (גם ``tokens_meta`` יוצא מסנכרון: ``StateInline`` מאתחל אותו ל-``outTokens.length``.)
 *
 * **המנגנון התקני.** הקובץ הזה בנוי במבנה של
 * ``node_modules/markdown-it/lib/rules_inline/strikethrough.mjs`` — ``~~קו חוצה~~`` הוא
 * אותו סוג דלימיטר בדיוק: כפול וסימטרי. כל ``==`` נדחף כטוקן ``text`` ונרשם ב-
 * ``state.delimiters``; ההתאמה בין פותח לסוגר נעשית ב-``balance_pairs`` של הספרייה;
 * וההפיכה ל-``mark_open``/``mark_close`` קורית ב-``postProcess`` שרשום על ``ruler2``.
 * **אין פרסור מקונן**, ולכן אין מה לשבור: התוכן הפנימי נפרס ממילא כי הטוקנים נשארים
 * באותו זרם.
 *
 * ``length: 0`` אינו קסם — הוא מנטרל את "כלל השלוש" שנועד להדגשות בלבד, וזה מתועד
 * בספרייה עצמה: "Length is only used for emphasis-specific rule of 3, if it's not
 * defined (in strikethrough or 3rd party plugins), we can default it to 0"
 * (``lib/rules_inline/balance_pairs.mjs``, שורות 30-34).
 *
 * שימוש:
 *     md.use(window.MdMarkPlugin);           // דפדפן
 *     md.use(require('.../md-mark-plugin')); // Node, לבדיקות
 *
 * מקור לכל מה שכתוב כאן: markdown-it@14.1.0 (``package.json``), הקבצים
 * ``lib/rules_inline/strikethrough.mjs``, ``balance_pairs.mjs``, ``fragments_join.mjs``.
 */
(function (root) {
  'use strict';

  var MARKER = 0x3D; /* '=' */
  var MARKUP = '==';

  /**
   * שלב א — זיהוי. רץ כ-inline rule, לפני ``emphasis``.
   *
   * מבנה זהה ל-``strikethrough_tokenize``: לא מחליטים כאן על פתיחה/סגירה ולא מחפשים
   * את הסוגר. רק דוחפים טוקן ``text`` לכל זוג ``==`` ורושמים אותו ברשימת הדלימיטרים.
   * ``scanDelims(pos, true)`` הוא זה שקובע אם הרצף יכול לפתוח או לסגור, לפי כללי
   * ה-flanking של CommonMark; ה-``true`` הוא ``canSplitWord``, ובזכותו ``a==shot==``
   * עובד כמו ``a~~shot~~``.
   */
  function tokenize(state, silent) {
    var start = state.pos;
    var marker = state.src.charCodeAt(start);

    if (silent) { return false; }
    if (marker !== MARKER) { return false; }

    var scanned = state.scanDelims(state.pos, true);
    var len = scanned.length;
    var ch = String.fromCharCode(marker);

    if (len < 2) { return false; }

    var token;

    // רצף באורך אי-זוגי (``===``) משאיר ``=`` בודד בהתחלה, בדיוק כמו ב-strikethrough.
    if (len % 2) {
      token = state.push('text', '', 0);
      token.content = ch;
      len--;
    }

    for (var i = 0; i < len; i += 2) {
      token = state.push('text', '', 0);
      token.content = ch + ch;

      state.delimiters.push({
        marker: marker,
        length: 0, // מנטרל את "כלל השלוש" שנועד להדגשות בלבד
        token: state.tokens.length - 1,
        end: -1,
        open: scanned.can_open,
        close: scanned.can_close
      });
    }

    state.pos += scanned.length;

    return true;
  }

  /**
   * שלב ב — המרה. רץ כ-``ruler2``, אחרי ש-``balance_pairs`` כבר זיווג פותח לסוגר
   * (הוא גנרי לחלוטין לפי ``marker``, ולכן אינו צריך לדעת עלינו).
   *
   * כאן רק הופכים את טוקני ה-``text`` שכבר קיימים לתגיות. שום טוקן לא נוסף ולא נמחק,
   * ולכן שום אינדקס של דלימיטר אחר לא זז — זה בדיוק ההבדל מהגרסה השבורה.
   */
  function convertDelimiters(state, delimiters) {
    var token;
    var loneMarkers = [];
    var max = delimiters.length;
    var i;

    for (i = 0; i < max; i++) {
      var startDelim = delimiters[i];

      if (startDelim.marker !== MARKER) { continue; }
      if (startDelim.end === -1) { continue; }

      var endDelim = delimiters[startDelim.end];

      token = state.tokens[startDelim.token];
      token.type = 'mark_open';
      token.tag = 'mark';
      token.nesting = 1;
      token.markup = MARKUP;
      token.content = '';

      token = state.tokens[endDelim.token];
      token.type = 'mark_close';
      token.tag = 'mark';
      token.nesting = -1;
      token.markup = MARKUP;
      token.content = '';

      if (state.tokens[endDelim.token - 1].type === 'text' &&
          state.tokens[endDelim.token - 1].content === '=') {
        loneMarkers.push(endDelim.token - 1);
      }
    }

    // ה-``=`` הבודד שנשאר מרצף אי-זוגי צריך לעבור אל מעבר לתגיות הסגירה, אחרת
    // הוא היה מודפס בתוך ה-``<mark>`` במקום אחריו. אותו טיפול בדיוק כמו ב-strikethrough.
    while (loneMarkers.length) {
      var idx = loneMarkers.pop();
      var j = idx + 1;

      while (j < state.tokens.length && state.tokens[j].type === 'mark_close') { j++; }

      j--;

      if (idx !== j) {
        token = state.tokens[j];
        state.tokens[j] = state.tokens[idx];
        state.tokens[idx] = token;
      }
    }
  }

  function postProcess(state) {
    var tokensMeta = state.tokens_meta;
    var max = state.tokens_meta.length;

    convertDelimiters(state, state.delimiters);

    for (var curr = 0; curr < max; curr++) {
      if (tokensMeta[curr] && tokensMeta[curr].delimiters) {
        convertDelimiters(state, tokensMeta[curr].delimiters);
      }
    }
  }

  /**
   * ``mark_open``/``mark_close`` אינם צריכים כלל renderer משלהם: ה-renderer הכללי של
   * markdown-it מרנדר כל טוקן לא מוכר לפי ``tag`` ו-``nesting``, וזה נותן בדיוק
   * ``<mark>...</mark>``. כך זה עבד גם קודם.
   */
  function mdMarkPlugin(md) {
    md.inline.ruler.before('emphasis', 'mark', tokenize);
    md.inline.ruler2.before('emphasis', 'mark', postProcess);
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = mdMarkPlugin;   // לבדיקות מ-Node
  }
  if (root) {
    root.MdMarkPlugin = mdMarkPlugin; // שימוש בדפדפן
  }
})(typeof window !== 'undefined' ? window : null);
