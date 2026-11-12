'use strict';
// הגדרת "הצגת כפתור סימניות" ← מוסתר: הכפתור נעלם **ושום נגיעה לא יוצרת סימנייה**.
//
// עד נובמבר 2026 ההגדרה הסתירה רק את הכפתור הצף, ונגיעה במספר שורה או בכותרת
// המשיכה ליצור סימניות. עכשיו כל דרכי היצירה ב-``bookmarks.js`` שואלות את
// ``BookmarkUI.isEnabled``: הנגיעה במספר שורה (רגילה, Shift, Ctrl, ותפריט הצבע),
// הנגיעה בכותרת במארקדאון, ו-Ctrl+B. הדרך החמישית — הודעה מתוך תצוגת HTML — ב-
// ``html_preview.html``, ונבדקת למטה מול הטקסט שלה (וההודעה עצמה בדפדפן —
// ``test_an_anchor_message_from_the_html_view``).
//
// **איך:** ``bookmarks.js`` נטען כמו שהוא בתוך ``vm``, עם DOM מדומה. המחלקות נחשפות
// מהסקריפט, ומנהל נבנה בלי ``init`` (שפונה לשרת). מה שהיה יוצר סימנייה —
// ``toggleBookmark``, ‏``promptForNote``, ‏``api.toggleBookmark`` ו-``api.toggleBookmarkAnchor`` —
// מוחלף ביומן, והבדיקה שואלת אם נקרא. כל מקרה רץ גם כשההגדרה "מוצג", כדי להוכיח
// שהיומן באמת היה מתמלא — אחרת "לא נקרא" לא אומר כלום.
//
// **מה לא מוכח כאן:** שהנגיעה בדפדפן מגיעה למאזינים. את זה מודדת
// ``tests/test_bookmarks_disabled_browser.py`` בעמוד האמיתי (מקומית בלבד — ב-CI אין Chromium).
//
// הרצה: node tests/bookmarks-disabled.test.js

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const SRC = fs.readFileSync(path.join(ROOT, 'webapp', 'static', 'js', 'bookmarks.js'), 'utf8');
const VISIBILITY_KEY = 'bookmarks_toggle_btn_visible';

let passed = 0, failed = 0;
async function acheck(name, fn) {
  try { await fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}

function mkEl(extra = {}) {
  const listeners = {};
  const classes = new Set();
  return Object.assign({
    style: {}, dataset: {}, textContent: '', innerHTML: '', parentNode: null,
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c),
      toggle: (c, f) => { const on = f === undefined ? !classes.has(c) : !!f; if (on) classes.add(c); else classes.delete(c); return on; },
    },
    addEventListener: (t, fn) => { (listeners[t] = listeners[t] || []).push(fn); },
    appendChild: (c) => c,
    setAttribute: () => {}, getAttribute: () => null,
    querySelector: () => null,
    __fire: (t, ev) => (listeners[t] || []).forEach((fn) => fn(ev)),
  }, extra);
}

/**
 * טוען את ``bookmarks.js`` עם ההגדרה ``stored`` ב-localStorage (``null`` — לא נשמרה,
 * ``'throws'`` — אחסון חסום), ומחזיר מנהל בלי ``init`` עם יומן של כל ניסיון יצירה.
 */
function load(stored) {
  const docListeners = {};
  const toggleBtn = mkEl();
  const heading = mkEl({ id: 'intro', textContent: 'מבוא' });
  heading.closest = () => heading;
  const document = {
    body: mkEl(),
    getElementById: (id) => (id === 'toggleBookmarksBtn' ? toggleBtn : null),
    querySelector: () => null,
    querySelectorAll: () => [heading],
    createElement: () => mkEl(),
    addEventListener: (t, fn) => { (docListeners[t] = docListeners[t] || []).push(fn); },
  };
  const localStorage = {
    getItem: (k) => {
      if (stored === 'throws') throw new Error('SecurityError');
      return k === VISIBILITY_KEY ? stored : null;
    },
    setItem: () => { if (stored === 'throws') throw new Error('SecurityError'); },
  };
  const winListeners = {};
  const sandbox = {
    addEventListener: (t, fn) => { (winListeners[t] = winListeners[t] || []).push(fn); },
    console: { log: () => {}, warn: () => {}, error: () => {} },
    JSON, Map, Array, Object, String, Number, Promise, Error, parseInt, setTimeout: () => 0,
    document, localStorage,
    getSelection: () => ({ toString: () => '' }),
    prompt: () => 'הערה',
  };
  vm.createContext(sandbox);
  sandbox.window = sandbox;
  vm.runInContext(`${SRC}\n;globalThis.__bm = { BookmarkManager, BookmarkUI };`, sandbox);

  const calls = [];
  const mgr = Object.create(sandbox.__bm.BookmarkManager.prototype);
  mgr.bookmarks = new Map([[7, { line_number: 7 }]]);
  mgr.defaultColor = 'yellow';
  mgr.ui = new sandbox.__bm.BookmarkUI();
  mgr.ui.showInlineColorMenu = (_el, cb) => { calls.push('colorMenu'); cb('red'); };
  mgr.ui.showLineLoading = () => {};
  mgr.getLineText = () => '';
  mgr.getCurrentLineFromSelection = () => 3;
  mgr.toggleBookmark = async (n) => { calls.push(`toggle:${n}`); };
  mgr.promptForNote = async (n) => { calls.push(`note:${n}`); };
  mgr.deleteBookmark = async (n) => { calls.push(`delete:${n}`); };
  mgr.api = {
    toggleBookmark: async () => { calls.push('api.toggle'); return { ok: false }; },
    toggleBookmarkAnchor: async () => { calls.push('api.anchor'); return { ok: false }; },
  };
  mgr.setupKeyboardShortcuts();
  /** אירוע ``storage`` כמו שהדפדפן יורה בלשונית אחרת. */
  const fireStorage = (ev) => (winListeners.storage || []).forEach((fn) => fn(
    Object.assign({ storageArea: localStorage }, ev)));
  return { mgr, calls, toggleBtn, heading, docListeners, fireStorage };
}

/** נגיעה במספר שורה 5, עם המקשים ``mods`` ו-``type`` של האירוע. */
function lineClick(h, mods = {}, type = 'click') {
  const lineEl = mkEl({ textContent: '5' });
  let prevented = false;
  const ev = Object.assign({
    type, button: type === 'contextmenu' ? 2 : 0,
    target: { closest: () => lineEl },
    preventDefault() { prevented = true; },
    stopPropagation() {},
  }, mods);
  return h.mgr.handleCodeClick(ev).then(() => prevented);
}

function headingClick(h, mods = {}, type = 'click') {
  let prevented = false;
  const ev = Object.assign({
    type, button: type === 'contextmenu' ? 2 : 0,
    target: h.heading,
    preventDefault() { prevented = true; },
    stopPropagation() {},
  }, mods);
  return h.mgr.handleMarkdownClick(ev).then(() => prevented);
}

function ctrlB(h) {
  let prevented = false;
  const ev = { ctrlKey: true, metaKey: false, shiftKey: false, key: 'b', preventDefault() { prevented = true; } };
  (h.docListeners.keydown || []).forEach((fn) => fn(ev));
  return prevented;
}

// ── המצב שנקרא מההגדרה ─────────────────────────────────────────────────
await acheck('"0" ← מוסתר וכבוי; "1" ושום דבר ← מוצג ופעיל', async () => {
  const off = load('0');
  eq(off.mgr.ui.isEnabled(), false, '"0"');
  eq(off.toggleBtn.style.display, 'none', 'הכפתור ב-"0"');
  eq(load('1').mgr.ui.isEnabled(), true, '"1"');
  eq(load(null).mgr.ui.isEnabled(), true, 'בלי הגדרה');
});

await acheck('אחסון חסום ← מוצג ופעיל, ובלי חריגה', async () => {
  // בלי אחסון גם עמוד ההגדרות לא יכול היה לשמור "מוסתר".
  const h = load('throws');
  eq(h.mgr.ui.isEnabled(), true, 'isEnabled');
  eq(h.toggleBtn.style.display, 'flex', 'הכפתור');
});

await acheck('הסתרה בזמן ריצה (setToggleButtonVisible) מכבה מיד', async () => {
  const h = load('1');
  h.mgr.ui.setToggleButtonVisible(false);
  await lineClick(h);
  eq(h.calls.join(','), '', 'נגיעה אחרי הסתרה');
});

await acheck('שינוי בלשונית אחרת (storage) חל מיד: "0" מכבה, ערך אחר או מחיקה מדליקים', async () => {
  const h = load('1');
  h.fireStorage({ key: VISIBILITY_KEY, newValue: '0' });
  eq(h.mgr.ui.isEnabled(), false, 'אחרי "0"');
  eq(h.toggleBtn.style.display, 'none', 'הכפתור אחרי "0"');
  await lineClick(h);
  eq(h.calls.join(','), '', 'נגיעה אחרי ההסתרה בלשונית האחרת');
  h.fireStorage({ key: VISIBILITY_KEY, newValue: '1' });
  eq(h.mgr.ui.isEnabled(), true, 'אחרי "1"');
  h.fireStorage({ key: VISIBILITY_KEY, newValue: '0' });
  h.fireStorage({ key: null, newValue: null });
  eq(h.mgr.ui.isEnabled(), true, 'אחרי ניקוי האחסון');
});

await acheck('storage של מפתח אחר, או מ-sessionStorage — לא נוגע במצב', async () => {
  const h = load('1');
  h.fireStorage({ key: 'something_else', newValue: '0' });
  h.fireStorage({ key: VISIBILITY_KEY, newValue: '0', storageArea: {} });
  eq(h.mgr.ui.isEnabled(), true, 'isEnabled');
  eq(h.toggleBtn.style.display, 'flex', 'הכפתור');
});

// ── מספר שורה ───────────────────────────────────────────────────────────
const LINE_CASES = [
  ['נגיעה רגילה', {}, 'click', 'toggle:5'],
  ['Shift — הערה', { shiftKey: true }, 'click', 'note:5'],
  ['תפריט הצבע', {}, 'contextmenu', 'colorMenu,api.toggle'],
];
for (const [name, mods, type, whenOn] of LINE_CASES) {
  await acheck(`מספר שורה, ${name}: כבוי — לא קורה כלום, והקישור לא נפתח`, async () => {
    const off = load('0');
    const prevented = await lineClick(off, mods, type);
    eq(off.calls.join(','), '', 'כבוי');
    // הכרעה א' של המשתמש: המספר לא מתנהג כקישור ``#line-N``.
    eq(prevented, true, 'preventDefault');
    const on = load('1');
    await lineClick(on, mods, type);
    eq(on.calls.join(','), whenOn, 'מוצג — היומן היה מתמלא');
  });
}

await acheck('מספר שורה, Ctrl — כבוי לא מוחק סימנייה קיימת', async () => {
  const off = load('0');
  off.mgr.bookmarks.set(5, { line_number: 5 });
  await lineClick(off, { ctrlKey: true });
  eq(off.calls.join(','), '', 'כבוי');
  const on = load('1');
  on.mgr.bookmarks.set(5, { line_number: 5 });
  await lineClick(on, { ctrlKey: true });
  eq(on.calls.join(','), 'delete:5', 'מוצג');
});

// ── כותרת במארקדאון ─────────────────────────────────────────────────────
const HEADING_CASES = [
  ['נגיעה רגילה', {}, 'click'],
  ['Shift — הערה', { shiftKey: true }, 'click'],
  ['תפריט הצבע', {}, 'contextmenu'],
];
for (const [name, mods, type] of HEADING_CASES) {
  await acheck(`כותרת, ${name}: כבוי — לא קורה כלום, ובלי preventDefault`, async () => {
    const off = load('0');
    const prevented = await headingClick(off, mods, type);
    eq(off.calls.join(','), '', 'כבוי');
    // לכותרת אין פעולה משלה; קישור בתוכה ממשיך לעבוד.
    eq(prevented, false, 'preventDefault');
    const on = load('1');
    await headingClick(on, mods, type);
    eq(on.calls.includes('api.anchor'), true, `מוצג — היומן היה מתמלא (${on.calls.join(',')})`);
  });
}

// ── Ctrl+B ──────────────────────────────────────────────────────────────
await acheck('Ctrl+B: כבוי — לא יוצר ולא חוסם את המקש', async () => {
  const off = load('0');
  eq(ctrlB(off), false, 'preventDefault');
  eq(off.calls.join(','), '', 'כבוי');
  const on = load('1');
  eq(ctrlB(on), true, 'preventDefault כשמוצג');
  eq(on.calls.join(','), 'toggle:3', 'מוצג');
});

// ── הדרך החמישית: הודעה מתצוגת HTML ─────────────────────────────────────
await acheck('תצוגת HTML שואלת את isEnabled לפני toggleBookmarkAnchor', async () => {
  const tpl = fs.readFileSync(path.join(ROOT, 'webapp', 'templates', 'html_preview.html'), 'utf8');
  const gate = tpl.indexOf('!window.bookmarkManager.ui.isEnabled()) return;');
  const call = tpl.indexOf('window.bookmarkManager.api.toggleBookmarkAnchor(');
  eq(gate !== -1 && call !== -1 && gate < call, true, 'השער לפני הקריאה');
});

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
