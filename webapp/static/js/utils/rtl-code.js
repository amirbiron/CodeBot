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
   */
  var PLAIN_LANGUAGE_NAMES = ['plaintext', 'text', 'nohighlight', 'none', 'txt'];

  // ``\b`` נשמר לכל איבר. בלעדיו ``language-texture`` היה נתפס כ"בלי
  // שפה" ומתהפך — הגבול הוא מה שמפריד בין השם לבין שם שמתחיל בו.
  var EXPLICIT_LANGUAGE_RE = new RegExp(
    '\\blanguage-(?!' +
    PLAIN_LANGUAGE_NAMES.map(function (n) { return n + '\\b'; }).join('|') +
    ')\\S+'
  );

  /**
   * האם שם השפה **הגולמי** הוא שפה אמיתית — אותה שאלה, בלי DOM.
   *
   * **רגיש לרישיות במכוון**, בדיוק כמו הרג'קס: ``Text`` נחשב שפה אמיתית
   * ולכן בלוק כזה אינו מתהפך. ``toLowerCase`` כאן נראה כמו שיפור והוא
   * בדיוק הפער ששיתוף הרשימה בא למנוע — אותו קלט היה מתהפך בפתק ולא
   * במסמך. הרשימה המשותפת מבטיחה שהרשימה זהה; רק זה מבטיח שההשוואה זהה.
   */
  function hasExplicitLanguageName(name) {
    var n = String(name || '').trim();
    if (!n) return false;
    return PLAIN_LANGUAGE_NAMES.indexOf(n) === -1;
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
   * תתבסס על ה-class המקורי ולא על זיהוי אוטומטי של hljs.
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

  if (typeof window !== 'undefined') {
    window.RtlCode = {
      isHebrewMajority: isHebrewMajority,
      hasExplicitLanguage: hasExplicitLanguage,
      hasExplicitLanguageName: hasExplicitLanguageName,
      applyRtlIfHebrew: applyRtlIfHebrew,
    };
  }
})();
