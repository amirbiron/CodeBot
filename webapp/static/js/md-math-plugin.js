/**
 * md-math-plugin.js — תוסף markdown-it לנוסחאות: ``$...$`` בתוך שורה, ``$$...$$`` כבלוק, ב-KaTeX.
 *
 * **למה הקובץ הזה קיים.** עד עכשיו הנוסחאות זוהו *אחרי* markdown-it: ``renderMathInElement`` של
 * KaTeX רץ על ה-HTML המוכן, בתצוגת המסמך (``md_preview.html``) ובתצוגה החיה (``live-preview.js``),
 * עם ``$`` ו-``$$`` כמפרידים. זה יצר שלוש תקלות:
 *
 * 1. **כל זוג ``$`` בטקסט רגיל הפך לנוסחה.** "עולה $5 ובפרימיום $10", או ``$substrCP`` ו-``$substrBytes``
 *    באותה פסקה, הוצגו בגופן מתמטי נטוי ובלי רווחים. KaTeX עצמו מזהיר מזה: ב-
 *    ``contrib/auto-render/auto-render.js`` ה-``$`` הבודד כבוי כברירת מחדל, עם ההערה
 *    "LaTeX uses $…$, but it ruins the display of normal `$` in text".
 * 2. **Markdown השחית את הנוסחה לפני ש-KaTeX ראה אותה.** ``\\`` (שורה חדשה במטריצה) הפך ל-``\`` בגלל
 *    ה-escape של Markdown, ו-``_`` ו-``*`` היו חשופים לפענוח של הדגשה.
 * 3. **בלוק ``$$`` על כמה שורות לא רונדר בכלל.** עם ``breaks: true`` כל ירידת שורה היא ``<br>``, וכל
 *    שורה היא צומת טקסט נפרד, ולכן ל-``$$`` הפותח לא נמצא סוגר. ושורה של ``=`` בתוך מטריצה הפכה
 *    את כל הפסקה לכותרת (setext) עוד לפני כן.
 *
 * **המנגנון.** שני כללים שקוראים את המקור הגולמי ושומרים אותו כמו שהוא ב-``token.content``, ולכן
 * התוכן מגיע ל-KaTeX כמו שנכתב: ``\\`` נשאר ``\\``. הכללים לא מפענחים את מה שבפנים, ולכן **אין כאן
 * קריאה ל-``inline.parse``** — זו הקריאה שהפילה את כל התצוגה בתוסף המארקר (``md-mark-plugin.js``).
 * כלל ה-inline רץ על כל ``$`` שכלל ה-text עצר עליו: ``$`` הוא תו מסיים ב-``rules_inline/text.mjs``.
 * כלל ה-block בנוי במבנה של ``rules_block/fence.mjs``, וקודם לו בשרשרת, כדי ששורות התוכן לא יפורשו
 * כבלוקים בעצמן — ``=`` לבד בשורה (כותרת), ``- 2x`` (רשימה), ``> `` (ציטוט).
 *
 * **הכללים.** הבסיס הוא pandoc (``MANUAL.txt``, הסעיף "Extension: tex_math_dollars"):
 *
 * - אחרי ה-``$`` הפותח אין רווח, ולפני ה-``$`` הסוגר אין רווח.
 * - המפריד הסוגר הוא ה-``$`` הראשון אחרי הפותח. אם הוא אינו תקין, אין נוסחה, ולא מחפשים סוגר אחר.
 * - ``$$...$$`` הוא נוסחת תצוגה, ומותר רווח בין המפרידים לנוסחה. בין ``$$`` ל-``$$`` אין שורה ריקה.
 * - ``\`` מכסה את התו שאחריו. בתוך נוסחה ``\$`` שייך ל-TeX ואינו סוגר. מחוץ לנוסחה ``\$`` נצרך קודם
 *   על ידי כלל ה-escape של markdown-it, ומוצג כסימן דולר רגיל.
 *
 * ועליהם כללים משלנו. pandoc פוסל רק ספרה אחרי הסוגר (``$20,000 and $30,000``), וזה לא מספיק לטקסט
 * שלנו: במשפט ``$substrCP\`\`, ולעולם לא \`\`$substrBytes`` ה-``$`` השני צמוד מבפנים לגרש ואחריו
 * האות ``s``, ולכן לפי pandoc בלבד זו נוסחה.
 *
 * - **``$`` שצמוד מבחוץ לאות לטינית או לספרה אינו מפריד** (``isWordChar``): לא לפני הפותח, ולא אחרי
 *   הסוגר. כך ``$5``, ``$set``, ``$HOME:$PATH``, ``$$ROOT`` ו-``$$CURRENT`` נשארים טקסט. המחיר:
 *   ``$n$th`` אינו נוסחה. אותיות עבריות אינן בכלל הזה בכוונה, ולכן ``ב$x$`` ו-``$x$-ים`` כן.
 * - **``$`` שאחריו עוד ``$`` אינו סוגר**: הוא תחילת ``$$``. בלי זה ``$substrBytes … ו-$$ROOT`` נסגר על
 *   החצי הראשון של ``$$ROOT``.
 * - **אות עברית מחוץ לסוגריים מסולסלים מבטלת נוסחה בתוך שורה** (``hasBareHebrew``). ב-TeX אות
 *   עברית אינה סמל של נוסחה, ועברית בנוסחה נכתבת בקבוצה — ``\text{מרחק}``. עברית חשופה בין שני
 *   ``$`` היא טקסט: ``$10, ולפעמים 5$``, מחיר בשני הסגנונות באותה פסקה, ש-pandoc מזהה כנוסחה. בלוק
 *   ``$$`` אינו בכלל הזה: הוא מפורש, בשורות משלו.
 * - **גרש הפוך (`` ` ``) לפני הסוגר מבטל את הנוסחה.** קוד שמתחיל אחרי ``$`` פותח לא נבלע בתוך נוסחה,
 *   ו-``$`` שבתוכו נשאר טקסט. קוד שמתחיל לפני ה-``$`` נצרך שלם על ידי כלל ה-backticks, עוד לפני שהכלל
 *   הזה רואה את ה-``$``.
 *
 * בלוק ``$$`` שלא נסגר אינו נוסחה. בניגוד לגדר קוד, הוא לא בולע את המשך המסמך: ``$$`` בודד בטקסט
 * (מספר התהליך ב-shell) נשאר טקסט.
 *
 * **הרינדור.** ``katex.renderToString`` מתוך ה-renderer של markdown-it:
 *
 * - ``throwOnError: false``: שגיאת תחביר של TeX (``ParseError``) מוצגת כמקור הנוסחה באדום, וההודעה
 *   ב-``title``. זה ``renderError`` של KaTeX, שבודק ``instanceof ParseError`` וזורק כל חריגה אחרת.
 * - ``macros`` אחד לכל רינדור של מסמך (``documentMacros``): ``\gdef`` בנוסחה אחת זמין בנוסחאות שאחריה
 *   באותו מסמך, ולא במסמך אחר. כך זה עבד גם עם ``renderMathInElement``, שהעביר ``macros`` אחד לכל
 *   הנוסחאות שבקריאה שלו.
 * - ``dir="ltr"`` על העטיפה: ל-CSS של KaTeX אין הגדרת כיוון, ובעמוד ``dir="rtl"`` חלקי הנוסחה סודרו
 *   מימין לשמאל: ``E = mc^2`` הוצג כ-``²mc = E``. התכונה ``dir`` מבודדת את הנוסחה גם בלי CSS, ולכן
 *   היא עובדת בכל עמוד שמרנדר Markdown.
 * - **חריגה שאינה ``ParseError`` נתפסת לכל נוסחה בנפרד.** קינון עמוק של סוגריים זורק ``RangeError``
 *   מתוך KaTeX גם עם ``throwOnError: false``, וחריגה מתוך ה-renderer מפילה את ``md.render`` כולו: בתצוגת
 *   המסמך היא מחליפה את כל המסמך ב"שגיאה ברינדור Markdown". הנוסחה הזו מקבלת מצב משלה — המקור שלה
 *   עם ``md-math-error`` וההודעה ב-``title`` — והחריגה נרשמת במלואה ב-``console.error``.
 *   ``tests/md-math-plugin.test.js`` מכסה את המקרה.
 *
 * שימוש:
 *     md.use(window.MdMathPlugin, { katex: window.katex }); // דפדפן; KaTeX מגיע מהבאנדל
 *     md.use(plugin, { katex });                            // Node, לבדיקות
 *
 * מקור לכל מה שכתוב כאן: markdown-it@14.1.0 (``rules_inline/text.mjs``, ``rules_block/fence.mjs``,
 * ``parser_inline.mjs``), KaTeX 0.16.25 (``renderToString``, ``renderError``, ``Namespace``), וה-
 * ``MANUAL.txt`` של pandoc.
 */
(function (root) {
  'use strict';

  var DOLLAR = 0x24;      /* $ */
  var BACKSLASH = 0x5C;   /* \ */
  var BACKTICK = 0x60;    /* ` */
  var OPEN_BRACE = 0x7B;  /* { */
  var CLOSE_BRACE = 0x7D; /* } */

  /**
   * אות לטינית או ספרה. ``$`` שצמוד לאחד מהם מבחוץ הוא חלק ממילה — ``$5``, ``$set``, ``US$`` — ולא
   * מפריד של נוסחה. אותיות עבריות אינן כאן בכוונה: ``ב$x$`` ו-``$x$-ים`` הם נוסחה.
   */
  function isWordChar(code) {
    return (code >= 0x30 && code <= 0x39) || // 0-9
           (code >= 0x41 && code <= 0x5A) || // A-Z
           (code >= 0x61 && code <= 0x7A);   // a-z
  }

  /** בלוק העברית ב-Unicode (U+0590–U+05FF): אותיות, ניקוד וטעמים. */
  function isHebrew(code) {
    return code >= 0x0590 && code <= 0x05FF;
  }

  /**
   * אות עברית שאינה בתוך סוגריים מסולסלים. ב-TeX אות עברית אינה סמל של נוסחה — KaTeX מתריע עליה
   * במצב מתמטי ("Unrecognized Unicode character") — ועברית בתוך נוסחה נכתבת בקבוצה, כמו
   * ``\text{מרחק}``. ולכן עברית מחוץ לכל קבוצה היא סימן שבין שני ה-``$`` יש טקסט ולא נוסחה:
   * ``$10, ולפעמים 5$``. ``\`` מדלג על התו שאחריו, כך ש-``\{`` ו-``\}`` אינם פותחים או סוגרים קבוצה.
   */
  function hasBareHebrew(src, from, to) {
    var depth = 0;
    var pos = from;

    while (pos < to) {
      var ch = src.charCodeAt(pos);

      if (ch === BACKSLASH) { pos += 2; continue; }
      if (ch === OPEN_BRACE) { depth++; }
      else if (ch === CLOSE_BRACE) { if (depth > 0) { depth--; } }
      else if (depth === 0 && isHebrew(ch)) { return true; }
      pos++;
    }

    return false;
  }

  /**
   * המיקום של המפריד הסוגר — ה-``$`` הראשון (``width`` 1) או ה-``$$`` הראשון (``width`` 2) מ-``from``
   * ועד ``max`` — או -1. ``\`` מדלג על התו שאחריו. בנוסחת תצוגה ``$`` בודד הוא חלק מהתוכן.
   * עם ``stopAtBacktick``, גרש הפוך לפני הסוגר מחזיר -1: מכאן מתחיל קוד, והוא לא נבלע בנוסחה.
   */
  function findCloser(src, from, max, width, stopAtBacktick) {
    var pos = from;

    while (pos < max) {
      var ch = src.charCodeAt(pos);

      if (ch === BACKSLASH) { pos += 2; continue; }
      if (ch === BACKTICK && stopAtBacktick) { return -1; }
      if (ch === DOLLAR) {
        if (width === 1) { return pos; }
        if (pos + 1 < max && src.charCodeAt(pos + 1) === DOLLAR) { return pos; }
      }
      pos++;
    }

    return -1;
  }

  /**
   * בודק נוסחה בתוך שורה שמתחילה ב-``start``, עם מפריד ברוחב ``width``. מחזיר את המיקום שאחרי
   * המפריד הסוגר, או -1 כשזו אינה נוסחה.
   */
  function scanInline(state, start, width) {
    var src = state.src;
    var max = state.posMax;
    var isWhiteSpace = state.md.utils.isWhiteSpace;
    var from = start + width;

    if (start > 0 && isWordChar(src.charCodeAt(start - 1))) { return -1; }
    if (from >= max) { return -1; }
    if (width === 1 && isWhiteSpace(src.charCodeAt(from))) { return -1; }

    var close = findCloser(src, from, max, width, true);

    if (close < 0) { return -1; }
    if (width === 1 && isWhiteSpace(src.charCodeAt(close - 1))) { return -1; }
    if (width === 2 && !src.slice(from, close).trim()) { return -1; }

    var after = close + width;

    if (after < max && isWordChar(src.charCodeAt(after))) { return -1; }
    // ``$`` ש-``$`` נוסף בא מיד אחריו הוא תחילת ``$$`` — ``$substrBytes ... $$ROOT`` — ולא סוגר
    if (width === 1 && after < max && src.charCodeAt(after) === DOLLAR) { return -1; }
    if (hasBareHebrew(src, from, close)) { return -1; }

    return after;
  }

  /**
   * כלל inline: ``$...$``, ו-``$$...$$`` בתוך פסקה (נוסחת תצוגה). רץ גם במצב ``silent``, שבו
   * ``skipToken`` מדלג על טוקן שלם בזמן שהוא מחפש את סוף התווית של קישור (``parser_inline.mjs``),
   * ולכן הכלל מקדם את ``state.pos`` גם בלי לדחוף טוקן.
   */
  function mathInline(state, silent) {
    var src = state.src;
    var start = state.pos;
    var max = state.posMax;

    if (src.charCodeAt(start) !== DOLLAR) { return false; }

    var run = 1;
    while (start + run < max && src.charCodeAt(start + run) === DOLLAR) { run++; }

    var end = run <= 2 ? scanInline(state, start, run) : -1;

    if (end < 0) {
      // לא נוסחה: כל רצף הדולרים הוא טקסט. כך ה-``$`` השני של ``$$`` שלא נסגר אינו נבדק שוב
      // כפותח של נוסחה בתוך שורה.
      if (!silent) { state.pending += src.slice(start, start + run); }
      state.pos = start + run;
      return true;
    }

    if (!silent) {
      var token = state.push('math_inline', 'math', 0);
      token.markup = src.slice(start, start + run);
      token.content = src.slice(start + run, end - run);
    }
    state.pos = end;
    return true;
  }

  /**
   * כלל block: שורה שמתחילה ב-``$$``, עד השורה שבה נמצא ה-``$$`` הסוגר. אחרי הסוגר מותרים רק רווחים;
   * אחרת זו פסקה שיש בתוכה נוסחת תצוגה, וכלל ה-inline מטפל בה. המבנה — הזחה, שורות של מכולה
   * (רשימה, ציטוט) ו-``getLines`` — הוא של ``rules_block/fence.mjs``. ההבדל: אין סגירה אוטומטית
   * בסוף המסמך, ושורה ריקה עוצרת. במצב ``silent`` (בדיקה אם הבלוק קוטע פסקה) הבדיקה מלאה, כדי
   * ששורה שמתחילה ב-``$$`` ואינה נוסחה לא תקטע את הפסקה שלה.
   */
  function mathBlock(state, startLine, endLine, silent) {
    var src = state.src;
    var pos = state.bMarks[startLine] + state.tShift[startLine];
    var max = state.eMarks[startLine];

    // מוזח ב-4 רווחים או יותר: זה בלוק קוד
    if (state.sCount[startLine] - state.blkIndent >= 4) { return false; }
    if (pos + 2 > max) { return false; }
    if (src.charCodeAt(pos) !== DOLLAR || src.charCodeAt(pos + 1) !== DOLLAR) { return false; }
    if (pos + 2 < max && src.charCodeAt(pos + 2) === DOLLAR) { return false; }

    var from = pos + 2;
    var line = startLine;
    var lineEnd = max;
    var close = findCloser(src, from, lineEnd, 2, false);

    while (close < 0) {
      line++;
      if (line >= endLine) { return false; }
      if (state.isEmpty(line)) { return false; }
      // שורה לא ריקה עם הזחה קטנה מזו של המכולה: הרשימה או הציטוט נגמרו
      if (state.sCount[line] < state.blkIndent) { return false; }
      lineEnd = state.eMarks[line];
      close = findCloser(src, state.bMarks[line] + state.tShift[line], lineEnd, 2, false);
    }

    if (state.skipSpaces(close + 2) < lineEnd) { return false; }

    var content;
    if (line === startLine) {
      content = src.slice(from, close);
    } else {
      content = src.slice(from, max) + '\n' +
        state.getLines(startLine + 1, line, state.sCount[startLine], true) +
        src.slice(state.bMarks[line] + state.tShift[line], close);
    }

    if (!content.trim()) { return false; }
    if (silent) { return true; }

    state.line = line + 1;

    var token = state.push('math_block', 'div', 0);
    token.content = content;
    token.markup = '$$';
    token.map = [startLine, state.line];

    return true;
  }

  /**
   * ``\gdef`` כותב לאובייקט ``macros`` שהועבר ל-KaTeX (``Namespace.set`` עם ``global``). אובייקט אחד
   * לכל רינדור משתף את ההגדרות בין הנוסחאות של אותו מסמך. ``env`` נוצר מחדש בכל ``md.render``.
   */
  function documentMacros(env) {
    if (!env.mdMathMacros) { env.mdMathMacros = {}; }
    return env.mdMathMacros;
  }

  function mdMathPlugin(md, options) {
    var katex = options && options.katex;
    var escapeHtml = md.utils.escapeHtml;

    function renderTex(token, displayMode, env) {
      try {
        return katex.renderToString(token.content, {
          displayMode: displayMode,
          throwOnError: false,
          macros: documentMacros(env)
        });
      } catch (err) {
        // ParseError לא מגיע לכאן: ``throwOnError: false`` מרנדר אותו. מה שמגיע הוא תקלה בנוסחה
        // הזו (``RangeError`` על קינון עמוק) או KaTeX שלא נטען. מצב משלה, כדי שלא תפיל את המסמך.
        console.error('md-math-plugin: KaTeX failed on a formula', err);
        return '<span class="md-math-error" title="' + escapeHtml(String(err)) + '">' +
          escapeHtml(token.markup + token.content + token.markup) + '</span>';
      }
    }

    md.inline.ruler.after('escape', 'math_inline', mathInline);
    md.block.ruler.before('fence', 'math_block', mathBlock, {
      alt: ['paragraph', 'reference', 'blockquote', 'list']
    });

    md.renderer.rules.math_inline = function (tokens, idx, _options, env) {
      var token = tokens[idx];
      return '<span class="md-math" dir="ltr">' + renderTex(token, token.markup === '$$', env) + '</span>';
    };

    // ``renderAttrs``: מאפיינים שתוספים אחרים מצמידים לבלוק — ``data-source-line`` של מיפוי
    // המקור ב-``md_preview.html``, שההעתקה כמארקדאון והעיגון של הפתקים נשענים עליו.
    md.renderer.rules.math_block = function (tokens, idx, _options, env, self) {
      var token = tokens[idx];
      return '<div class="md-math" dir="ltr"' + self.renderAttrs(token) + '>' +
        renderTex(token, true, env) + '</div>\n';
    };
  }

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = mdMathPlugin;   // לבדיקות מ-Node
  }
  if (root) {
    root.MdMathPlugin = mdMathPlugin; // שימוש בדפדפן
  }
})(typeof window !== 'undefined' ? window : null);
