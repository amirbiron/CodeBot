/**
 * טוסט חיווי — התראה חולפת לפעולות שנשמרות מיד.
 *
 * מבוסס על ``bookmarks.js:944-962`` (טוסט המועדפים/הנעץ), אבל עומד בפני
 * עצמו: בלי מחלקה, בלי ``BookmarkManager``, ובלי הדרישה ל-``#fileId``
 * שבלעדיה המנגנון שם כלל אינו נוצר (``bookmarks.js:1645-1656``).
 *
 * ה-CSS ב-``webapp/static/css/toast.css``. שניהם נטענים היום רק מעמוד
 * ההגדרות.
 *
 * **השם אינו ``window.showNotification`` בכוונה.** שלושה מקומות בקוד
 * (``collections.js:124``, ``dashboard.html:2756``, ``base.html:4291``)
 * בודקים את השם ההוא ונופלים אחורה לטוסט מאולתר. הגדרתו בעמוד אחד בלבד
 * הייתה משנה את התנהגותם שם ולא בשאר — חוסר עקביות גרוע מהמצב הנוכחי.
 */
(function () {
  'use strict';

  var ICONS = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
  var DEFAULT_DURATION = 4000;
  /**
   * משך היציאה בלבד — לסביבה שאין בה ``getComputedStyle``, כלומר סטאב
   * בדיקות ולא דפדפן. **אינו כפילות של הערך שב-CSS**: בדפדפן הערך נקרא
   * משם, ראו ``exitMs``.
   */
  var EXIT_MS_FALLBACK = 300;

  /**
   * כמה זמן לוקח למעבר של ``.ck-toast`` לצאת, לפי ה-CSS עצמו.
   *
   * **למה קריאה ולא קבוע.** ``transition: transform 0.3s`` ב-``toast.css``
   * וקבוע ב-JS הם שני ערכים שנסחפים בשקט: שינוי אחד מהם בלבד או חותך את
   * היציאה באמצע, או משאיר צומת בלתי נראה על המסך. כאן ה-CSS הוא המקור
   * היחיד ואין מה לסנכרן.
   *
   * זה גם מטפל ב-``prefers-reduced-motion``, שקובע ``transition: none``:
   * הקריאה מחזירה ``0s``, והצומת מוסר מיד במקום להמתין לשווא.
   *
   * הערך עשוי לחזור כרשימה מופרדת בפסיקים אם יתווסף מעבר נוסף; נלקח
   * הארוך שבהם, כי הצומת חייב לשרוד עד שכולם הסתיימו.
   */
  function exitMs(el) {
    if (typeof window.getComputedStyle !== 'function') return EXIT_MS_FALLBACK;
    var raw;
    try {
      raw = window.getComputedStyle(el).transitionDuration;
    } catch (e) {
      return EXIT_MS_FALLBACK;
    }
    if (!raw) return EXIT_MS_FALLBACK;
    var longest = 0;
    var parts = String(raw).split(',');
    for (var i = 0; i < parts.length; i += 1) {
      var t = parts[i].trim();
      // ``ms`` נבדק לפני ``s`` — כל ערך ב-``ms`` מסתיים גם ב-``s``.
      var ms = /ms$/.test(t) ? parseFloat(t) : parseFloat(t) * 1000;
      if (isFinite(ms) && ms > longest) longest = ms;
    }
    return longest;
  }

  /** ``key`` ← ``{ el, hideTimer, removeTimer }`` של הטוסט שמוצג כרגע. */
  var active = Object.create(null);

  function getContainer() {
    if (!document.body) return null;
    var el = document.getElementById('ckToastContainer');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'ckToastContainer';
    el.className = 'ck-toast-container';
    el.setAttribute('role', 'status');
    el.setAttribute('aria-live', 'polite');
    document.body.appendChild(el);
    return el;
  }

  /** מסיר מיד, בלי אנימציה, ומבטל את שני הטיימרים שלו. */
  function drop(entry) {
    if (!entry) return;
    if (entry.hideTimer) clearTimeout(entry.hideTimer);
    if (entry.removeTimer) clearTimeout(entry.removeTimer);
    if (entry.el && entry.el.parentNode) entry.el.parentNode.removeChild(entry.el);
  }

  /**
   * מציג טוסט.
   *
   * ``type``  — ``success`` / ``error`` / ``warning`` / ``info``. כל ערך
   *             אחר נקרא כ-``info``; הוא נכנס לתוך שם מחלקה, ולכן חייב
   *             לעבור רשימת היתר ולא רק שרשור.
   * ``options.key``      — טוסט עם אותו מפתח **מחליף** את קודמו במקום
   *                        להצטבר לצידו. בלי זה, שלוש שמירות ברצף
   *                        מייצרות שלושה כרטיסים זהים; ועם זה אנימציית
   *                        הכניסה רצה מחדש בכל פעם, וזה החיווי.
   * ``options.duration`` — מילישניות עד ההיעלמות. ``0`` תקף ומכובד;
   *                        ברירת המחדל חלה רק כשהערך חסר או אינו
   *                        מספר סופי ואי-שלילי.
   *
   * **ערוץ הכשל הוא ערך ההחזרה:** ``true`` אם הטוסט נכנס ל-DOM,
   * ``false`` אם לא היה ``document.body``. הקורא חייב לבדוק — טוסט הוא
   * ערוץ הדיווח למשתמש, ואם הוא לא הוצג צריך ליפול למשהו אחר.
   */
  window.ckToast = function (message, type, options) {
    var opts = options || {};
    var kind = Object.prototype.hasOwnProperty.call(ICONS, type) ? type : 'info';

    var container = getContainer();
    if (!container) return false;

    if (opts.key) drop(active[opts.key]);

    var el = document.createElement('div');
    el.className = 'ck-toast ck-toast--' + kind;

    var icon = document.createElement('span');
    icon.className = 'ck-toast__icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = ICONS[kind];

    var msg = document.createElement('span');
    msg.className = 'ck-toast__msg';
    // ``textContent`` ולא ``innerHTML``: ההודעה נושאת גם טקסט שגיאה
    // שמגיע מהשרת. ``bulk-actions.js:440`` מזריק אותו גולמי.
    msg.textContent = message == null ? '' : String(message);

    el.appendChild(icon);
    el.appendChild(msg);
    container.appendChild(el);

    // קריאת מאפיין פריסה מכריחה את הדפדפן לחשב את הסגנון ההתחלתי
    // (ההיסט של ``--ck-toast-exit``) לפני שינוי המחלקה, ובלעדיה אין ממה
    // להנפיש. זה הדטרמיניסטי; ``setTimeout(.., 10)`` היה מרוץ.
    void el.offsetWidth;
    el.classList.add('is-shown');

    var entry = { el: el, hideTimer: null, removeTimer: null };

    // **בדיקת נוכחות ולא truthiness.** ``opts.duration || DEFAULT`` היה
    // הופך ``0`` ל-4000, כלומר מתעלם מבקשה מפורשת לסגור מיד. ובדיקת
    // הטיפוס נדרשת כי ערך לא-מספרי היה עובר ל-``setTimeout``, ושם
    // ההתנהגות נקבעת על ידו ולא על ידינו.
    var duration = (typeof opts.duration === 'number'
                    && isFinite(opts.duration)
                    && opts.duration >= 0)
      ? opts.duration
      : DEFAULT_DURATION;

    entry.hideTimer = setTimeout(function () {
      el.classList.remove('is-shown');
      entry.removeTimer = setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
        if (opts.key && active[opts.key] === entry) delete active[opts.key];
      }, exitMs(el));
    }, duration);

    if (opts.key) active[opts.key] = entry;
    return true;
  };
})();
