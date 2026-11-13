/**
 * md-link-target-plugin.js — תוסף markdown-it: קישור במסמך שמוביל לעמוד נפתח בלשונית חדשה.
 *
 * **למה.** בתצוגות של מסמך Markdown לחיצה על קישור החליפה את העמוד שהגולש היה בו. בתצוגת המסמך זה איבד את המקום
 * בקריאה, ובתצוגה החיה בעמוד העריכה זה גם עזב את העורך באמצע עבודה. החלטת בעל הפרויקט (נובמבר 2026): קישור שמוביל לעמוד
 * נפתח בלשונית חדשה, בכל תצוגה של Markdown. כך זה כבר היה בפתקים הדביקים (``_appendInlineSegments`` ב-``sticky-notes.js``).
 *
 * **הכלל** — ``opensInNewTab``, שמקבל את ה-``href`` כמו שהוא נכתב ל-HTML:
 * - **נפתח בלשונית חדשה:** כתובת בסכמה ``http`` או ``https``, וכתובת בלי סכמה בכלל — ``//example.com``, ``/file/...``,
 *   ``docs/a.md``. כתובת בלי סכמה היא עמוד באתר שהדפדפן משלים מהכתובת הנוכחית.
 * - **נשאר באותה לשונית:** עוגן בתוך המסמך (``#סעיף`` — תוכן עניינים, ``¶`` של כותרת, קישור פנימי שהכותב כתב), ו-``href``
 *   ריק (``[טקסט]()``), שמפנה לעמוד עצמו. לשונית חדשה כאן הייתה פותחת עותק של אותו עמוד.
 * - **נשאר באותה לשונית:** כל סכמה אחרת — ``mailto:``, ``tel:`` וקישור לאפליקציה. הם פותחים אפליקציה ולא עמוד בדפדפן,
 *   ולכן אין להם מה לפתוח בלשונית חדשה.
 * הסכמה מזוהה לפי התחביר שלה ב-RFC 3986 (סעיף 3.1: אות, ואחריה אותיות, ספרות, ``+``, ``-`` או ``.``, עד ``:``), בלי תלות
 * באותיות גדולות או קטנות — אותו תחביר שבו הדפדפן מזהה סכמה (WHATWG URL Standard, ‏"scheme start state" ו-"scheme state").
 * רווח או תו בקרה בתחילת הכתובת לא מגיעים לכאן: ``normalizeLink`` של markdown-it מקצץ את הרווח ומקודד את תו הבקרה
 * (``%01``) לפני שהכתובת נשמרת באסימון, ואת האותיות של הסכמה הוא משאיר כמו שנכתבו (``HTTPS://``) — נבדק ב-14.1.0.
 *
 * **``rel="noopener noreferrer"``** — כמו בפתקים: העמוד שנפתח לא מקבל גישה ל-``window.opener``, ולא את כתובת העמוד שממנו
 * הגיע. ``noreferrer`` כבר כולל את ``noopener`` (HTML Living Standard, סוג הקישור ``noreferrer``), ושניהם נכתבים בכל זאת
 * כדי שהכוונה תהיה גלויה.
 *
 * **למה בתוסף של markdown-it ולא בלחיצה בכל עמוד.** התוסף מחליף את הכלל שכותב את תגית הפתיחה של קישור
 * (``md.renderer.rules.link_open``), ולכן ה-HTML עצמו יוצא עם ``target`` ו-``rel``, בכל מקום שהוא מוכנס אליו: עמוד, קובץ
 * HTML מעוצב שיורד (``renderForExport``), קישור שיתוף. כל קישור בתוכן עובר בכלל הזה: ``[טקסט](כתובת)``, ``<כתובת>`` וקישור
 * אוטומטי (``state.push('link_open', ...)`` ב-``rules_inline/link.mjs``, ‏``autolink.mjs`` ו-``linkify.mjs`` של markdown-it),
 * וגם ה-``¶`` של markdown-it-anchor (אסימון ``link_open`` עם ``#``). הערות שוליים ותוכן העניינים כותבים את הקישורים שלהם
 * בעצמם, וכולם עוגנים. כלל ``link_open`` שהוגדר לפני התוסף לא נדרס: התוסף מוסיף את המאפיינים ומעביר אליו את הכתיבה.
 *
 * **המקומות שמתקינים אותו** — כל מקום שיוצר markdown-it: ``md_preview.html``, ``live-preview.js`` (``ensureRenderer``, בשלושת
 * הסוגים) ומסלול הגיבוי ב-``repo-browser.js`` (``renderMarkdownFallback``). צד השרת מקבל את אותו כלל מ-
 * ``services/md_link_target.py`` (``opens_in_new_tab``), ושני הצדדים נבדקים מול אותה טבלת מקרים,
 * ``tests/fixtures/md_link_target_cases.json``, כדי שלא ייפרדו. ``tests/md-link-target-plugin.test.js`` בודק גם שכל מקום כזה
 * מתקין את התוסף, ושכל תבנית שמארחת רנדרר טוענת אותו.
 *
 * מקור: markdown-it@14.1.0 (``package-lock.json``) — ``Renderer.prototype.render`` ו-``renderInline`` ב-``lib/renderer.mjs``
 * קוראים ל-``rules[type]`` כשהוא מוגדר ול-``renderToken`` אחרת, ו-``attrGet`` / ``attrSet`` ב-``lib/token.mjs``.
 * markdown-it-anchor@9.2.0 בונה את ה-``¶`` מ-``new Token("link_open", "a", 1)`` עם ``href`` של ``"#" + slug``.
 *
 * שימוש:
 *     md.use(window.MdLinkTargetPlugin);
 * הבדיקות טוענות את הקובץ כמו הדפדפן, כ-script קלאסי בתוך ``vm``: ``package.json`` מוגדר ``"type": "module"``, ולכן
 * ``require`` לא היה עובד עליו.
 */
(function (root) {
  'use strict';

  // סכמה לפי RFC 3986, סעיף 3.1: ``ALPHA *( ALPHA / DIGIT / "+" / "-" / "." )``, ואחריה ``:``.
  // אותו ביטוי בדיוק ב-``SCHEME_RE`` של ``services/md_link_target.py``.
  var SCHEME_RE = /^([a-z][a-z0-9+.-]*):/i;
  var NEW_TAB_SCHEMES = { http: true, https: true };
  var NEW_TAB_REL = 'noopener noreferrer';

  function opensInNewTab(href) {
    if (typeof href !== 'string' || href === '' || href.charAt(0) === '#') return false;
    var match = SCHEME_RE.exec(href);
    if (!match) return true;
    return NEW_TAB_SCHEMES[match[1].toLowerCase()] === true;
  }

  function linkTargetPlugin(md) {
    var previous = md.renderer.rules.link_open;
    md.renderer.rules.link_open = function (tokens, idx, options, env, self) {
      var token = tokens[idx];
      if (opensInNewTab(token.attrGet('href'))) {
        token.attrSet('target', '_blank');
        token.attrSet('rel', NEW_TAB_REL);
      }
      return previous ? previous(tokens, idx, options, env, self) : self.renderToken(tokens, idx, options);
    };
  }

  // הכלל עצמו חשוף לטסטים, שבודקים אותו מול אותה טבלה כמו את צד השרת.
  linkTargetPlugin.opensInNewTab = opensInNewTab;

  if (root) {
    root.MdLinkTargetPlugin = linkTargetPlugin;
  }
})(typeof window !== 'undefined' ? window : null);
