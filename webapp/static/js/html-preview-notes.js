/**
 * פתקים על תצוגת ה-HTML (``/html/<id>``) — החיבור בין המסגרת ל-``StickyNotesManager``.
 *
 * **למה קובץ נפרד**, כמו ``repo-notes.js``: מנהל הפתקים לא צריך לדעת איך תצוגת ה-HTML בנויה, והתבנית לא
 * צריכה לדעת איך פתק ממוקם. כל הידע על התפר יושב כאן.
 *
 * **מה שונה כאן:** ה-HTML של הקובץ מוצג בתוך iframe מבודד (``sandbox`` בלי ``allow-same-origin``), כלומר
 * במקור אחר. העמוד אינו יכול לקרוא מהמסגרת לא את התוכן ולא כמה גללו בה — ולכן אין עיגון לאלמנט, ופתק
 * "על הקובץ" (``surface``) נע לפי מה שהמסגרת מספרת. את הסיפור שולח מדווח שהשרת מצרף לסוף ה-HTML
 * (``webapp/html_preview_frame.py``): מיקום הגלילה, רוחב התוכן והכיוון, ב-``postMessage``. כאן הדיווח
 * הופך ל"גולל" שהמנהל מכיר — אובייקט עם המאפיינים שהוא קורא מגולל (``_surfaceScrollShift``,
 * ``_surfaceReach``, ``_updatePinnedVisibility``, ``_visibleTopLeft``), והכיוון ב-``direction``, כי אין לו CSS.
 *
 * **מי מותר לו לדבר:** רק המסגרת הזו — ``ev.source`` הוא ה-``contentWindow`` שלה. ה-``origin`` של
 * המסגרת הוא ``"null"``, כמו של כל מסגרת מבודדת, ולכן הוא אינו מזהה אותה. וגם ממנה כל שדה נבדק: במצב
 * "אפשר JS" הסקריפטים של הקובץ רצים באותה מסגרת ויכולים לשלוח הודעה באותו ``type``.
 *
 * **ה-``type`` של ההודעות מגיע מהתבנית** (``data-scroll-message`` / ``data-scroll-request``), שמקבלת אותו
 * מ-``html_preview_frame`` בשרת — הוא כתוב במקום אחד בלבד.
 */
(function () {
  'use strict';

  /** מספר סופי — ``NaN`` ו-``Infinity`` עוברים כל השוואה בשקט (``amir-bug-patterns``, U3). */
  function finite(n) { return typeof n === 'number' && Number.isFinite(n); }

  /** הדיווח, אחרי בדיקה של כל שדה — או ``null``, ואז ההודעה אינה משנה דבר. */
  function readReport(data, messageType) {
    if (!data || typeof data !== 'object' || data.type !== messageType) return null;
    if (!finite(data.x) || !finite(data.y)) return null;
    if (!finite(data.scrollWidth) || !finite(data.clientWidth)) return null;
    if (data.scrollWidth < 0 || data.clientWidth < 0) return null;
    if (data.direction !== 'ltr' && data.direction !== 'rtl') return null;
    return {
      x: data.x, y: data.y,
      scrollWidth: data.scrollWidth, clientWidth: data.clientWidth,
      direction: data.direction,
    };
  }

  function mount() {
    var surface = document.getElementById('htmlPreviewSurface');
    var frame = document.getElementById('previewFrame');
    if (!surface || !frame) return;
    if (typeof window.StickyNotesManager !== 'function') {
      // העמוד טוען את ``sticky-notes.js`` לפני הקובץ הזה; בלעדיו אין פתקים בעמוד, וזה צריך להיראות.
      console.error('html-preview-notes: StickyNotesManager לא נטען — אין פתקים בתצוגה הזו');
      return;
    }
    var fileId = surface.getAttribute('data-file-id');
    var messageType = surface.getAttribute('data-scroll-message');
    var requestType = surface.getAttribute('data-scroll-request');
    if (!fileId || !messageType || !requestType) {
      console.error('html-preview-notes: חסרים נתונים בתבנית (data-file-id / data-scroll-*) — אין פתקים');
      return;
    }

    // **לפני הדיווח הראשון** — ראש התוכן, ורוחב התוכן כרוחב המסגרת: פתק נעוץ מוצג כאילו לא גללו. כך גם
    // כשהמדווח לא רץ בכלל (קובץ שנגמר בתוך ``<script>`` או הערה שלא נסגרו): הפתקים לא עוקבים אחרי הגלילה,
    // ושום דבר לא נשבר.
    var report = null;

    var view = {
      // **אזור התצוגה של המסגרת** — הקופסה שבתוך הגבול שלה, ולכן ``clientLeft``/``clientTop`` של הגולל אפס.
      getBoundingClientRect: function () {
        var r = frame.getBoundingClientRect();
        var left = r.left + (frame.clientLeft || 0);
        var top = r.top + (frame.clientTop || 0);
        var width = frame.clientWidth;
        var height = frame.clientHeight;
        return { left: left, top: top, right: left + width, bottom: top + height, width: width, height: height };
      },
      clientLeft: 0,
      clientTop: 0,
      get scrollLeft() { return report ? report.x : 0; },
      get scrollTop() { return report ? report.y : 0; },
      get scrollWidth() { return report ? report.scrollWidth : frame.clientWidth; },
      get clientWidth() { return report ? report.clientWidth : frame.clientWidth; },
      get direction() { return report ? report.direction : 'ltr'; }
    };

    var manager;
    try {
      manager = new window.StickyNotesManager({
        file: fileId,
        frame: true,
        container: surface,
        scroller: function () { return view; }
      });
    } catch (e) {
      console.error('html-preview-notes: הרכבת המנהל נכשלה', e);
      return;
    }

    window.addEventListener('message', function (ev) {
      if (ev.source !== frame.contentWindow) return;
      var next = readReport(ev.data, messageType);
      // הודעה שאינה דיווח תקין — מהקובץ עצמו במצב JS, או בכלל לא בשבילנו — אינה משנה דבר. בלי לוג: במצב
      // JS הקובץ יכול לשלוח הודעות בקצב של גלילה.
      if (!next) return;
      report = next;
      manager.refreshPinned();
    });

    // **טעינה מחדש של המסגרת** — "אפשר JS", או ניווט בתוכה — מתחילה מראש התוכן. מבקשים דיווח מיד, ולא
    // מחכים לגלילה הראשונה: המדווח שולח גם בעצמו בטעינה, ובין שתי ההודעות אין סדר מובטח מול האירוע הזה,
    // ולכן הבקשה היא שמבטיחה שהדיווח האחרון הוא של הדף שנטען. מסגרת שנווטה לדף בלי מדווח לא תענה, והפתקים
    // יישארו בראש התוכן.
    frame.addEventListener('load', function () {
      report = null;
      manager.refreshPinned();
      frame.contentWindow.postMessage({ type: requestType }, '*');
    });

    // **ובקשה אחת עכשיו, כשהמאזינים כבר רשומים.** המסגרת נפרסת לפני הסקריפטים שבסוף העמוד, והמדווח שבה שולח את
    // הדיווח הראשון לפני שהקובץ הזה רץ — הודעה שאיש לא הקשיב לה. עד כאן הדיווח הבא הגיע מהבקשה שב-``load``. מה
    // שנמדד בכרומיום (נובמבר 2026): בלי הבקשה הזו, בפריסה אחרת של העמוד, בשתיים מחמש הרצות לא הגיע שום דיווח עד
    // הגלילה הראשונה; איתה — אפס מעשר. **המנגנון לא אותר:** בהרצה שמעכבת את הקובץ הזה עד שהמסגרת נטענה, אירוע
    // ה-``load`` שלה מגיע רק אחרי הקובץ, והמאזין שמעל תופס אותו. הבקשה כאן אינה תלויה בסדר: מסגרת שכבר נטענה
    // עונה עליה, ומסגרת שעוד נטענת מפספסת אותה ומדווחת בעצמה — אחרי שהמאזין כבר כאן.
    frame.contentWindow.postMessage({ type: requestType }, '*');

    // חשוף לבדיקות ולניפוי — בלי להדליף את המנהל עצמו
    window.htmlPreviewNotes = {
      hasManager: function () { return !!manager; },
      report: function () { return report ? Object.assign({}, report) : null; }
    };
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
