/**
 * זיהוי ויישור RTL לבלוקי קוד עם תוכן בעברית.
 * משותף ל-live-preview, repo-browser ו-md_preview.
 */
(function () {
  'use strict';

  var HEBREW_THRESHOLD = 0.3;

  function isHebrewMajority(text) {
    if (!text) return false;
    var cleaned = text.replace(/\s+/g, '');
    if (cleaned.length === 0) return false;
    var hebrewCount = 0;
    var letterCount = 0;
    for (var i = 0; i < cleaned.length; i++) {
      var c = cleaned.charCodeAt(i);
      if (c >= 0x0590 && c <= 0x05FF) {
        hebrewCount++;
        letterCount++;
      } else if ((c >= 0x0041 && c <= 0x005A) || (c >= 0x0061 && c <= 0x007A)) {
        // אותיות לטיניות (A-Z, a-z)
        letterCount++;
      }
      // סימנים, חיצים, מספרים וסימני פיסוק לא נספרים – כך הם לא מדללים את היחס
    }
    if (letterCount === 0) return false;
    return hebrewCount / letterCount > HEBREW_THRESHOLD;
  }

  /**
   * שמות שאינם שפת תכנות אמיתית. בלוק שנושא אחד מהם נחשב "בלי שפה",
   * ולכן הוא עדיין מועמד ליישור לימין.
   *
   * **מקור אחד לשתי צורות של אותה שאלה.** לצרכן אחד יש אלמנט DOM עם
   * ``class="language-…"`` (תצוגת המסמכים), ולצרכן אחר יש את שם השפה
   * הגולמי שכבר נגזר משורת הגדר (הפתקים בונים ``div`` ולא ``pre``,
   * ולכן אין להם מחלקה לקרוא). הרשימה נכתבת כאן פעם אחת והרג'קס נבנה
   * ממנה, כדי ששני הצרכנים לא יוכלו לענות תשובות שונות על אותו קלט.
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
  // הבלוק, ורק קוד — קטע שמתחיל בגדר פנימית ונגמר בגדר הסוגרת שלה — הוא
  // משמאל לימין. כלל לפי האות החזקה הראשונה (``unicode-bidi: plaintext``)
  // נבדק ב-Markdown-Docs ונפסל: ב-``- `editor.background` → רקע המסמך``
  // האות הראשונה לועזית, והשורה קפצה שמאלה באמצע רשימה עברית. זו אותה
  // הכרעה שמתועדת ב-``sticky-notes.css`` ליד ``.sticky-md-code-block.rtl-code``.

  /**
   * האם השורה פותחת גדר, ובאיזו: ``{marker, length}`` או ``null``.
   *
   * **הכלל של CommonMark 0.31.2, סעיף 4.5, כפי ש-markdown-it 14.1.0 מממש
   * אותו** (``rules_block/fence.mjs`` — הפרסר שמרנדר את המסמכים כאן): שלושה
   * גרשיים או שלוש טילדות לפחות, ובגדר של גרשיים השארית אינה מכילה גרש
   * (דוגמה 145: השורה "``` aa ```" היא קוד בשורה, לא גדר). בגדר של טילדות
   * השארית יכולה להכיל גרשיים (דוגמה 146).
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
   * תו נקרא פעם אחת.
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
    return { marker: marker, length: i - start };
  }

  // סוגרת רק שורה שכולה אותו תו, באורך שלפחות שווה לפותחת, ואחריו רק
  // רווחים או טאבים. ```` אינה נסגרת ב-``` (דוגמה 124), ושורה עם שם שפה
  // אינה סוגרת (דוגמה 147). אותו כלל כמו לולאת הסגירה ב-``fence.mjs``, חוץ
  // מההזחה — מאותה סיבה כמו ב-``fenceOpening``.
  function closesFence(line, open) {
    var s = String(line);
    var i = 0;
    while (i < s.length && (s[i] === ' ' || s[i] === '\t')) i++;
    var start = i;
    while (i < s.length && s[i] === open.marker) i++;
    if (i - start < open.length) return false;
    while (i < s.length && (s[i] === ' ' || s[i] === '\t')) i++;
    return i === s.length;
  }

  /**
   * השורה שסוגרת את הגדר שנפתחה ב-``lines[start]``, או ``lines.length``
   * כשאינה נסגרת — ואז הגדר נמשכת עד הסוף, כמו בגדר שלא נסגרה ב-markdown-it.
   * ``open`` הוא מה ש-``fenceOpening`` החזירה על אותה שורה.
   */
  function fenceEnd(lines, start, open) {
    for (var i = start + 1; i < lines.length; i++) {
      if (closesFence(lines[i], open)) return i;
    }
    return lines.length;
  }

  /**
   * מחלקת את הטקסט של בלוק לקטעים רציפים של שורות: ``{ltr, from, to}``,
   * כש-``to`` אינו כלול. קטע ``ltr`` מתחיל בגדר פותחת ונגמר בגדר הסוגרת
   * שלה, **כולל שתי שורות הגדר**, או בסוף הטקסט כשהגדר לא נסגרה. כל השאר
   * בקטעים שאינם ``ltr``, ולכן שורות ריקות סביב הגדר נשארות בהם — לא
   * נעלמות ולא מוכפלות.
   */
  function innerFences(text) {
    var lines = String(text == null ? '' : text).split('\n');
    var parts = [];
    function take(ltr, from, to) {
      if (to > from) parts.push({ ltr: ltr, from: from, to: to });
    }
    var from = 0;
    var i = 0;
    while (i < lines.length) {
      var open = fenceOpening(lines[i]);
      if (!open) { i++; continue; }
      var last = Math.min(fenceEnd(lines, i, open), lines.length - 1);
      take(false, from, i);
      take(true, i, last + 1);
      i = from = last + 1;
    }
    take(false, from, lines.length);
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

  function childIndex(node) {
    var i = 0;
    while ((node = node.previousSibling)) i++;
    return i;
  }

  function nodeLength(node) {
    return node.nodeType === 3 ? node.data.length : node.childNodes.length;
  }

  // נקודה בתוך ``root`` לפי מיקום תו ב-``textContent`` שלו. נקודת התחלה
  // יושבת בצומת שהתו **מתחיל** בו, ונקודת סוף בצומת שהתו שלפניה **נגמר**
  // בו. אחר כך הנקודה מטפסת כל עוד היא בקצה של אלמנט: כך אלמנט צבוע
  // שמתחיל בדיוק בגבול עובר לתוך הקטע שלם, במקום להשאיר מאחור קליפה ריקה.
  function boundaryPoint(root, offset, isEnd) {
    var walker = root.ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    var seen = 0;
    var node;
    var point = null;
    while ((node = walker.nextNode())) {
      var len = node.data.length;
      if (isEnd ? offset <= seen + len : offset < seen + len) {
        point = { node: node, offset: offset - seen };
        break;
      }
      seen += len;
    }
    if (!point) point = { node: root, offset: root.childNodes.length };
    while (point.node !== root) {
      var parent = point.node.parentNode;
      if (!isEnd && point.offset === 0) {
        point = { node: parent, offset: childIndex(point.node) };
      } else if (isEnd && point.offset === nodeLength(point.node)) {
        point = { node: parent, offset: childIndex(point.node) + 1 };
      } else {
        break;
      }
    }
    return point;
  }

  /**
   * עוטפת כל קטע קוד פנימי של בלוק עברי ב-``<span class="rtl-code-ltr"
   * dir="ltr">``, ומחזירה כמה קטעים נעטפו. בלוק שאינו עברי, ובלוק עברי
   * בלי גדר פנימית, לא משתנים בכלל. הכיוון, היישור והגלילה של העטיפה
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
   * **העטיפה גוזרת את הקטע מתוך ה-HTML שכבר נצבע, ולא צובעת מחדש.**
   * ``Range.extractContents`` מפצל בעצמו כל אלמנט צבוע שחוצה את הגבול —
   * חצי נשאר בחוץ וחצי עובר לעטיפה — ולכן אין צורך לדעת אילו טוקנים
   * highlight.js פורש על כמה שורות, ואין צורך לדעת באיזו שפה הבלוק נצבע.
   * הצבעים נשארים של הבלוק השלם, והעטיפה עובדת גם כש-highlight.js לא נטען.
   * ``textContent`` נשאר זהה תו בתו, וכפתורי ההעתקה קוראים ממנו.
   *
   * **לא עוטפת פעמיים.** עטיפה שכבר קיימת בבלוק פירושה שהוא כבר טופל;
   * הצבעה מחדש מוחקת אותה, ואז הבלוק נעטף שוב.
   */
  function wrapInnerFences(block) {
    var pre = block && block.closest ? block.closest('pre') : null;
    if (!pre || !pre.classList.contains('rtl-code')) return 0;
    if (block.querySelector('.rtl-code-ltr')) return 0;
    var ranges = innerFenceRanges(block.textContent);
    var doc = block.ownerDocument;
    ranges.forEach(function (r) {
      var start = boundaryPoint(block, r.start, false);
      var end = boundaryPoint(block, r.end, true);
      var range = doc.createRange();
      range.setStart(start.node, start.offset);
      range.setEnd(end.node, end.offset);
      var wrapper = doc.createElement('span');
      wrapper.className = 'rtl-code-ltr';
      wrapper.setAttribute('dir', 'ltr');
      wrapper.appendChild(range.extractContents());
      range.insertNode(wrapper);
    });
    return ranges.length;
  }

  if (typeof window !== 'undefined') {
    window.RtlCode = {
      isHebrewMajority: isHebrewMajority,
      hasExplicitLanguage: hasExplicitLanguage,
      hasExplicitLanguageName: hasExplicitLanguageName,
      applyRtlIfHebrew: applyRtlIfHebrew,
      fenceOpening: fenceOpening,
      fenceEnd: fenceEnd,
      innerFences: innerFences,
      innerFenceRanges: innerFenceRanges,
      wrapInnerFences: wrapInnerFences,
      // **עותק קפוא ולא הרשימה עצמה.** הרג'קסים כבר נבנו ממנה, ולכן שינוי
      // של המערך מבחוץ לא היה משנה אף החלטה — רק גורם לה להיראות אחרת
      // ממה שנאכף. החשיפה קיימת כדי שעמוד המשתמש, שמונה את השמות, ייבדק
      // מולה בטסט במקום להיסחף בשקט.
      plainLanguageNames: Object.freeze(PLAIN_LANGUAGE_NAMES.slice()),
    };
  }
})();
