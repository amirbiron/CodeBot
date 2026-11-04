/**
 * md-heading-level-plugin.js — תוסף markdown-it שמגביל את רמות הכותרות: כותרת עמוקה מהמגבלה מוצגת כפסקה רגילה,
 * עם הטקסט כמו שנכתב (``##### טקסט``).
 *
 * **למה.** גודל הגופן של H5 ו-H6 קטן מטקסט רגיל, ואין להם מקום בין H4 לטקסט. לכן תצוגת המסמך
 * (``md_preview.html``, בכתובות ``/md/<file_id>`` ו-``/share/<share_id>?view=md``) והתצוגה החיה בעמודי העורך
 * (הווריאנט ``livePreview`` ב-``live-preview.js``) מרנדרות כותרות רק עד H4 (החלטת המשתמש: בתצוגה החיה באוקטובר
 * 2026, ובתצוגת המסמך בנובמבר 2026). דפדפן הריפו וכרטיסי החיפוש בתיעוד (הווריאנט ``default``) מרנדרים את כל שש
 * הרמות, ולא משתמשים בתוסף.
 *
 * **למה קובץ משותף.** הכלל נכתב קודם בתוך ``live-preview.js`` בלבד, ותצוגת המסמך המשיכה לרנדר H5/H6. שני
 * הרנדררים טוענים את הקובץ הזה, ולכן המגבלה מוגדרת במקום אחד: ``DOCUMENT_MAX_LEVEL``.
 *
 * **איך.** הכלל רץ אחרי פענוח הבלוקים (``block``) ולפני פענוח השורה (``inline``). לכן הטקסט עם הסולמיות מפוענח
 * כטקסט רגיל, ותוספי הכותרות שרצים אחריו — העוגנים (``markdown-it-anchor``) ותוכן העניינים — לא רואים אותה
 * ככותרת. ``heading_open`` / ``inline`` / ``heading_close`` הם תמיד שלישייה רצופה בכלל ``heading`` של markdown-it
 * (נבדק בגרסה 14.1.0). ה-``map`` של הטוקן נשאר, ולכן הפסקה מקבלת את שורת המקור שלה (``data-source-line``) כמו
 * כל פסקה.
 *
 * **מי שסופר כותרות צריך לדעת על המגבלה.** ``MdAnchors.extractExplicitAnchors`` משייך עוגן לכותרת לפי המספר
 * הסידורי שלה, ולכן מקבל את המגבלה שהותקנה בפועל (``maxHeadingLevel``). שני הרנדררים מעבירים לו אותה.
 *
 * שימוש:
 *     md.use(window.MdHeadingLevel.plugin, { maxLevel: window.MdHeadingLevel.DOCUMENT_MAX_LEVEL }); // דפדפן
 *     md.use(require('.../md-heading-level-plugin').plugin, { maxLevel: 4 });                       // Node
 */
(function (root) {
  'use strict';

  /** הרמה העמוקה ביותר שתצוגת המסמך והתצוגה החיה מרנדרות ככותרת. */
  var DOCUMENT_MAX_LEVEL = 4;

  function headingLevelPlugin(md, options) {
    var maxLevel = options && options.maxLevel;
    // מגבלה חסרה או שגויה היא טעות בקוד שקורא לתוסף, ולא מצב שאפשר להמשיך ממנו: ``undefined`` היה הופך כל
    // כותרת לפסקה (``level <= undefined`` הוא false).
    if (typeof maxLevel !== 'number' || maxLevel % 1 !== 0 || maxLevel < 1 || maxLevel > 6) {
      throw new Error('md-heading-level-plugin: maxLevel must be an integer between 1 and 6');
    }
    md.core.ruler.after('block', 'heading-max-level', function (state) {
      var tokens = state.tokens;
      for (var i = 0; i + 2 < tokens.length; i += 1) {
        var open = tokens[i];
        if (open.type !== 'heading_open' || Number(open.tag.slice(1)) <= maxLevel) continue;
        var inline = tokens[i + 1];
        var close = tokens[i + 2];
        if (inline.type !== 'inline' || close.type !== 'heading_close') continue;
        inline.content = inline.content ? open.markup + ' ' + inline.content : open.markup;
        open.type = 'paragraph_open';
        open.tag = 'p';
        open.markup = '';
        close.type = 'paragraph_close';
        close.tag = 'p';
        close.markup = '';
      }
    });
  }

  var api = { plugin: headingLevelPlugin, DOCUMENT_MAX_LEVEL: DOCUMENT_MAX_LEVEL };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;   // לבדיקות מ-Node
  }
  if (root) {
    root.MdHeadingLevel = api; // שימוש בדפדפן
  }
})(typeof window !== 'undefined' ? window : null);
