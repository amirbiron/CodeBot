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
        container: host
      });
    } catch (e) {
      manager = null;
      try { console.error('repo-notes: הרכבת המנהל נכשלה', e); } catch (_) { }
    }
  }

  async function setEnabled(on) {
    enabled = !!on;
    if (current.path) writePref(current.repo, current.path, enabled);
    if (enabled) mount();
    else await teardown();
    paintButton();
  }

  document.addEventListener('repo:file-loaded', function (ev) {
    var detail = (ev && ev.detail) || {};
    var nextRepo = String(detail.repo || '');
    var nextPath = detail.path ? String(detail.path) : null;
    if (nextRepo === current.repo && nextPath === current.path) return;

    // **פירוק לפני החלפת היעד, ותמיד.** גם כשהפתקים כבויים, המנהל היוצא
    // עשוי להחזיק כתיבה בתור.
    teardown().then(function () {
      current = { repo: nextRepo, path: nextPath };
      enabled = nextPath ? readPref(nextRepo, nextPath) : false;
      if (enabled) mount();
      paintButton();
    });
  });

  document.addEventListener('DOMContentLoaded', function () {
    var btn = toggleBtn();
    if (btn) btn.addEventListener('click', function () { setEnabled(!enabled); });
    paintButton();
  });

  // חשוף לבדיקות ולניפוי — בלי להדליף את המנהל עצמו
  window.repoNotes = {
    isEnabled: function () { return enabled; },
    target: function () { return { repo: current.repo, path: current.path }; },
    setEnabled: setEnabled
  };
})();
