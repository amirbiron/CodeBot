/**
 * **ערכת המסמך מצד הלקוח — מקום אחד לשני המסכים שבוחרים אותה.**
 *
 * ערכת מסמך היא ערכה אישית או ציבורית שחלה רק על כרטיס "תצוגת Markdown" ב-``/md/<id>``
 * (``docs/webapp/custom_themes_guide.rst``, ``md-doc-theme``). שני מסכים מציגים ומשנים אותה: מודאל הערכות שבסרגל
 * הניווט (``initThemePicker`` ב-``base.html``) והתיבה "ערכת המסמך" בגלריית הערכות (``theme-importer.js``). שניהם
 * צריכים אותם שלושה דברים — הטוקן של ערכה מתוך ``/api/themes/list``, הבחירה הנוכחית, והשמירה — ועותק לכל מסך היה
 * נסחף בתיקון הבא (R6). לכן הם כאן, והמסכים קוראים ל-``window.CkMdDocTheme``.
 *
 * - ``tokenFor(theme)`` — ``custom:<id>`` / ``shared:<slug>`` לפריט מ-``/api/themes/list``, או ``''`` לפריט שאינו
 *   יכול להיות ערכת מסמך (ערכה מובנית, או פריט בלי מזהה). באותיות קטנות, כמו ש-``_decode_md_doc_theme`` בשרת
 *   מנרמל, כדי שהשוואה לטוקן שהשרת מחזיר תעבוד.
 * - ``getState()`` — ``{token, scope, found, name}`` מ-``GET /api/ui_prefs/md_doc_theme`` (``api_md_doc_theme_state``).
 *   ``token`` ריק כשאין ערכת מסמך. זורק בכל כשל, כולל 503 של מסד שלא ענה: "לא ידוע" אינו "ללא".
 * - ``save(token, scope)`` — ``POST /api/ui_prefs`` עם ``md_doc_theme`` (``null`` לכיבוי) ו-``md_doc_theme_scope``.
 *   מחזיר את מה שהשרת שמר, וזורק בכל כשל — הקורא מציג שגיאה ולא הצלחה.
 *
 * **לכל בקשה תקרת זמן** (``REQUEST_TIMEOUT_MS``): שני המסכים מחזיקים משהו בזמן ההמתנה — כפתור "החל" מושבת, כרטיס
 * במודאל מעומעם — ובקשה שנתקעה על חיבור half-open הייתה משאירה אותם כך. התקרה דוחה את ה-``fetch``, והקורא משחרר את
 * מה שהחזיק ב-``finally``.
 *
 * הקובץ מגדיר בלבד: שום דבר אינו רץ בטעינה, ושום בקשה אינה נשלחת עד שמסך קורא לפונקציה.
 */
(function () {
  'use strict';

  if (typeof window === 'undefined') return;

  const STATE_URL = '/api/ui_prefs/md_doc_theme';
  const SAVE_URL = '/api/ui_prefs';
  // לא נמדד ל-endpoints האלה. אותו ערך כמו ``FETCH_TIMEOUT_MS`` של בועת התזכורות ב-``base.html``, ומאותה סיבה: שם
  // נמדדו 5.32 שניות בבקשה הראשונה של worker טרי, שפותח חיבור ראשון למונגו — וגם שני ה-handlers כאן פונים למסד.
  const REQUEST_TIMEOUT_MS = 15 * 1000;

  // ``AbortSignal.timeout`` כשהדפדפן מכיר אותו; אחרת אותה תקרה מ-``AbortController``; ובדפדפן שאין בו אף אחד מהם —
  // בלי סיגנל. לפי יכולת, לא אחרי כשל. אותו מבנה כמו ``requestDeadline`` ב-``card-preview.js``, ושם ההסבר למה המבנה
  // הזה לא אוחד לקובץ משותף אחד.
  function timeoutSignal() {
    if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
      return AbortSignal.timeout(REQUEST_TIMEOUT_MS);
    }
    if (typeof AbortController === 'function') {
      const controller = new AbortController();
      setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
      return controller.signal;
    }
    return undefined;
  }

  function tokenFor(theme) {
    if (!theme || typeof theme !== 'object') return '';
    if (theme.type !== 'custom' && theme.type !== 'shared') return '';
    if (typeof theme.id !== 'string' || !theme.id) return '';
    return `${theme.type}:${theme.id}`.toLowerCase();
  }

  // גוף התשובה, או ``null`` כשאינו JSON — דף שגיאה של proxy, או גוף ריק. הקורא מחליט לפי ``ok``, לא לפי החריגה.
  async function readJson(res) {
    try {
      return await res.json();
    } catch (_) {
      return null;
    }
  }

  function failure(res, data) {
    const code = data && typeof data === 'object' && typeof data.error === 'string' && data.error
      ? data.error
      : `http_${res.status}`;
    const error = new Error(code);
    error.status = res.status;
    return error;
  }

  async function getState() {
    const res = await fetch(STATE_URL, {
      headers: { 'Accept': 'application/json' },
      signal: timeoutSignal(),
    });
    const data = await readJson(res);
    if (!res.ok || !data || typeof data !== 'object' || data.ok !== true) {
      throw failure(res, data);
    }
    return {
      token: typeof data.md_doc_theme === 'string' ? data.md_doc_theme : '',
      scope: data.scope === 'device' ? 'device' : 'global',
      found: data.found === true,
      name: typeof data.name === 'string' ? data.name : '',
    };
  }

  async function save(token, scope) {
    const res = await fetch(SAVE_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({
        md_doc_theme: token || null,
        md_doc_theme_scope: scope === 'device' ? 'device' : 'global',
      }),
      signal: timeoutSignal(),
    });
    const data = await readJson(res);
    // ``data.ok`` ולא רק ``res.ok``: ה-endpoint מחזיר גם 200 עם ``ok:false`` בחלק ממסלולי הכשל.
    if (!res.ok || !data || typeof data !== 'object' || data.ok !== true) {
      throw failure(res, data);
    }
    return typeof data.md_doc_theme === 'string' ? data.md_doc_theme : '';
  }

  window.CkMdDocTheme = Object.freeze({ tokenFor, getState, save });
})();
