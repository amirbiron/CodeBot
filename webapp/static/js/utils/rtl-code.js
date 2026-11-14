/**
 * זיהוי ויישור RTL לבלוקי קוד עם תוכן בעברית, ועברית בתוך שורת קוד.
 * משותף ל-live-preview, repo-browser, md_preview ו-safe-highlight
 * (``isolateHebrewTokens``, שרץ בכל הדגשה שעוברת דרכו).
 */
(function () {
  'use strict';

  var HEBREW_THRESHOLD = 0.3;

  /**
   * כמה אותיות עבריות וכמה אותיות בכלל יש בטקסט: ``{hebrew, letters}``.
   * "אות" היא עברית (U+0590–U+05FF) או לטינית (A-Z, a-z). סימנים, חיצים,
   * מספרים, סימני פיסוק ורווחים לא נספרים — כך הם לא מדללים את היחס.
   *
   * **הספירה נפרדת מההחלטה כדי ששתיהן ייכתבו פעם אחת.** ``isHebrewMajority``
   * שואלת על טקסט אחד, ו-``innerFences`` שואלת על טווח שורות בתוך בלוק — לכל
   * גדר פנימית — ולכן סוכמת את הספירה של כל שורה פעם אחת. הספירות מצטרפות,
   * כי ירידת שורה אינה אות.
   */
  function letterCounts(text) {
    var s = text == null ? '' : String(text);
    var hebrew = 0;
    var letters = 0;
    for (var i = 0; i < s.length; i++) {
      var c = s.charCodeAt(i);
      if (c >= 0x0590 && c <= 0x05FF) {
        hebrew++;
        letters++;
      } else if ((c >= 0x0041 && c <= 0x005A) || (c >= 0x0061 && c <= 0x007A)) {
        letters++;
      }
    }
    return { hebrew: hebrew, letters: letters };
  }

  // ההחלטה עצמה, על ספירה של ``letterCounts``. בלי אותיות בכלל — לא עברי.
  function hebrewShareAboveThreshold(hebrew, letters) {
    return letters > 0 && hebrew / letters > HEBREW_THRESHOLD;
  }

  function isHebrewMajority(text) {
    var counts = letterCounts(text);
    return hebrewShareAboveThreshold(counts.hebrew, counts.letters);
  }

  /**
   * שמות שאינם שפת תכנות אמיתית. בלוק שנושא אחד מהם נחשב "בלי שפה",
   * ולכן הוא עדיין מועמד ליישור לימין.
   *
   * **מקור אחד לשתי צורות של אותה שאלה.** לצרכן אחד יש אלמנט DOM עם
   * ``class="language-…"`` (תצוגת המסמכים), ולצרכנים אחרים יש את שם השפה
   * הגולמי שכבר נגזר משורת הגדר: הפתקים בונים ``div`` ולא ``pre``, ולכן
   * אין להם מחלקה לקרוא; ו-``innerFences`` שואלת על גדר פנימית, שהיא שורה
   * בתוך הטקסט של בלוק ולא אלמנט. הרשימה נכתבת כאן פעם אחת והרג'קס נבנה
   * ממנה, כדי שהצרכנים לא יוכלו לענות תשובות שונות על אותו קלט.
   *
   * **``markdown`` ו-``md`` כאן אף שהם שפה שיש לה הדגשה.** השאלה אינה
   * "האם יש ל-hljs דקדוק לשם הזה" אלא "האם הצהרה על השם הזה אומרת שזה
   * קוד". בלוק מארקדאון הוא טקסט לקריאה — ובעברית הוא מתנהג כמו הערה,
   * לא כמו קוד — ולכן הוא מועמד ליישור לימין כמו ``text``. שני השמות
   * יחד כי בריפו הם אותה שפה (ראו ``isMarkdownLanguage`` ב-
   * ``live-preview.js`` וב-``repo-browser.js``). ההדגשה עצמה אינה נפגעת:
   * ההחלטה כאן נוגעת רק ביישור, ו-hljs ממשיך לקרוא את אותה מחלקה.
   */
  var PLAIN_LANGUAGE_NAMES = ['plaintext', 'text', 'nohighlight', 'none', 'txt', 'markdown', 'md'];

  // **חלופה אחת ששתי הצורות נבנות ממנה.** הגבול אחרי השם הוא חלק
  // מהשאלה ולא קישוט: בלעדיו ``texture`` נבלע ב-``text``. וחשוב מכך, הוא
  // מגדיר שהשאלה היא "**מתחיל** בשם פטור שנגמר בגבול" ולא "שווה לשם
  // פטור" — ולכן ``text,`` הוא ``text``. רשימה משותפת בלי הסמנטיקה
  // המשותפת הספיקה כדי ששתי הצורות יחלקו על שמונה קלטים.
  //
  // **הגבול הוא "אין אחריו אות, סימן צירוף, ספרה או קו תחתון" בכל כתב,
  // ולא ``\b``.** ‏``\b`` ב-JavaScript מכיר רק ``[A-Za-z0-9_]`` כתווי מילה,
  // וגם הדגל ``u`` לבדו אינו מרחיב את זה (MDN, "Word boundary assertion").
  // לכן אות עברית אחרי השם נחשבה סוף מילה, ו-``mdעברית`` או ``textעברית``
  // נחשבו "בלי שפה" ומתהפכים — אף שזה שם אחר. פיסוק ומקף עדיין נחשבים
  // גבול, בדיוק כמו קודם, כך ש-``text,`` ו-``md-x`` לא זזו. ‏``\p{…}`` עובד
  // רק עם הדגל ``u`` (MDN, "Unicode character class escape"), ולכן שני
  // הרג'קסים נבנים איתו.
  var NAME_END = '(?![\\p{L}\\p{M}\\p{N}_])';
  var PLAIN_LANGUAGE_PREFIX =
    PLAIN_LANGUAGE_NAMES.map(function (n) { return n + NAME_END; }).join('|');

  var EXPLICIT_LANGUAGE_RE = new RegExp('\\blanguage-(?!' + PLAIN_LANGUAGE_PREFIX + ')\\S+', 'u');
  var PLAIN_LANGUAGE_NAME_RE = new RegExp('^(?:' + PLAIN_LANGUAGE_PREFIX + ')', 'u');

  /**
   * האם שם השפה **הגולמי** הוא שפה אמיתית — אותה שאלה, בלי DOM.
   *
   * **רגיש לרישיות במכוון**, בדיוק כמו הרג'קס: ``Text`` נחשב שפה אמיתית
   * ולכן בלוק כזה אינו מתהפך. ``toLowerCase`` כאן נראה כמו שיפור והוא
   * בדיוק הפער ששיתוף הרשימה בא למנוע — אותו קלט היה מתהפך בפתק ולא
   * במסמך. הרשימה המשותפת מבטיחה שהרשימה זהה; רק זה מבטיח שההשוואה זהה.
   *
   * **ומאותה סיבה זו בדיקת תחילית ולא ``indexOf``.** השוואה מלאה ענתה
   * "שפה אמיתית" על ``text,`` בזמן שהרג'קס ראה שם ``text`` ועבר —
   * ‏``markdown-it`` מפיק ``class="language-text,"`` על גדר כזו, ולכן
   * אותו קלט בדיוק התהפך במסמך ולא בפתק. נסיון לפתור בנרמול (לחתוך את
   * השם עד הגבול הראשון) נמדד ופותח פער חדש בכיוון ההפוך, על שמות
   * שאינם פותחים באות כמו ``-x``. התחילית היא מה שמגיע לאפס.
   */
  function hasExplicitLanguageName(name) {
    var n = String(name || '').trim();
    if (!n) return false;
    return !PLAIN_LANGUAGE_NAME_RE.test(n);
  }

  function hasExplicitLanguage(block) {
    var cls = block.className || '';
    // שפות שאינן שפות תכנות אמיתיות – לא חוסמות זיהוי RTL
    return EXPLICIT_LANGUAGE_RE.test(cls);
  }

  /**
   * בודק אם בלוק קוד מכיל תוכן בעברית ללא שפת תכנות מוגדרת,
   * ומחיל direction: rtl + class rtl-code, או מסיר אותם אם לא.
   *
   * חשוב: יש לקרוא לפונקציה *לפני* hljs.highlightElement כדי שהבדיקה
   * תתבסס על ה-class המקורי ולא על זיהוי אוטומטי של hljs. את
   * ``wrapInnerFences`` קוראים להפך — *אחרי* ההדגשה.
   */
  function applyRtlIfHebrew(block) {
    var parent = block.closest('pre');
    if (!parent) return false;

    var isHebrew = !hasExplicitLanguage(block) && isHebrewMajority(block.textContent);

    parent.style.direction = isHebrew ? 'rtl' : 'ltr';
    parent.style.textAlign = isHebrew ? 'right' : 'left';

    if (isHebrew) {
      parent.classList.add('rtl-code');
    } else {
      parent.classList.remove('rtl-code');
    }

    return isHebrew;
  }

  // ─── קטעי קוד פנימיים בבלוק עברי ───────────────────────────────────
  //
  // בלוק עברי מקבל ``direction: rtl`` (ראו ``applyRtlIfHebrew``). כשבתוכו
  // יש דוגמת קוד עם גדרות משלה, הכיוון הימני חל גם עליה: שורת הגדר
  // ```python מוצגת כ-python``` והשורה המוזחת מתחילה משמאל לשורה שמעליה. הכיוון
  // נקבע לפי **סוג התוכן ולא לפי האותיות**: טקסט ורשימות הולכים עם כיוון
  // הבלוק, ורק קוד הוא משמאל לימין. כלל לפי האות החזקה הראשונה
  // (``unicode-bidi: plaintext``) נבדק ב-Markdown-Docs ונפסל: ב-
  // ``- `editor.background` → רקע המסמך`` האות הראשונה לועזית, והשורה קפצה
  // שמאלה באמצע רשימה עברית. זו אותה הכרעה שמתועדת ב-``sticky-notes.css`` ליד
  // ``.sticky-md-code-block.rtl-code``.
  //
  // **ומה נחשב קוד — אותה שאלה כמו על בלוק רגיל.** גדר פנימית היא קוד אלא אם
  // היא עונה על שני התנאים ש-``applyRtlIfHebrew`` שואלת על בלוק: שם השפה שלה
  // אינו מצהיר על קוד (``hasExplicitLanguageName``, מול ``PLAIN_LANGUAGE_NAMES``),
  // והתוכן שלה עובר את ``HEBREW_THRESHOLD`` של ``letterCounts``. בלוק פנימי כזה
  // הוא טקסט, ונשאר עם כיוון הבלוק — כולל שורות הגדר שלו, שהגרשיים בהן
  // מצוירים בתחילת השורה, בקצה הימני, כמו האות הראשונה של הטקסט שהם תוחמים.
  // ואותה שאלה בכל רמה: בתוך בלוק פנימי כזה, דוגמת קוד שוב משמאל לימין.

  /**
   * האם השורה פותחת גדר, ובאיזו: ``{marker, length, lang}`` או ``null``.
   *
   * **הכלל של CommonMark 0.31.2, סעיף 4.5, כפי ש-markdown-it 14.1.0 מממש
   * אותו** (``rules_block/fence.mjs`` — הפרסר שמרנדר את המסמכים כאן): שלושה
   * גרשיים או שלוש טילדות לפחות, ובגדר של גרשיים השארית אינה מכילה גרש
   * (דוגמה 145: השורה "``` aa ```" היא קוד בשורה, לא גדר). בגדר של טילדות
   * השארית יכולה להכיל גרשיים (דוגמה 146).
   *
   * **``lang`` הוא שם השפה שבלוק רגיל היה מקבל משורת הגדר הזו.** ב-markdown-it
   * 14.1.0 כל מה שאחרי הגרשיים נשמר ב-``token.info`` (``fence.mjs``), וה-renderer
   * לוקח ממנו את המילה הראשונה אחרי ``trim()`` — ``split(/(\s+)/g)[0]`` — לתוך
   * ``class="language-…"`` (``default_rules.fence`` ב-``renderer.mjs``). אותו
   * ``trim`` ואותו ``\s`` כאן, ולכן אותה מילה. **ההבדל היחיד:** ה-renderer מעביר
   * את ``info`` קודם דרך ``unescapeAll`` (``common/utils.mjs``), שמפענח ``\`` לפני
   * סימן פיסוק וישויות HTML, וכאן לא — ``&#116;ext`` הוא ``text`` שם ונשאר
   * ``&#116;ext`` כאן. ``unescapeAll`` אינו נוגע במחרוזת שאין בה ``\`` או ``&``,
   * ולכן ההבדל קיים רק בשם שפה שנכתב כך.
   *
   * **הזחה אינה נבדקת, בכוונה.** CommonMark מתיר עד שלושה רווחים, אבל
   * הטקסט של בלוק הקוד מנותק מההקשר שלו: דוגמה שנכתבה בתוך פריט רשימה
   * ("1. התקינו:" ואחריה ```bash מוזחת) היא קוד, ומקומה משמאל לימין.
   * רווחים וטאבים מובילים מדולגים — אותם שני תווים ש-``isSpace`` של
   * markdown-it מכיר (``common/utils.mjs``).
   *
   * **סריקה של תווים ולא ביטוי רגולרי.** ב-Markdown-Docs ביטוי שפיצל את
   * השארית בתוך עצמו ניסה כל חלוקה של רצף רווחים: בדיקה אחת של שורה עם
   * 1,600 רווחים לקחה 1.6 שניות, והפריוויו מריץ אותה על כל שורה. כאן כל
   * תו נקרא פעם אחת, ושם השפה נחתך ב-``search`` ולא מפוצל בתוך ביטוי.
   */
  function fenceOpening(line) {
    var s = String(line);
    var i = 0;
    while (i < s.length && (s[i] === ' ' || s[i] === '\t')) i++;
    var marker = s[i];
    if (marker !== '`' && marker !== '~') return null;
    var start = i;
    while (i < s.length && s[i] === marker) i++;
    if (i - start < 3) return null;
    if (marker === '`' && s.indexOf('`', i) >= 0) return null;
    var info = s.slice(i).trim();
    var gap = info.search(/\s/);
    return { marker: marker, length: i - start, lang: gap < 0 ? info : info.slice(0, gap) };
  }

  /**
   * האם השורה יכולה לסגור גדר, ובאיזה רצף: ``{marker, length}`` או ``null``.
   * רק שורה שכולה אותו תו, ואחריו רק רווחים או טאבים. היא סוגרת גדר של אותו
   * תו שאורכה לכל היותר ``length`` — ```` אינה נסגרת ב-``` (דוגמה 124), ושורה
   * עם שם שפה אינה סוגרת (דוגמה 147). אותו כלל כמו לולאת הסגירה ב-``fence.mjs``,
   * חוץ מההזחה — מאותה סיבה כמו ב-``fenceOpening``.
   */
  function closingRun(line) {
    var s = String(line);
    var i = 0;
    while (i < s.length && (s[i] === ' ' || s[i] === '\t')) i++;
    var marker = s[i];
    if (marker !== '`' && marker !== '~') return null;
    var start = i;
    while (i < s.length && s[i] === marker) i++;
    var length = i - start;
    while (i < s.length && (s[i] === ' ' || s[i] === '\t')) i++;
    return i === s.length ? { marker: marker, length: length } : null;
  }

  // המקום של הגדר הראשונה ב-``candidates`` שאורכה לכל היותר ``length``, או
  // ``candidates.length``. האורכים שם יורדים ממש, ולכן חיפוש בינארי.
  function firstClosable(candidates, length) {
    var lo = 0;
    var hi = candidates.length;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (candidates[mid].length <= length) hi = mid;
      else lo = mid + 1;
    }
    return lo;
  }

  /**
   * מחלקת את הטקסט של בלוק לקטעים רציפים של שורות: ``{ltr, from, to}``,
   * כש-``to`` אינו כלול. קטע ``ltr`` הוא דוגמת קוד: מהגדר הפותחת ועד הגדר
   * הסוגרת שלה, **כולל שתי שורות הגדר**, או עד הסוף כשהגדר לא נסגרה. כל השאר
   * בקטעים שאינם ``ltr`` — טקסט, שורות ריקות סביב הגדר, ובלוקים פנימיים
   * שהם טקסט (ההסבר בראש הפרק), כולל שורות הגדר שלהם.
   *
   * **מעבר אחד על השורות, עם מחסנית של הגדרות הפתוחות.** הגדרות מקוננות:
   * בלוק פנימי שהוא טקסט יכול להכיל דוגמת קוד משלו, ולכן ההחלטה נשאלת שוב
   * בתוכו. שתי הכרעות קובעות את הסגירה, ושתיהן של markdown-it כשהוא מפרסר את
   * התוכן של בלוק כמסמך בפני עצמו: (1) שורה שיכולה לסגור כמה גדרות פתוחות
   * סוגרת את **החיצונית** מביניהן — הגדר החיצונית נסגרת בשורה הראשונה שסוגרת
   * אותה, בלי קשר למה שנפתח בתוכה; (2) גדר פנימית שלא נסגרה עד אז נגמרת
   * בשורה שלפני, כמו גדר שלא נסגרה עד סוף המסמך. בתוך דוגמת קוד (שם שפה
   * מוצהר) לא נפתחות גדרות. בתוך גדר בלי שם שפה הן נפתחות מראש, כי עוד לא
   * ידוע אם התוכן שלה עברי; התשובה לא משנה איפה היא נגמרת, רק אם מסתכלים על
   * מה שבתוכה.
   *
   * **ליניארית באורך הטקסט** — רקורסיה הייתה סורקת כל רמה מחדש, ושרשרת של
   * גדרות פתוחות זו בתוך זו הייתה ריבועית, והתצוגה החיה מרנדרת מחדש בכל
   * הקלדה. כאן כל שורה נקראת פעם אחת, הספירה של כל טווח היא חיסור של
   * סכומים מצטברים, והגדר שנסגרת נמצאת בחיפוש בינארי: רק גדר שקצרה מכל
   * גדר פתוחה מאותו תו שמתחתיה יכולה להיות זו שנסגרת — כל שורה שסוגרת
   * אותה סוגרת גם את זו שמתחתיה, והחיצונית מנצחת.
   */
  function innerFences(text) {
    var lines = String(text == null ? '' : text).split('\n');
    var n = lines.length;
    var hebrewBefore = [0];
    var lettersBefore = [0];
    var k;
    for (k = 0; k < n; k++) {
      var counts = letterCounts(lines[k]);
      hebrewBefore.push(hebrewBefore[k] + counts.hebrew);
      lettersBefore.push(lettersBefore[k] + counts.letters);
    }

    var fences = [];
    var open = [];
    var closable = { '`': [], '~': [] };
    for (var i = 0; i < n; i++) {
      if (open.length) {
        var run = closingRun(lines[i]);
        var candidates = run ? closable[run.marker] : null;
        var at = candidates ? firstClosable(candidates, run.length) : 0;
        if (candidates && at < candidates.length) {
          var closed = candidates[at];
          for (k = open.length - 1; k > closed.depth; k--) open[k].last = i - 1;
          closed.close = i;
          closed.last = i;
          open.length = closed.depth;
          ['`', '~'].forEach(function (m) {
            var list = closable[m];
            while (list.length && list[list.length - 1].depth >= closed.depth) list.pop();
          });
          continue;
        }
      }
      var parent = open.length ? open[open.length - 1] : null;
      if (parent && parent.code) continue;
      var opening = fenceOpening(lines[i]);
      if (!opening) continue;
      var fence = {
        open: i, close: -1, last: n - 1, length: opening.length, parent: parent, depth: open.length,
        code: hasExplicitLanguageName(opening.lang),
      };
      fences.push(fence);
      open.push(fence);
      var same = closable[opening.marker];
      if (!same.length || opening.length < same[same.length - 1].length) same.push(fence);
    }

    // ההחלטה, לפי סדר הפתיחה — הורה לפני ילדיו. גדר שההורה שלה הוא קוד אינה
    // נשאלת: היא כבר בתוך קטע ``ltr``.
    var parts = [];
    var from = 0;
    function take(ltr, a, b) {
      if (b > a) parts.push({ ltr: ltr, from: a, to: b });
    }
    fences.forEach(function (f) {
      if (f.parent && !f.parent.text) return;
      var contentEnd = f.close >= 0 ? f.close : f.last + 1;
      f.text = !f.code && hebrewShareAboveThreshold(
        hebrewBefore[contentEnd] - hebrewBefore[f.open + 1],
        lettersBefore[contentEnd] - lettersBefore[f.open + 1]);
      if (f.text) return;
      take(false, from, f.open);
      take(true, f.open, f.last + 1);
      from = f.last + 1;
    });
    take(false, from, n);
    return parts;
  }

  /**
   * טווחי התווים של הקטעים ה-``ltr`` בטקסט: ``{start, end}``, ``end`` לא
   * כלול. הקטע נושא בסופו את ירידת השורה שאחרי הגדר הסוגרת, ולכן הטקסט
   * שמחוצה לו מתחיל בשורה הבאה. ירידת השורה שלפני הגדר הפותחת נשארת
   * בחוץ, בסוף הקטע שלפניו.
   */
  function innerFenceRanges(text) {
    var s = String(text == null ? '' : text);
    var lineStarts = [0];
    for (var k = 0; k < s.length; k++) {
      if (s.charCodeAt(k) === 10) lineStarts.push(k + 1);
    }
    var ranges = [];
    innerFences(s).forEach(function (part) {
      if (!part.ltr) return;
      ranges.push({
        start: lineStarts[part.from],
        end: part.to < lineStarts.length ? lineStarts[part.to] : s.length,
      });
    });
    return ranges;
  }

  // אורך הטקסט של צומת, כפי שהוא נספר ב-``textContent`` של ההורה: הערת HTML
  // אינה טקסט, ולכן אפס.
  function textLength(node) {
    if (node.nodeType === 3) return node.data.length;
    if (node.nodeType === 1) return node.textContent.length;
    return 0;
  }

  /**
   * מפצלת צומת לחלקים לפי ``cuts`` — מיקומים בטקסט שלו, ממוינים, ממש בתוכו
   * (לא בקצוות). צומת טקסט נחתך לצמתי טקסט; אלמנט נשכפל בלי ילדיו לכל חלק,
   * והילדים שלו — מפוצלים באותה דרך — מתחלקים בין השכפולים. כך ``hljs-doctag``
   * שהגבול עובר בתוכו הופך לשני אלמנטים עם אותה מחלקה, ואין צבע שאובד.
   * בלי ``cuts`` הצומת חוזר כמו שהוא.
   */
  function splitNode(node, cuts) {
    if (!cuts.length) return [node];
    var doc = node.ownerDocument;
    var parts = [];
    var i;
    if (node.nodeType === 3) {
      var from = 0;
      for (i = 0; i < cuts.length; i++) {
        parts.push(doc.createTextNode(node.data.slice(from, cuts[i])));
        from = cuts[i];
      }
      parts.push(doc.createTextNode(node.data.slice(from)));
      return parts;
    }
    for (i = 0; i <= cuts.length; i++) parts.push(node.cloneNode(false));
    var seen = 0;
    var k = 0;
    Array.prototype.slice.call(node.childNodes).forEach(function (child) {
      var len = textLength(child);
      while (k < cuts.length && cuts[k] <= seen) k++;
      var inner = [];
      for (var j = k; j < cuts.length && cuts[j] < seen + len; j++) inner.push(cuts[j] - seen);
      var segment = k;
      splitNode(child, inner).forEach(function (part, n) { parts[segment + n].appendChild(part); });
      seen += len;
    });
    return parts;
  }

  /**
   * עוטפת כל טווח ב-``ranges`` — ``{start, end}`` במיקומי התווים של
   * ``textContent`` של ``root``, ממוינים ולא חופפים — באלמנט ש-``makeWrapper``
   * מחזיר, כילד ישיר של ``root``. מחזירה כמה עטיפות נוספו. משותפת ל-
   * ``wrapInnerFences`` ול-``isolateHebrewTokens``.
   *
   * **גוזרת מתוך ה-HTML שכבר נצבע, ולא צובעת מחדש.** אלמנט צבוע שחוצה גבול
   * מפוצל (``splitNode``) — חלק נשאר בחוץ וחלק עובר לעטיפה — ולכן אין צורך
   * לדעת אילו טוקנים highlight.js פורש על כמה שורות, או באיזו שפה הבלוק נצבע.
   * אלמנט שמתחיל או נגמר בדיוק בגבול עובר שלם, בלי קליפה ריקה מאחור.
   * ``textContent`` נשאר זהה תו בתו, וכפתורי ההעתקה קוראים ממנו.
   *
   * **ליניארית באורך התוכן, במעבר אחד.** הגרסה הקודמת גזרה כל טווח ב-
   * ``Range.extractContents`` משלו, וזה היה ריבועי באורך טוקן: כל ``Range``
   * חי מתעדכן בכל שינוי במסמך, נקודה בתוך אלמנט היא "הילד ה-N" ונמצאת בהליכה
   * על האחים, וחיתוך באמצע צומת טקסט מעתיק אותו. ב-docstring עברי של אלפי
   * שורות — טווח לכל שורה — זה נמדד בכרומיום בשניות ארוכות, והתצוגה החיה
   * מרנדרת מחדש בכל הקלדה.
   */
  function wrapTextRanges(root, ranges, makeWrapper) {
    if (!ranges.length) return 0;
    var cuts = [];
    ranges.forEach(function (r) { cuts.push(r.start, r.end); });
    var pieces = [];
    var seen = 0;
    var k = 0;
    Array.prototype.slice.call(root.childNodes).forEach(function (child) {
      var len = textLength(child);
      while (k < cuts.length && cuts[k] <= seen) k++;
      var inner = [];
      for (var j = k; j < cuts.length && cuts[j] < seen + len; j++) inner.push(cuts[j] - seen);
      var bounds = [seen].concat(inner.map(function (c) { return seen + c; }), [seen + len]);
      splitNode(child, inner).forEach(function (part, n) {
        pieces.push({ node: part, start: bounds[n], end: bounds[n + 1] });
      });
      seen += len;
    });
    var frag = root.ownerDocument.createDocumentFragment();
    var wrappers = [];
    var r = 0;
    pieces.forEach(function (p) {
      while (r < ranges.length && ranges[r].end <= p.start) r++;
      var range = ranges[r];
      // חלק באורך אפס (צומת ריק) נכנס רק כשהוא ממש בפנים — כמו שהוא לא
      // נכנס לקטע כשהוא יושב בדיוק על הגבול.
      var inside = range && (p.end > p.start
        ? range.start <= p.start && p.end <= range.end
        : range.start < p.start && p.start < range.end);
      if (inside) {
        if (!wrappers[r]) {
          wrappers[r] = makeWrapper();
          frag.appendChild(wrappers[r]);
        }
        wrappers[r].appendChild(p.node);
      } else {
        frag.appendChild(p.node);
      }
    });
    while (root.firstChild) root.removeChild(root.firstChild);
    root.appendChild(frag);
    return wrappers.filter(Boolean).length;
  }

  /**
   * עוטפת כל קטע קוד פנימי של בלוק עברי (קטע ``ltr`` של ``innerFences``) ב-
   * ``<span class="rtl-code-ltr" dir="ltr">``, ומחזירה כמה קטעים נעטפו. בלוק
   * שאינו עברי, ובלוק עברי שאין בו קטע כזה — בלי גדר פנימית, או שכל הגדרות
   * הפנימיות שלו הן טקסט — לא משתנים בכלל. הכיוון, היישור והגלילה של העטיפה
   * מוגדרים ב-``markdown-enhanced.css``, שנטען מ-``base.html`` — ושלושת
   * הצרכנים הם עמודים שיורשים ממנו.
   *
   * **חייבת לרוץ אחרי ההדגשה**, בדיוק הפוך מ-``applyRtlIfHebrew``. ההדגשה
   * בונה את תוכן הבלוק מחדש מהטקסט שלו: ב-highlight.js 11.11.1
   * ``highlightElement`` קורא את ``textContent`` וכותב ``innerHTML``
   * (``lib/core.js``), וגם המסלול בלי שפה ב-``SafeHighlight.highlightBlock``
   * כותב ``innerHTML`` כשזוהתה שפה. עטיפה שנוספה לפני כן נמחקת. ההחלטה אם הבלוק עברי
   * נקראת מהמחלקה ``rtl-code`` שעל ה-``pre``, כלומר מ-``applyRtlIfHebrew``
   * שרצה לפני ההדגשה.
   *
   * **העטיפה גוזרת את הקטע מתוך ה-HTML שכבר נצבע, ולא צובעת מחדש**
   * (``wrapTextRanges``). הצבעים נשארים של הבלוק השלם, והעטיפה עובדת גם
   * כש-highlight.js לא נטען. ``textContent`` נשאר זהה תו בתו, וכפתורי
   * ההעתקה קוראים ממנו.
   *
   * **לא עוטפת פעמיים.** עטיפה שכבר קיימת בבלוק פירושה שהוא כבר טופל;
   * הצבעה מחדש מוחקת אותה, ואז הבלוק נעטף שוב.
   */
  function wrapInnerFences(block) {
    var pre = block && block.closest ? block.closest('pre') : null;
    if (!pre || !pre.classList.contains('rtl-code')) return 0;
    if (block.querySelector('.rtl-code-ltr')) return 0;
    var doc = block.ownerDocument;
    return wrapTextRanges(block, innerFenceRanges(block.textContent), function () {
      var wrapper = doc.createElement('span');
      wrapper.className = 'rtl-code-ltr';
      wrapper.setAttribute('dir', 'ltr');
      return wrapper;
    });
  }

  // ─── הערות ומחרוזות עבריות בתוך שורת קוד ───────────────────────────
  //
  // הכיוון ההפוך מ-``wrapInnerFences``: שם בלוק עברי מכיל קוד, כאן בלוק קוד
  // מכיל עברית. כל שורה בבלוק קוד היא פסקה משמאל לימין, ולכן הערה כמו
  // ``// הצורה המינימלית של צומת hast שהתוסף צריך`` מתפרקת לשני קטעים עבריים
  // משני צדי ``hast``, והם מסודרים משמאל לימין — בסדר הקריאה ההפוך. התיקון:
  // הגוף של ההערה או המחרוזת נעטף ב-``<span dir="rtl">``. גיליון הסגנון של
  // הדפדפן נותן לכל אלמנט עם ``dir`` את ``unicode-bidi: isolate`` (תקן HTML,
  // "Bidirectional text" בפרק ה-Rendering), ולכן הגוף מסודר מימין לשמאל בתוך
  // עצמו, והשורה סביבו לא זזה — בלי שורת CSS. הועבר מהבלוג של הפורטפוליו
  // (``client/src/lib/rtl-code-tokens.ts`` שם).
  //
  // **ההזחה והסימנים נשארים בחוץ.** עטיפה של הטוקן כולו נמדדה בבלוג ונפסלה:
  // ב-``dir="rtl"`` הרווחים של ההזחה עוברים לצד ימין, הערה מוזחת נדחפת לקצה
  // השמאלי, ו-``<!--``/``-->`` מתהפכים. ומאותה סיבה גם שלד המחרוזת נשאר
  // בחוץ — התחילית והגרש. ב-highlight.js (בניגוד ל-Shiki של הבלוג) התחילית
  // היא חלק מהטוקן: ``f"…"`` של פייתון, ``$@"…"`` של C#, ``r#"…"#`` של Rust
  // (נבדק ב-11.9.0 וב-11.11.1). בתוך העטיפה ה-``f`` של ``f"✅ הקובץ {name}
  // נשמר"`` היה מצויר בקצה הימני, אחרי הגרש הסוגר.

  // **סימני ההערה בתחילת שורה, לפי הסדר שבו הם נבדקים**: הטקסט, והאם התו
  // האחרון שלו יכול לחזור (``///``, ``##``, ``/**``, ``;;``). הרשימה של הבלוג
  // (``//``, ``#``, ``--``, ``/*``, ``*`` — סימן ההמשך בשורות של ``/* … *\/`` —
  // ``<!--``, ``"""``, ``'''``), ועוד הסימנים שהטוקן של highlight.js 11.11.1
  // פותח בהם בשפות שהרשימה של הבלוג לא כיסתה: ``;`` (``ini``, ``lisp``),
  // ``%`` (``erlang``, ``matlab``, ``latex``), ``!`` (``fortran``), ``'`` ו-
  // ``REM`` (``vbnet``, בלי הבחנה בין אותיות גדולות לקטנות, ורק כשאחריו רווח —
  // ``([\t ]|^)REM(?=\s)`` ב-``vbnet.js``). סימן שאינו כאן נשאר בתוך העטיפה,
  // ובכיוון מימין לשמאל הוא מצויר בקצה הימני של העברית.
  var COMMENT_OPENERS = [
    { text: '//', repeats: true },
    { text: '#', repeats: true },
    { text: '--' },
    { text: '/*', repeats: true },
    { text: '*' },
    { text: '<!--' },
    { text: '"""' },
    { text: "'''" },
    { text: ';', repeats: true },
    { text: '%', repeats: true },
    { text: '!', repeats: true },
    { text: "'" },
    { text: 'REM', word: true },
  ];
  var COMMENT_CLOSERS = ['*/', '-->', '"""', "'''"];

  // שלד המחרוזת: בפתיחה — תחילית צמודה וגרש (``f"``, ``rb'``, ``$@"``,
  // ``u8"``, ``r#"``, ``"""``), ובסגירה — הגרש ו-``#`` של Rust. רק בשורה
  // הראשונה של הטוקן ובאחרונה שלו: גרש בתחילת שורה **באמצע** מחרוזת רב-שורתית
  // הוא תוכן ולא סימן. שני הביטויים מעוגנים לקצה ואין בהם חזרה חופפת, ולכן
  // הם ליניאריים.
  var STRING_OPEN = /^[A-Za-z0-9@$#]*(?:"""|'''|"|'|`)/;
  var STRING_CLOSE = /(?:"""|'''|"|'|`)#*$/;

  // **מחרוזת raw של C ו-C++**: ``R"tag(`` … ``)tag"``, וה-tag חלק מהשלד. אותו
  // ביטוי כמו הפתיחה ב-``cpp.js`` וב-``c.js`` של highlight.js 11.11.1, והסגירה
  // שם היא אותו tag (``END_SAME_AS_BEGIN``). בתוך העטיפה tag שאינו סימטרי
  // במראה, כמו ``-=``, היה מצויר בסדר ההפוך — נמדד, ו-
  // ``tests/test_rtl_code_tokens_browser.py`` בודק את זה.
  var CPP_RAW_OPEN = /^(?:u8?|U|L)?R"([^()\\ ]{0,16})\(/;

  function isSpace(ch) {
    return /\s/.test(ch);
  }

  // אורך סימן הפתיחה של הערה ב-``line[at]``, או אפס.
  function commentOpenerLength(line, at) {
    for (var k = 0; k < COMMENT_OPENERS.length; k++) {
      var opener = COMMENT_OPENERS[k];
      var len = opener.text.length;
      var found = opener.word
        ? line.slice(at, at + len).toUpperCase() === opener.text && isSpace(line.charAt(at + len))
        : line.slice(at, at + len) === opener.text;
      if (!found) continue;
      if (opener.repeats) {
        var last = opener.text.charAt(len - 1);
        while (line.charAt(at + len) === last) len++;
      }
      return len;
    }
    return 0;
  }

  /**
   * הגוף של שורה בטוקן, ``{start, end}`` בתוך השורה: בלי הרווחים בשני הקצוות,
   * ובהערה גם בלי סימן הפתיחה וסימן הסגירה.
   *
   * **סריקה של תווים ולא ביטוי רגולרי**, מאותה סיבה כמו ``fenceOpening``. הביטוי
   * של הבלוג (גוף עצל, ואחריו ``\s*`` משני צדי סימן סגירה אופציונלי) ניסה כל
   * חלוקה של רצף רווחים בין שני ה-``\s*``, בכל מקום שהגוף נעצר בו — זמן שגדל
   * בחזקה שלישית באורך הרצף, והערה עם כמה אלפי רווחים תקעה את העמוד לשניות
   * ארוכות. כאן כל תו נקרא פעם אחת לכל היותר מכל כיוון, ו-
   * ``tests/rtl-code-tokens.test.js`` בודק שהזמן גדל ליניארית.
   */
  function lineBody(line, isComment) {
    var start = 0;
    var end = line.length;
    while (start < end && isSpace(line.charAt(start))) start++;
    if (isComment) {
      start += commentOpenerLength(line, start);
      while (start < end && isSpace(line.charAt(start))) start++;
    }
    while (end > start && isSpace(line.charAt(end - 1))) end--;
    if (isComment) {
      for (var k = 0; k < COMMENT_CLOSERS.length; k++) {
        var closer = COMMENT_CLOSERS[k];
        if (end - closer.length >= start && line.slice(end - closer.length, end) === closer) {
          end -= closer.length;
          break;
        }
      }
      while (end > start && isSpace(line.charAt(end - 1))) end--;
    }
    return { start: start, end: end };
  }

  var HEBREW_TOKENS = '.hljs-comment, .hljs-string';

  /**
   * טווחי הגוף שצריך לעטוף בטקסט של טוקן אחד: ``{start, end}`` לכל שורה,
   * ``end`` לא כלול. הטוקן של highlight.js יכול להימשך על כמה שורות (``/* … *\/``,
   * docstring), וכל שורה היא פסקה נפרדת, ולכן ההחלטה וההפרדה הן לכל שורה.
   *
   * שורה נעטפת כשהגוף שלה ``isHebrewMajority`` (הסף הוא ``HEBREW_THRESHOLD``),
   * **ויש בו יותר ממילה אחת.** מילה בודדת אין לה סדר לתקן, ועטיפה שלה רק מזיקה:
   * highlight.js צובע ערך YAML בלי גרשיים כטוקן לכל מילה (``name: ערך בעברית``
   * הוא שני טוקנים), ואלמנט מבודד נחשב בשורה כתו ניטרלי. שתי מילים עבריות
   * צמודות מסודרות היום מימין לשמאל כרצף אחד; כל אחת עטופה לבד — הן מתהפכות.
   * נמדד בכרומיום, ו-``tests/test_rtl_code_tokens_browser.py`` בודק את זה.
   */
  function hebrewTokenRanges(text, isString) {
    var lines = String(text == null ? '' : text).split('\n');
    var ranges = [];
    var offset = 0;
    var rawCloser = null;
    lines.forEach(function (line, i) {
      var lineStart = offset;
      offset += line.length + 1;
      var lead = 0;
      var rest = line;
      if (isString) {
        if (i === 0) {
          var raw = CPP_RAW_OPEN.exec(rest);
          var open = raw || STRING_OPEN.exec(rest);
          if (raw) rawCloser = ')' + raw[1] + '"';
          if (open) { lead = open[0].length; rest = rest.slice(lead); }
        }
        if (i === lines.length - 1) {
          if (rawCloser) {
            if (rest.slice(-rawCloser.length) === rawCloser) rest = rest.slice(0, rest.length - rawCloser.length);
          } else {
            var close = STRING_CLOSE.exec(rest);
            if (close) rest = rest.slice(0, close.index);
          }
        }
      }
      var span = lineBody(rest, !isString);
      var body = rest.slice(span.start, span.end);
      if (!body || !/\s/.test(body) || !isHebrewMajority(body)) return;
      var start = lineStart + lead + span.start;
      ranges.push({ start: start, end: start + body.length });
    });
    return ranges;
  }

  /**
   * עוטפת ב-``<span dir="rtl">`` את הגוף של כל הערה ומחרוזת עבריות בבלוק קוד
   * שכבר נצבע, ומחזירה כמה עטיפות נוספו. ``SafeHighlight.highlightBlock`` קורא
   * לה אחרי הצביעה, ולכן כל מי שמדגיש דרכו מקבל אותה.
   *
   * **בלוק ``pre.rtl-code`` מדולג** — הוא כבר כולו מימין לשמאל
   * (``applyRtlIfHebrew``), והקוד שבתוכו מטופל ב-``wrapInnerFences``.
   *
   * **רק הטוקן החיצוני.** מחרוזת בתוך ``{…}`` של f-string היא טוקן בתוך טוקן,
   * והיא כבר בתוך העטיפה של החיצוני.
   *
   * **גוזרת מתוך ה-HTML הצבוע, ולא צובעת מחדש** (``wrapTextRanges``, כמו
   * ``wrapInnerFences``): בתוך טוקן יכולים להיות אלמנטים צבועים
   * (``hljs-doctag`` על ``TODO:``, ``hljs-subst`` על ``{name}``), וכל אחד
   * שחוצה את הגבול מפוצל. ``textContent`` נשאר זהה תו בתו, ולכן כפתורי
   * ההעתקה — שקוראים ממנו — מעתיקים בדיוק את המקור.
   *
   * **בטוחה להרצה חוזרת:** טוקן שכבר יש בו ``span[dir="rtl"]`` מדולג.
   */
  function isolateHebrewTokens(block) {
    if (!block || !block.querySelectorAll) return 0;
    if (block.closest && block.closest('pre.rtl-code')) return 0;
    var doc = block.ownerDocument;
    var makeWrapper = function () {
      var wrapper = doc.createElement('span');
      wrapper.setAttribute('dir', 'rtl');
      return wrapper;
    };
    var count = 0;
    Array.prototype.forEach.call(block.querySelectorAll(HEBREW_TOKENS), function (token) {
      var outer = token.parentElement && token.parentElement.closest(HEBREW_TOKENS);
      if (outer && block.contains(outer)) return;
      if (token.querySelector('span[dir="rtl"]')) return;
      var ranges = hebrewTokenRanges(token.textContent, token.classList.contains('hljs-string'));
      count += wrapTextRanges(token, ranges, makeWrapper);
    });
    return count;
  }

  /**
   * **שם קובץ עברי שהדפדפן היה מציג עם הסיומת באמצע** — ``{stem, extension}`` או ``null``. ההחלטה וההסבר גרים ב-
   * ``utils/file-name.js`` (``FileName.parts``), כי היא משותפת לקוד בשורה ולשמות הקבצים בממשק, ויש לה תאום בשרת.
   * **היעדר ``window.FileName`` הוא היעדר יכולת סטטי:** ``base.html`` טוען אותו ב-``<head>`` של כל עמוד, ועמוד הייצוא
   * המעוצב טוען אותו בעצמו. בלעדיו הקוד מוצג בלי פירוק, ונרשמת אזהרה אחת בקונסול — כדי שתבנית שנשכחה תיראה.
   */
  var warnedNoFileName = false;
  function fileNameParts(text) {
    var api = typeof window !== 'undefined' ? window.FileName : null;
    if (api && typeof api.parts === 'function') return api.parts(text);
    if (!warnedNoFileName && typeof console !== 'undefined') {
      warnedNoFileName = true;
      console.warn('rtl-code: window.FileName חסר (utils/file-name.js לא נטען) — שמות קבצים בקוד בשורה מוצגים בלי פירוק');
    }
    return null;
  }

  /**
   * ממלא אלמנט של קוד בשורה בטקסט שלו, עם הכיוון שלו: שם קובץ ש-``fileNameParts`` מפרק מקבל ``dir="rtl"``, את
   * ``stem + '.'`` כטקסט ואת הסיומת ב-``<bdi>``; כל קוד אחר מקבל ``dir="auto"`` ואת הטקסט כמו שהוא. **הבנייה
   * לצמתים כתובה כאן פעם אחת** — הפתק (``_appendInlineSegments``) והכרטיס של פתק (``fillTitle`` ב-``note-cards.js``)
   * עוברים דרכה. תוסף ה-markdown-it (``md-auto-dir-plugin.js``) בונה את אותו HTML כמחרוזת, וטסט ההשוואה ב-
   * ``tests/sticky-notes-target.test.js`` מוודא שהפתק והמסמך מסכימים. ``textContent`` בלבד: הטקסט הוא מה שהמשתמש כתב.
   */
  function fillInlineCode(el, text) {
    var s = text == null ? '' : String(text);
    var parts = fileNameParts(s);
    if (!parts) {
      el.setAttribute('dir', 'auto');
      el.textContent = s;
      return el;
    }
    var doc = el.ownerDocument || document;
    el.textContent = '';
    el.setAttribute('dir', 'rtl');
    el.appendChild(doc.createTextNode(parts.stem + '.'));
    var extension = doc.createElement('bdi');
    extension.textContent = parts.extension;
    el.appendChild(extension);
    return el;
  }

  if (typeof window !== 'undefined') {
    window.RtlCode = {
      isHebrewMajority: isHebrewMajority,
      hasExplicitLanguage: hasExplicitLanguage,
      hasExplicitLanguageName: hasExplicitLanguageName,
      applyRtlIfHebrew: applyRtlIfHebrew,
      fenceOpening: fenceOpening,
      innerFences: innerFences,
      innerFenceRanges: innerFenceRanges,
      wrapInnerFences: wrapInnerFences,
      hebrewTokenRanges: hebrewTokenRanges,
      isolateHebrewTokens: isolateHebrewTokens,
      fillInlineCode: fillInlineCode,
      // **עותק קפוא ולא הרשימה עצמה.** הרג'קסים כבר נבנו ממנה, ולכן שינוי
      // של המערך מבחוץ לא היה משנה אף החלטה — רק גורם לה להיראות אחרת
      // ממה שנאכף. החשיפה קיימת כדי שעמוד המשתמש, שמונה את השמות, ייבדק
      // מולה בטסט במקום להיסחף בשקט.
      plainLanguageNames: Object.freeze(PLAIN_LANGUAGE_NAMES.slice()),
    };
  }
})();
