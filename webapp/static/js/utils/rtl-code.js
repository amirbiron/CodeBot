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
    for (var i = 0; i < cleaned.length; i++) {
      var c = cleaned.charCodeAt(i);
      if (c >= 0x0590 && c <= 0x05FF) hebrewCount++;
    }
    return hebrewCount / cleaned.length > HEBREW_THRESHOLD;
  }

  function hasExplicitLanguage(block) {
    var cls = block.className || '';
    return /\blanguage-(?!plaintext\b)\S+/.test(cls);
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
      applyRtlIfHebrew: applyRtlIfHebrew,
    };
  }
})();
