/**
 * utils/file-name.js — שם קובץ בשורה עברית: הסיומת בקצה השמאלי, והשם מבודד מהטקסט שסביבו.
 *
 * **מה שבור בלי זה.** ב-``מדריך-תצוגת-Markdown-RTL.md`` הנקודה יושבת בין שתי אותיות לטיניות, ואלגוריתם הכיווניות
 * מדביק אותה אליהן: ``Markdown-RTL.md`` הופך לגוש אחד משמאל לימין, והסיומת נמצאת בקצה הימני שלו — צמודה לעברית,
 * באמצע השם. ובהקשר שמאל-לימין (כרטיס תוצאת חיפוש, הכותרות של שני הצדדים ב-``/compare``) נשבר גם שם שנגמר בעברית:
 * ב-``ערכות.md`` הסיומת יוצאת מימין לשם. ``tests/test_file_name_display_browser.py`` מודד את שני המקרים בכרומיום.
 *
 * **מה עושים.** ``element`` בונה את השם כ-``<bdi>`` אחד, שנכנס **בתוך** האלמנט הקיים (כך שה-CSS שלו — חיתוך בשלוש
 * נקודות, ``line-clamp`` — נשמר):
 *
 * - שם ש-``parts`` מפרק: ``<bdi dir="rtl">STEM.<bdi>EXT</bdi></bdi>`` — השם מימין לשמאל, והסיומת מבודדת בקצה
 *   השמאלי. זה המבנה של קוד בשורה (``RtlCode.fillInlineCode`` ב-``utils/rtl-code.js``), רק כאלמנט פנימי ולא על
 *   האלמנט עצמו: על בלוק, ``dir`` היה משנה גם את היישור שלו.
 * - כל שם אחר: ``<bdi dir="auto">NAME</bdi>`` — הכיוון לפי האות החזקה הראשונה, והשם מבודד. בהקשר ימין-לשמאל זה לא
 *   משנה את הסדר של שם שמתחיל באות, ומתקן שם שמתחיל בסימן, כמו ``_draft.md``. ``dir="auto"`` כתוב במפורש, ולא
 *   נשען על ברירת המחדל של ``bdi``.
 *
 * הטקסט עצמו לא משתנה — אין תווים נסתרים, ו-``textContent`` נשאר השם תו בתו — ולכן העתקה מחזירה את השם בדיוק, וקוד
 * שמעתיק את הטקסט ל-``title`` ממשיך לעבוד. **בלי ``innerHTML``:** השם הוא קלט של משתמש, והוא נכנס רק דרך
 * ``createElement`` ו-``textContent``. מקום שבונה שורה כמחרוזת בונה אותה בלי השם, וממלא את השם אחר כך דרך ``fill``.
 *
 * **מתי מפרקים** (``parts``) — רק כשכל אלה מתקיימים, כלומר רק כשהדפדפן באמת היה מדביק את הסיומת לשם:
 *
 * - בסוף יש נקודה ואחריה סיומת: אחת עד עשר אותיות או ספרות לטיניות (``EXTENSION_RE``).
 * - לפני הנקודה יש אות עברית.
 * - בקטע שבין האות העברית האחרונה לנקודה יש אות לטינית, ואין נקודה — ``Q3`` ב-``Report-דוח-Q3.md``.
 * - אין בטקסט לוכסן: נתיב נשאר כמו שהוא.
 *
 * מה נשאר בלי פירוק, ולמה — החלטה של המשתמש מנובמבר 2026 — כתוב בסעיף ``markdown-auto-dir`` ב-
 * ``docs/markdown_style_guide.rst``.
 *
 * **"עברית" ו"לטינית" הן טבלאות, ולא ``\p{Script=…}``.** לשרת יש תאום בפייתון (``webapp/file_name_display.py``),
 * לעמודים שהוא בונה, ובספרייה הסטנדרטית של פייתון אין את מאפיין הכתב של יוניקוד. שתי הטבלאות כאן ושם זהות, ולכן
 * שני הצדדים מחליטים אותו דבר — גם בדפדפן או ב-Node שמכירים גרסת יוניקוד אחרת. ``HEBREW_LETTERS`` ו-``LATIN_LETTERS``
 * הם האותיות (``\p{L}``) שבכתב העברי ובכתב הלטיני, כפי שהן ב-Node 22.23.4 (יוניקוד 17.0), נכון ל-14.11.2026.
 * ``tests/test_file_name_display.py`` מריץ את שני המימושים על כל תו ביוניקוד ומשווה, ו-``tests/file-name.test.js``
 * בודק שהטבלאות מכסות את כל מה ש-Node שמריץ אותו מכיר כעברית או כלטינית — וכשלא, מדפיס את הטבלה המעודכנת.
 *
 * **איפה זה נטען.** ב-``<head>`` של ``base.html``, בלי ``defer``: מודאל "קבצים אחרונים" יושב בכל עמוד, ו-
 * ``md_preview.html`` טוען את ``utils/rtl-code.js`` (שנשען על ``parts``) בתוך בלוק התוכן. עמוד הייצוא המעוצב
 * (``export/styled_document.html``) אינו יורש מ-``base.html``, ולכן טוען אותו בעצמו.
 */
(function () {
  'use strict';

  //: אותיות הכתב העברי — ``(?=\p{L})\p{Script=Hebrew}`` ב-Node 22.23.4 (יוניקוד 17.0). התאום: ``HEBREW_LETTERS``
  //: ב-``webapp/file_name_display.py``.
  var HEBREW_LETTERS = [
    [0x05D0, 0x05EA], [0x05EF, 0x05F2], [0xFB1D, 0xFB1D], [0xFB1F, 0xFB28], [0xFB2A, 0xFB36], [0xFB38, 0xFB3C],
    [0xFB3E, 0xFB3E], [0xFB40, 0xFB41], [0xFB43, 0xFB44], [0xFB46, 0xFB4F],
  ];

  //: אותיות הכתב הלטיני — ``(?=\p{L})\p{Script=Latin}`` ב-Node 22.23.4 (יוניקוד 17.0). התאום: ``LATIN_LETTERS``
  //: ב-``webapp/file_name_display.py``.
  var LATIN_LETTERS = [
    [0x0041, 0x005A], [0x0061, 0x007A], [0x00AA, 0x00AA], [0x00BA, 0x00BA], [0x00C0, 0x00D6], [0x00D8, 0x00F6],
    [0x00F8, 0x02B8], [0x02E0, 0x02E4], [0x1D00, 0x1D25], [0x1D2C, 0x1D5C], [0x1D62, 0x1D65], [0x1D6B, 0x1D77],
    [0x1D79, 0x1DBE], [0x1E00, 0x1EFF], [0x2071, 0x2071], [0x207F, 0x207F], [0x2090, 0x209C], [0x212A, 0x212B],
    [0x2132, 0x2132], [0x214E, 0x214E], [0x2183, 0x2184], [0x2C60, 0x2C7F], [0xA722, 0xA787], [0xA78B, 0xA7DC],
    [0xA7F1, 0xA7FF], [0xAB30, 0xAB5A], [0xAB5C, 0xAB64], [0xAB66, 0xAB69], [0xFB00, 0xFB06], [0xFF21, 0xFF3A],
    [0xFF41, 0xFF5A], [0x10780, 0x10785], [0x10787, 0x107B0], [0x107B2, 0x107BA], [0x1DF00, 0x1DF1E],
    [0x1DF25, 0x1DF2A],
  ];

  //: נקודה אחרונה ואחריה סיומת עד סוף הטקסט. ``$`` בלי הדגל ``m`` הוא סוף הקלט בלבד; התאום בפייתון כותב ``\Z``,
  //: כי שם ``$`` מתאים גם לפני ``\n`` אחרון.
  var EXTENSION_RE = /\.([A-Za-z0-9]{1,10})$/;

  function inRanges(ranges, codePoint) {
    var lo = 0;
    var hi = ranges.length - 1;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      if (codePoint < ranges[mid][0]) hi = mid - 1;
      else if (codePoint > ranges[mid][1]) lo = mid + 1;
      else return true;
    }
    return false;
  }

  /**
   * השם והסיומת של שם קובץ שהדפדפן היה מציג עם הסיומת באמצע — ``{stem, extension}`` — או ``null``.
   * עובר על התווים לפי נקודות קוד (``for…of``), כמו התאום בפייתון.
   */
  function parts(name) {
    var s = name == null ? '' : String(name);
    if (/[/\\]/.test(s)) return null;
    var m = EXTENSION_RE.exec(s);
    if (!m) return null;
    var stem = s.slice(0, m.index);
    var chars = Array.from(stem);
    var lastHebrew = -1;
    for (var i = chars.length - 1; i >= 0; i--) {
      if (inRanges(HEBREW_LETTERS, chars[i].codePointAt(0))) { lastHebrew = i; break; }
    }
    if (lastHebrew < 0) return null;
    var hasLatin = false;
    for (var j = lastHebrew + 1; j < chars.length; j++) {
      if (chars[j] === '.') return null;
      if (inRanges(LATIN_LETTERS, chars[j].codePointAt(0))) hasLatin = true;
    }
    if (!hasLatin) return null;
    return { stem: stem, extension: m[1] };
  }

  /** ה-``<bdi>`` של השם — ראו את ההסבר בראש הקובץ. ``doc`` הוא המסמך שבו נבנה האלמנט (ברירת מחדל: ``document``). */
  function element(name, doc) {
    var d = doc || document;
    var s = name == null ? '' : String(name);
    var split = parts(s);
    var outer = d.createElement('bdi');
    if (!split) {
      outer.setAttribute('dir', 'auto');
      outer.textContent = s;
      return outer;
    }
    outer.setAttribute('dir', 'rtl');
    outer.appendChild(d.createTextNode(split.stem + '.'));
    var extension = d.createElement('bdi');
    extension.textContent = split.extension;
    outer.appendChild(extension);
    return outer;
  }

  /** מחליף את התוכן של ``el`` בשם הקובץ (``element``). מחזיר את ``el``. */
  function fill(el, name) {
    el.textContent = '';
    el.appendChild(element(name, el.ownerDocument || document));
    return el;
  }

  if (typeof window !== 'undefined') {
    window.FileName = Object.freeze({
      parts: parts,
      element: element,
      fill: fill,
      // **עותקים קפואים**, לטסטים שמשווים את הטבלאות ל-``\p{Script=…}`` של ה-Node שמריץ אותם. שינוי שלהם מבחוץ
      // לא היה משנה אף החלטה — ``parts`` קורא את המקור.
      HEBREW_LETTERS: Object.freeze(HEBREW_LETTERS.map(function (r) { return Object.freeze(r.slice()); })),
      LATIN_LETTERS: Object.freeze(LATIN_LETTERS.map(function (r) { return Object.freeze(r.slice()); })),
    });
  }
})();
