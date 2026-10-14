/**
 * זמן יחסי לתצוגה ("לפני 20 דק׳", "אתמול", "לפני שבועיים") — מקור אחד לצד הלקוח.
 *
 * משותף לחלונית השרשורים בפתקים (``sticky-notes.js``), לרשימת הקבצים האחרונים
 * (``base.html``) ולהיסטוריית הקומיטים בדפדפן הריפו (``repo-history.js``). לפני
 * הקובץ הזה היו שני עותקים כתובים ביד, והם כבר נבדלו: האחד ספר עד שנים והשני
 * נעצר בימים ("לפני 400 ימים"), ושניהם אמרו "לפני 1 שעות" — כי עברית אינה
 * מוסיפה "1" ליחיד, ואף אחד מהם לא ידע את זה (R6).
 *
 * **המילים מגיעות מהדפדפן, לא מכאן.** ``Intl.RelativeTimeFormat`` יודע יחיד, זוגי
 * ורבים בעברית ("לפני שעה", "לפני שעתיים", "לפני 3 שע׳"), ואין בקובץ אף מילה
 * עברית מוקלדת שאפשר לשכוח לעדכן. מקור: MDN, ‏``Intl.RelativeTimeFormat()``
 * constructor — האפשרויות ``numeric`` (``always`` / ``auto``) ו-``style``.
 *
 * **הבחירות כאן נמדדו בכרומיום 141 (אוקטובר 2026), ולא הונחו:**
 *
 * - ``numeric: 'always'`` ולא ``'auto'``. עם ``auto`` שלפני יומיים יוצא
 *   "שלשום", ושבוע אחד יוצא "השבוע שעבר" — כלומר שבוע **בלוח השנה**, ולא "לפני
 *   שבעה ימים". ``always`` נותן "לפני יומיים" (מה שהעיצוב מראה), ועדיין "אתמול"
 *   ליום אחד.
 * - ``style: 'short'`` לשניות, דקות, שעות וימים — "לפני 20 דק׳", כמו בעיצוב.
 *   **אבל ``long`` לשבועות, חודשים ושנים:** בקצר שבוע אחד יוצא "לפני שב׳", ובארוך
 *   "לפני שבוע". (וביום ההפך: בארוך יום אחד יוצא "לפני יום 1", ובקצר "אתמול".)
 * - פחות מדקה הוא ``'עכשיו'`` — ``format(0, 'second')`` של ``numeric: 'auto'``.
 *   ב-``always`` אפס יוצא "בעוד 0 שנ׳".
 *
 * **הצורה המקוצרת** (``compact``) היא של חלונית צרה בפתק צר: "20 דק׳" בלי
 * "לפני". היא חלה רק על דקות ושעות, מ-``Intl.NumberFormat`` עם ``style: 'unit'``.
 * מיום ומעלה היא זהה לרגילה: יחידת "יום" לבדה יוצאת "יום" (בלי "לפני" זו כבר
 * אינה שעה שעברה), ושבוע אחד יוצא "שבוע 1".
 *
 * נטען גלובלית מ-``base.html``, ליד ``utils/size-format.js``.
 */
(function () {
  'use strict';

  if (typeof window === 'undefined') return;

  var SECOND = 1000;
  var MINUTE = 60 * SECOND;
  var HOUR = 60 * MINUTE;
  var DAY = 24 * HOUR;
  var WEEK = 7 * DAY;
  // חודש ושנה **ממוצעים**, ולא לפי לוח השנה. אותם ספים כמו שהיו ב-
  // ``repo-history.js`` (30 ו-365 ימים), כדי שהמעבר לא יזיז אף תווית שם.
  var MONTH = 30 * DAY;
  var YEAR = 365 * DAY;

  /** הסולם: עד איזה מרחק כל יחידה חלה, ובאיזה סגנון היא נכתבת (ראו למעלה). */
  var SCALE = Object.freeze([
    Object.freeze({ below: HOUR, unit: 'minute', size: MINUTE, style: 'short' }),
    Object.freeze({ below: DAY, unit: 'hour', size: HOUR, style: 'short' }),
    Object.freeze({ below: WEEK, unit: 'day', size: DAY, style: 'short' }),
    Object.freeze({ below: MONTH, unit: 'week', size: WEEK, style: 'long' }),
    Object.freeze({ below: YEAR, unit: 'month', size: MONTH, style: 'long' }),
    Object.freeze({ below: Infinity, unit: 'year', size: YEAR, style: 'long' }),
  ]);

  // **היעדר יכולת, ולא כשל.** דפדפן שאין לו ``Intl.RelativeTimeFormat`` אינו
  // "נכשל לפעמים" — אין לו את זה לכל חיי העמוד. שם מוצג התאריך עצמו
  // (``toLocaleString``). הבדיקה כאן היא על הקיום בלבד, והבנייה עם הלוקאל
  // והאפשרויות הקבועים שלמטה נמדדה בכרומיום.
  var HAS_RELATIVE = typeof Intl !== 'undefined' && typeof Intl.RelativeTimeFormat === 'function';

  var NOW_WORD = HAS_RELATIVE
    ? new Intl.RelativeTimeFormat('he', { numeric: 'auto' }).format(0, 'second')
    : '';
  var BY_STYLE = HAS_RELATIVE ? {
    short: new Intl.RelativeTimeFormat('he', { numeric: 'always', style: 'short' }),
    long: new Intl.RelativeTimeFormat('he', { numeric: 'always', style: 'long' }),
  } : null;

  /**
   * יחידה בלי "לפני" ("20 דק׳"), לצורה המקוצרת — או ``null`` כשאין יכולת.
   *
   * ``style: 'unit'`` נוסף ל-``Intl.NumberFormat`` מאוחר יותר מ-``RelativeTimeFormat``,
   * ומנוע שאינו מכיר אותו **זורק** ``RangeError`` כבר בבנייה — ערך לא תקף לאפשרות
   * שמקבלת רשימה סגורה (MDN, ‏``Intl.NumberFormat()`` constructor, "Exceptions"). זו
   * בדיקת יכולת חד-פעמית בטעינה, ולכן אין לוג: בלי היכולת הצורה המקוצרת פשוט זהה
   * לרגילה.
   */
  function unitFormatter(unit) {
    try {
      return new Intl.NumberFormat('he', { style: 'unit', unit: unit, unitDisplay: 'short' });
    } catch (_) {
      return null;
    }
  }
  var COMPACT = {
    minute: unitFormatter('minute'),
    hour: unitFormatter('hour'),
  };

  /**
   * ``Date`` או מחרוזת ISO ← אלפיות שנייה, או ``NaN``. כל ערך אחר אינו זמן.
   *
   * ``toString`` ולא ``instanceof Date``: ``instanceof`` נכשל על ``Date`` שנוצר
   * ב-realm אחר (מסגרת אחרת, או ``vm`` בבדיקות) — נמדד: הבדיקה החזירה ריק.
   */
  function toMillis(value) {
    if (Object.prototype.toString.call(value) === '[object Date]') return value.getTime();
    if (typeof value === 'string' && value) return Date.parse(value);
    return NaN;
  }

  /**
   * זמן ← "לפני X", ביחידה הגדולה ביותר שנכנסת בו פעם אחת לפחות. ערך שאינו זמן ← ``''``.
   *
   * ``opts.now`` — "עכשיו" באלפיות שנייה (לבדיקות; ברירת המחדל ``Date.now()``).
   * ``opts.compact`` — הצורה המקוצרת, ראו בראש הקובץ.
   *
   * **זמן בעתיד נחשב "עכשיו".** השעון של המכשיר אינו השעון של השרת, ותגובה שנכתבה
   * לפני רגע יכולה להגיע עם זמן שקדם לשעון המקומי בכמה שניות. "בעוד 3 שנ׳" על משהו
   * שכבר קרה הוא שקר — ושני העותקים הקודמים הציגו גם הם "כרגע" ו"הרגע" במקרה הזה.
   *
   * **הערך עצמו חייב לשאת אזור זמן** (``Z`` או היסט). מחרוזת ISO בלי היסט נקראת
   * בדפדפן כשעון מקומי, וזה R7 — באחריות מי שמייצר את הערך, לא של הפונקציה הזו.
   */
  function format(value, opts) {
    var when = toMillis(value);
    if (!isFinite(when)) return '';
    var now = (opts && typeof opts.now === 'number' && isFinite(opts.now)) ? opts.now : Date.now();
    var elapsed = now - when;
    if (!HAS_RELATIVE) return new Date(when).toLocaleString('he-IL');
    // גם זמן בעתיד (``elapsed`` שלילי) נופל כאן — ראו למעלה.
    if (elapsed < MINUTE) return NOW_WORD;
    for (var i = 0; i < SCALE.length; i++) {
      var step = SCALE[i];
      if (elapsed >= step.below) continue;
      var amount = Math.floor(elapsed / step.size);
      var compact = opts && opts.compact ? COMPACT[step.unit] : null;
      if (compact) return compact.format(amount);
      return BY_STYLE[step.style].format(-amount, step.unit);
    }
    // לא מגיעים לכאן: הדרגה האחרונה היא ``Infinity``.
    return '';
  }

  // מוקפא, כמו ``SizeFormat``: החלפת ``format`` מבחוץ הייתה משנה את התצוגה בכל
  // הצרכנים בבת אחת — בדיוק הסחיפה שהמודול הזה בא למנוע.
  window.RelativeTime = Object.freeze({ format: format });
})();
