/**
 * פתקים בדפדפן הריפו — החיבור בין ``repo-browser`` ל-``StickyNotesManager``.
 *
 * **למה קובץ נפרד ולא קוד בתוך אחד מהשניים:** ``repo-browser`` לא צריך
 * לדעת שקיימים פתקים, ומנהל הפתקים לא צריך לדעת איך דפדפן הריפו בנוי.
 * ביניהם עובר אירוע אחד — ``repo:file-loaded`` — וכל הידע על התפר יושב כאן.
 *
 * **מה שונה כאן מלוח ומקובץ:** התצוגה היא CodeMirror, שאינו מרנדר שורות
 * מחוץ למסך. אין DOM להיצמד אליו, ולכן העיגון הוא ברמת **קובץ**: שני
 * המצבים (``surface``/``screen``) מצמידים את הפתק למסגרת התצוגה ולא
 * לשורת קוד. פתק שנרשם על ``main`` מופיע גם בענף PR, כי המפתח הוא
 * ``(repo, path)`` בלי ענף.
 */
(function () {
  'use strict';

  var manager = null;
  var current = { repo: '', path: null };
  var enabled = false;

  //: העדפה פר-קובץ, כמו ``board-infinite:<id>`` בלוח. רק "דלוק" נשמר —
  //: היעדר מפתח פירושו כבוי, וכך ברירת המחדל נשארת שמרנית.
  function prefKey(repo, path) { return 'repo-notes:' + repo + ':' + path; }

  function readPref(repo, path) {
    try { return window.localStorage.getItem(prefKey(repo, path)) === '1'; }
    catch (_) { return false; }
  }

  function writePref(repo, path, on) {
    try {
      if (on) window.localStorage.setItem(prefKey(repo, path), '1');
      else window.localStorage.removeItem(prefKey(repo, path));
    } catch (_) { /* מצב פרטי / אחסון חסום — לא שובר את הפיצ'ר */ }
  }

  function toggleBtn() { return document.getElementById('repo-notes-toggle'); }

  function paintButton() {
    var btn = toggleBtn();
    if (!btn) return;
    btn.style.display = current.path ? '' : 'none';
    btn.classList.toggle('active', enabled);
    btn.setAttribute('aria-pressed', enabled ? 'true' : 'false');
    btn.title = enabled ? 'הסתר פתקים' : 'פתקים על הקובץ הזה';
  }

  /**
   * מפרק את המנהל הנוכחי — ו**ממתין** לו.
   *
   * ``destroy`` מרוקן את תור השמירה לפני הפירוק, ולכן ה-``await`` כאן
   * אינו נימוס: בלעדיו החלפת קובץ הייתה יכולה להתחיל בזמן שעריכה עדיין
   * באוויר, והעריכה האחרונה הייתה נעלמת בלי שום סימן.
   */
  async function teardown() {
    if (!manager) return;
    var dying = manager;
    manager = null;
    try { await dying.destroy(); } catch (_) { /* פירוק לא אמור להפיל את הדף */ }
  }

  function mount() {
    if (manager || !current.path || !current.repo) return;
    var host = document.getElementById('code-viewer-container');
    if (!host || typeof window.StickyNotesManager !== 'function') return;
    // ``position`` נדרש כדי שפתק ``absolute`` יימדד מול המסגרת הזו ולא
    // מול ה-body. נקבע כאן ולא ב-CSS כדי לא לגעת בפריסה של הדפדפן.
    try {
      var pos = window.getComputedStyle(host).position;
      if (!pos || pos === 'static') host.style.position = 'relative';
    } catch (_) { }
    try {
      manager = new window.StickyNotesManager({
        repo: current.repo,
        path: current.path,
        container: host,
        // **ידיעת מבנה התצוגה חיה כאן, לא במנהל הגנרי.** הקונטיינר אינו
        // נגלל (``100vh`` עם ``overflow: hidden``); מה שנגלל הוא הפאנל
        // שבתוכו — ``CodeMirror`` לקוד ותצוגת ה-Markdown לקבצי ``.md``.
        // המנהל רק שואל "מי הגולל", וכל שינוי מחלקה אצל הרנדרר נופל כאן
        // ולא מפיל בשקט את מיקום הפתקים.
        //
        // נקרא בכל פעם מחדש: ``CodeMirror`` נבנה מחדש בכל קובץ, והמתג
        // מחליף בין שני פאנלים.
        scroller: function () {
          var md = host.querySelector('.markdown-preview-container');
          // ``offsetParent`` ריק פירושו ``display: none`` — הפאנל השני.
          if (md && md.offsetParent) return md;
          return host.querySelector('.CodeMirror-scroll')
              || host.querySelector('.cm-scroller')
              || null;
        }
      });
    } catch (e) {
      manager = null;
      try { console.error('repo-notes: הרכבת המנהל נכשלה', e); } catch (_) { }
    }
  }

  // **כל פעולות מחזור-החיים מסודרות בשרשרת אחת.** teardown הוא async
  // (ממתין ל-flush), ובלי סדרור שתי החלפות קובץ מהירות היו יוצרות שני
  // ``teardown().then(...)`` שנפתרים בסדר לא צפוי — ומשאירים את ``current``
  // או את ``manager`` במצב של קובץ ישן. השרשרת מריצה כל מעבר עד הסוף לפני
  // הבא, וה-``generation`` מבטיח שמעבר שנעקף בידי אירוע חד יותר לא יחיל
  // מצב מיושן.
  var opChain = Promise.resolve();
  var generation = 0;

  function enqueue(fn) {
    // ``fn`` לשני הענפים כדי שכשל במעבר אחד לא ישבור את השרשרת.
    opChain = opChain.then(fn, fn);
    return opChain;
  }

  async function applyTarget(nextRepo, nextPath, myGen) {
    if (myGen !== generation) return;               // נעקף עוד לפני שרץ
    if (nextRepo === current.repo && nextPath === current.path) return;
    await teardown();
    if (myGen !== generation) return;               // נעקף תוך כדי פירוק
    current = { repo: nextRepo, path: nextPath };
    enabled = nextPath ? readPref(nextRepo, nextPath) : false;
    if (enabled) mount();
    paintButton();
  }

  async function applyEnabled(on) {
    enabled = !!on;
    if (current.path) writePref(current.repo, current.path, enabled);
    if (enabled) mount();
    else await teardown();
    paintButton();
  }

  // ה-API הציבורי מחזיר את ה-promise של השרשרת, כדי שבדיקות יוכלו להמתין.
  function setEnabled(on) { return enqueue(function () { return applyEnabled(on); }); }

  document.addEventListener('repo:file-loaded', function (ev) {
    var detail = (ev && ev.detail) || {};
    var nextRepo = String(detail.repo || '');
    var nextPath = detail.path ? String(detail.path) : null;
    // מסמנים את הכוונה החדשה **מיד** (סינכרונית), כך שמעבר קודם שעדיין
    // בשרשרת יידע שהוא כבר לא האחרון.
    var myGen = ++generation;
    enqueue(function () { return applyTarget(nextRepo, nextPath, myGen); });
  });

  document.addEventListener('DOMContentLoaded', function () {
    var btn = toggleBtn();
    if (btn) btn.addEventListener('click', function () { setEnabled(!enabled); });
    paintButton();
  });

  // חשוף לבדיקות ולניפוי — בלי להדליף את המנהל עצמו
  window.repoNotes = {
    isEnabled: function () { return enabled; },
    hasManager: function () { return manager !== null; },
    target: function () { return { repo: current.repo, path: current.path }; },
    setEnabled: setEnabled,
    // מאפשר לבדיקות להמתין שכל המעברים בשרשרת יסתיימו
    settled: function () { return opChain; }
  };
})();
