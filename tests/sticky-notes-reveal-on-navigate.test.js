'use strict';
// ניווט מכוון לפתק — מה שקורה **מלבד** הגלילה.
//
// שלושת הפערים שדווחו מהשימוש בחיפוש הפתקים: הגעת לפתק והוא ממוזער, הגעת
// אליו והוא מאחורי פתק אחר, והגעת אליו והדף בכלל לא זז. הבדיקה כאן נועלת
// את שלושתם על ``scrollToNote``.
//
// **הגלילה עצמה נמדדת בדפדפן ולא כאן.** ``scrollIntoView`` הוא שאלה של
// פריסה אמיתית — מי הגולל, כמה הוא גדל, ומתי — ו-DOM מקרטון יכול רק לומר
// "הפונקציה נקראה". מה שכן נבדק כאן הוא **על מי** היא נקראה, כי זו החלטה
// של הקוד שלנו ולא של הדפדפן.
//
// המנהל נטען מהמקור בתוך sandbox של ``vm``, באותה תבנית של
// ``sticky-notes-deep-link.test.js``.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(
  path.join(__dirname, '..', 'webapp', 'static', 'js', 'sticky-notes.js'), 'utf8');

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(a, b, what) {
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
  }
}
function ok(v, what) { if (!v) throw new Error(what || 'ציפיתי לאמת'); }

function makeSandbox() {
  const el = () => ({
    style: {}, dataset: {}, innerHTML: '', textContent: '',
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    appendChild() {}, addEventListener() {}, removeEventListener() {},
    querySelector: () => null, querySelectorAll: () => [],
    setAttribute() {}, getAttribute: () => null, remove() {},
    getBoundingClientRect: () => ({ top: 0, left: 0, width: 0, height: 0 }),
  });
  const store = { getItem: () => null, setItem() {}, removeItem() {} };
  const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    window: {
      location: { href: 'https://x.test/boards/b1', hash: '' },
      addEventListener() {}, removeEventListener() {},
      innerWidth: 1024, innerHeight: 768,
      matchMedia: () => ({ matches: false }),
      getComputedStyle: () => ({}),
      localStorage: store, scrollTo() {},
    },
    document: {
      body: el(), documentElement: el(),
      getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
      createElement: () => el(), createElementNS: () => el(),
      addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    },
    localStorage: store, navigator: {},
    URL, URLSearchParams, TextEncoder,
    setTimeout: (f) => setTimeout(f, 0),
    clearTimeout, setInterval, clearInterval,
    requestAnimationFrame: (f) => setTimeout(f, 0),
    fetch: () => Promise.resolve({ json: async () => ({ ok: true, notes: [] }) }),
    CustomEvent: function (t, i) { return { type: t, detail: (i || {}).detail }; },
  };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  sandbox.window.document = sandbox.document;
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);
  return sandbox;
}

/** פתק-סטאב: מחלקות אמיתיות, ``style`` אמיתי, ותיעוד מי נגלל. */
function noteEl(minimized) {
  const classes = new Set(minimized ? ['sticky-note', 'is-minimized'] : ['sticky-note']);
  return {
    scrolledIntoView: [],
    style: {},
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
      toggle: (c) => (classes.has(c) ? classes.delete(c) : classes.add(c)),
    },
    scrollIntoView(opts) { this.scrolledIntoView.push(opts || {}); },
    getBoundingClientRect: () => ({ top: 0, bottom: 10, left: 0, right: 10, width: 10, height: 10 }),
  };
}

/** מנהל-סטאב על ה-prototype האמיתי, כמו ב-``sticky-notes-deep-link``. */
function manager(sb, el, data) {
  const m = Object.create(sb.window.StickyNotesManager.prototype);
  m.saved = [];
  m.notes = new Map([['n1', { el, data }]]);
  m._queueSave = (element, fragment) => { m.saved.push(fragment); };
  m._updateAnchoredNotePosition = () => {};
  m._innerScroller = () => null;
  m._anchorHost = null;
  return m;
}

const FLOATING = { id: 'n1', anchor_id: '__floating__', line_start: null };

// ---------------------------------------------------------------------------

check('פתק ממוזער נפתח', () => {
  const sb = makeSandbox();
  const el = noteEl(true);
  const m = manager(sb, el, FLOATING);
  m.scrollToNote('n1');
  eq(el.classList.contains('is-minimized'), false, 'המחלקה הוסרה');
});

check('והפתיחה **נשמרת**, ולא רק מוצגת', () => {
  // הסיבה אינה טכנית: פתק שנפתח לתצוגה בלבד חוזר להיות ממוזער בכניסה
  // הבאה, והמשתמש — שלא מיזער אותו — מחפש אותו ולא מוצא.
  const sb = makeSandbox();
  const el = noteEl(true);
  const m = manager(sb, el, FLOATING);
  m.scrollToNote('n1');
  eq(m.saved, [{ is_minimized: false }], 'נשלחה שמירה אחת');
});

check('פתק שכבר פתוח אינו מייצר כתיבה מיותרת', () => {
  const sb = makeSandbox();
  const el = noteEl(false);
  const m = manager(sb, el, FLOATING);
  m.scrollToNote('n1');
  eq(m.saved, [], 'שום דבר לא נשמר');
});

check('הפתק עולה לקדמת הערימה, תמיד', () => {
  // ``sticky-notes.css`` נותן ל**כל** הפתקים ``z-index: 950``, ולכן הסדר
  // הוא סדר ה-DOM. ערך גבוה מ-950 הוא מה שמוציא את הפתק מאחורי שכניו.
  const sb = makeSandbox();
  const el = noteEl(false);
  const m = manager(sb, el, FLOATING);
  m.scrollToNote('n1');
  ok(Number(el.style.zIndex) > 950, `ציפיתי ל-z מעל 950, קיבלתי ${el.style.zIndex}`);
});

check('שני ניווטים — השני מעל הראשון', () => {
  // ערך קבוע היה נותן לשניהם אותו z, ואז הסדר ביניהם היה נקבע שוב לפי
  // ה-DOM — כלומר ההעלאה השנייה לא הייתה עושה כלום.
  const sb = makeSandbox();
  const a = noteEl(false), b = noteEl(false);
  const m = Object.create(sb.window.StickyNotesManager.prototype);
  m.notes = new Map([['a', { el: a, data: { id: 'a', anchor_id: '__floating__' } }],
                     ['b', { el: b, data: { id: 'b', anchor_id: '__floating__' } }]]);
  m._queueSave = () => {}; m._updateAnchoredNotePosition = () => {}; m._innerScroller = () => null;
  m.scrollToNote('a');
  m.scrollToNote('b');
  ok(Number(b.style.zIndex) > Number(a.style.zIndex), 'השני גבוה מהראשון');
});

check('הגלילה היא על הפתק עצמו כשאין עוגן', () => {
  // **מי נגלל הוא החלטה של הדפדפן, ועל מי — שלנו.** ``scrollIntoView``
  // מגלגל כל אב שנדרש, ולכן הקוד אינו צריך לדעת אם הגולל הוא המשטח,
  // ``<body>`` או ``<html>`` — שלוש אפשרויות שנמדדו בפועל בעמוד הזה.
  const sb = makeSandbox();
  const el = noteEl(false);
  const m = manager(sb, el, FLOATING);
  m.scrollToNote('n1');
  eq(el.scrolledIntoView.length, 1, 'נגלל פעם אחת');
  eq(el.scrolledIntoView[0].block, 'center', 'ממורכז');
});

check('ניווט לפתק עם עוגן גולל אל העוגן ולא אל הפתק', () => {
  const sb = makeSandbox();
  const el = noteEl(false);
  const anchor = noteEl(false);
  const m = manager(sb, el, { id: 'n1', anchor_id: 'sec-1', line_start: null });
  m._anchorElementFor = () => anchor;
  m.scrollToNote('n1');
  eq(anchor.scrolledIntoView.length, 1, 'העוגן נגלל');
  eq(el.scrolledIntoView.length, 0, 'והפתק לא');
});

check('תיקון המיקום חוזר על הגלילה בלבד, לא על הפעולה', () => {
  // ``_ensureInView`` קיימת בדיוק בשביל זה: המשטח גדל **אחרי** שהפתקים
  // נטענו, ולכן גלילה ראשונה יכולה לפספס. אבל חזרה על ``scrollToNote``
  // כולה הייתה פותחת ומעלה שוב ושוב, ו-``behavior: 'smooth'`` היה נלחם
  // בעצמו. מוטציה שמחזירה אותה מפילה גם את הבדיקה הזו וגם את
  // ``sticky-notes-deep-link.test.js``.
  const sb = makeSandbox();
  const el = noteEl(true);
  const m = manager(sb, el, FLOATING);
  m._isInViewport = () => false;   // כאילו הפריסה עדיין לא התייצבה
  m.scrollToNote('n1');
  m._ensureInView(el, 2);
  eq(m.saved.length, 1, 'השמירה קרתה פעם אחת בלבד');
  ok(el.scrolledIntoView.length > 1, 'והגלילה כן חזרה');
});

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
