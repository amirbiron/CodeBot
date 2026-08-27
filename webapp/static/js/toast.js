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
  /** חייב להתאים ל-``transition`` של ``.ck-toast`` ב-``toast.css``. */
  var EXIT_MS = 300;

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
   * ``options.duration`` — מילישניות עד ההיעלמות.
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
    // (``translateX(400px)``) לפני שינוי המחלקה, ובלעדיה אין ממה
    // להנפיש. זה הדטרמיניסטי; ``setTimeout(.., 10)`` היה מרוץ.
    void el.offsetWidth;
    el.classList.add('is-shown');

    var entry = { el: el, hideTimer: null, removeTimer: null };

    entry.hideTimer = setTimeout(function () {
      el.classList.remove('is-shown');
      entry.removeTimer = setTimeout(function () {
        if (el.parentNode) el.parentNode.removeChild(el);
        if (opts.key && active[opts.key] === entry) delete active[opts.key];
      }, EXIT_MS);
    }, opts.duration || DEFAULT_DURATION);

    if (opts.key) active[opts.key] = entry;
    return true;
  };
})();
