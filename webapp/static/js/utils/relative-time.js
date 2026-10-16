/**
 * זמן יחסי לתצוגה ("לפני 20 דק׳", "אתמול", "לפני שבועיים") — מקור אחד לצד הלקוח.
 *
 * משותף לחלונית השרשורים בפתקים (``sticky-notes.js``), לרשימת הקבצים האחרונים
 * (``base.html``) ולהיסטוריית הקומיטים בדפדפן הריפו (``repo-history.js``). לפני
 * הקובץ הזה היו שני עותקים כתובים ביד, והם כבר נבדלו: האחד ספר עד שנים והשני
 * נעצר בימים ("לפני 400 ימים"), ושניהם אמרו "לפני 1 שעות" — כי עברית אינה
 * מוסיפה "1" ליחיד, ואף אחד מהם לא ידע את זה (R6).
 *
 * **המילים כתובות כאן, ולא מגיעות מ-``Intl.RelativeTimeFormat``.** הניסוח של
 * ``Intl`` הוא נתוני ה-CLDR של המנוע, והם משתנים בין גרסאות. נמדד באוקטובר 2026:
 * בנוד 22 (ICU 77.1, ‏CLDR 47) ובכרומיום 141 שעה אחת היא "לפני שעה", אבל בנוד 24
 * (ICU 78.3, ‏CLDR 48) היא "לפני שע׳ (1)", יום אחד הוא "לפני יום אחד (1)" במקום
 * "אתמול", ושעתיים הן "לפני שעתיים (2)". כלומר אותו קוד היה מציג משהו אחר בכל
 * דפדפן, לפי הגרסה שלו — ואף טסט על מנוע אחד לא היה תופס את זה. כאן כל מנוע מציג
 * בדיוק אותו טקסט, וזה גם מה שהעיצוב מראה.
 *
 * הצורות הן אלה ש-CLDR 47 נתן, כי הן מה שהעיצוב מציג: דקות ושעות בקיצור ("דק׳",
 * "שע׳"), ימים, שבועות, חודשים ושנים במילה המלאה; יחיד בלי המספר ("לפני שעה"),
 * וזוגי בצורת הזוגי ("לפני שעתיים") — חוץ מדקות, שם "לפני 2 דק׳".
 *
 * **הצורה המקוצרת** (``compact``) היא של חלונית צרה בפתק צר: אותו טקסט בלי
 * "לפני" ("20 דק׳", "שעה"). היא חלה רק על דקות ושעות; מיום ומעלה היא זהה לרגילה,
 * כי "יום" או "שבוע" לבד כבר אינם זמן שעבר.
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

  var NOW_WORD = 'עכשיו';
  var BEFORE = 'לפני ';
  // יום אחד הוא "אתמול" ולא "לפני יום".
  var YESTERDAY = 'אתמול';

  /**
   * הסולם: עד איזה מרחק כל יחידה חלה, והמילים שלה — יחיד, זוגי (``null``: אין
   * צורת זוגי, ושתיים נכתבות כמו רבים) ורבים, שאחריהם המספר. ``compact`` — האם
   * הצורה המקוצרת חלה עליה.
   */
  var SCALE = Object.freeze([
    Object.freeze({ below: HOUR, size: MINUTE, one: 'דקה', two: null, many: 'דק׳', compact: true }),
    Object.freeze({ below: DAY, size: HOUR, one: 'שעה', two: 'שעתיים', many: 'שע׳', compact: true }),
    Object.freeze({ below: WEEK, size: DAY, one: 'יום', two: 'יומיים', many: 'ימים', compact: false }),
    Object.freeze({ below: MONTH, size: WEEK, one: 'שבוע', two: 'שבועיים', many: 'שבועות', compact: false }),
    Object.freeze({ below: YEAR, size: MONTH, one: 'חודש', two: 'חודשיים', many: 'חודשים', compact: false }),
    Object.freeze({ below: Infinity, size: YEAR, one: 'שנה', two: 'שנתיים', many: 'שנים', compact: false }),
  ]);

  /** כמות ביחידה ← המילים בלי "לפני" ("שעה", "שעתיים", "3 שע׳"). */
  function amountPhrase(step, amount) {
    if (amount === 1) return step.one;
    if (amount === 2 && step.two) return step.two;
    return amount + ' ' + step.many;
  }

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
    // גם זמן בעתיד (``elapsed`` שלילי) נופל כאן — ראו למעלה.
    if (elapsed < MINUTE) return NOW_WORD;
    for (var i = 0; i < SCALE.length; i++) {
      var step = SCALE[i];
      if (elapsed >= step.below) continue;
      var amount = Math.floor(elapsed / step.size);
      var phrase = amountPhrase(step, amount);
      if (opts && opts.compact && step.compact) return phrase;
      if (step.size === DAY && amount === 1) return YESTERDAY;
      return BEFORE + phrase;
    }
    // לא מגיעים לכאן: הדרגה האחרונה היא ``Infinity``.
    return '';
  }

  // מוקפא, כמו ``SizeFormat``: החלפת ``format`` מבחוץ הייתה משנה את התצוגה בכל
  // הצרכנים בבת אחת — בדיוק הסחיפה שהמודול הזה בא למנוע.
  window.RelativeTime = Object.freeze({ format: format });
})();
