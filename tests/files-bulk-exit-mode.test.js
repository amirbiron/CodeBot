'use strict';
// בחירה מרובה בעמוד הקבצים: פעולה על הנבחרים שהצליחה יוצאת ממצב הבחירה.
//
// **מה נבדק:** ``multi-select.js`` ו-``bulk-actions.js`` נטענים כמו שהם, בתוך ``vm``
// עם DOM מדומה, ונבדק המצב שהם משאירים: המחלקה ``multi-select-active`` על ``body``
// (היא שמציגה את הצ'קבוקסים), ``modeActive``, ומה שנשמר ב-sessionStorage. האחרון
// חשוב בנפרד: "הוסף תגיות" מרענן את העמוד, ומנהל חדש קורא את המצב משם. לפני
// התיקון כל פעולה ניקתה רק את הבחירה, והצ'קבוקסים נשארו — גם אחרי הרענון.
//
// **ובכשל המצב נשאר**, כדי שאפשר יהיה לנסות שוב, ומוצגת שגיאה. שלוש פעולות
// ("הסר ממועדפים", "הוסף תגיות", "שתף") לא הציגו כלום כשהשרת ענה ``success: false``.
//
// **ו"ביטול בחירה" לא יוצא מהמצב** — הכרעה של המשתמש (נובמבר 2026): הוא מנקה
// את הבחירה, והצ'קבוקסים נשארים.
//
// **מה הבדיקות כאן לא מוכיחות:** שהצ'קבוקסים באמת נעלמים מהמסך. זה ה-CSS
// (``.multi-select-active .file-selection`` ב-``multi-select.css``), ו-DOM מדומה
// אינו מצייר. את זה מודדת ``tests/test_files_bulk_exit_browser.py`` בעמוד האמיתי
// (מקומית בלבד — ב-CI אין Chromium).
//
// הרצה: node tests/files-bulk-exit-mode.test.js

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const JS_DIR = path.join(__dirname, '..', 'webapp', 'static', 'js');
const MULTI_SELECT = fs.readFileSync(path.join(JS_DIR, 'multi-select.js'), 'utf8');
const BULK_ACTIONS = fs.readFileSync(path.join(JS_DIR, 'bulk-actions.js'), 'utf8');

let passed = 0, failed = 0;
async function acheck(name, fn) {
  try { await fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}
function ok(v, what) { if (!v) throw new Error(what || 'ציפיתי לאמת'); }

function mkClassList(initial = []) {
  const set = new Set(initial);
  return {
    add: (...c) => c.forEach((x) => set.add(x)),
    remove: (...c) => c.forEach((x) => set.delete(x)),
    contains: (c) => set.has(c),
    toggle: (c, force) => {
      const on = force === undefined ? !set.has(c) : !!force;
      if (on) set.add(c); else set.delete(c);
      return on;
    },
  };
}

/** אלמנט מדומה: רק מה ששני הקבצים נוגעים בו. */
function mkEl(classes = []) {
  const listeners = {};
  const el = {
    className: '', innerHTML: '', textContent: '', style: {}, dataset: {}, parentNode: null,
    classList: mkClassList(classes),
    querySelector: () => mkEl(),
    addEventListener: (t, fn) => { (listeners[t] = listeners[t] || []).push(fn); },
    appendChild: (c) => { c.parentNode = el; return c; },
    removeChild: (c) => { c.parentNode = null; return c; },
    remove: () => {},
    setAttribute: () => {},
    getAttribute: () => null,
    click: () => {},
    __fire: (t, ev) => (listeners[t] || []).forEach((fn) => fn(ev || {})),
  };
  return el;
}

/** שלושה קבצים בעמוד, כל אחד עם כרטיס וצ'קבוקס. */
function mkFiles() {
  return ['a1', 'b2', 'c3'].map((id) => {
    const card = mkEl(['file-card']);
    const checkbox = mkEl(['file-checkbox']);
    checkbox.checked = false;
    checkbox.dataset = { fileId: id, fileName: `${id}.py` };
    checkbox.closest = () => card;
    checkbox.getAttribute = (name) => (name === 'data-file-name' ? checkbox.dataset.fileName : null);
    return { id, card, checkbox };
  });
}

/**
 * טוען את שני הקבצים בסביבה אחת. ``respond(url, body)`` מחזיר את גוף התשובה של
 * השרת, או ``{throws: true}`` לכשל רשת. ``storage`` משותף בין טעינות, כמו
 * sessionStorage בין רענונים של אותה לשונית.
 */
function load({ respond, storage = new Map(), storageThrows = null } = {}) {
  const sent = [];
  const timers = [];
  const notifications = [];
  const files = mkFiles();
  const docListeners = {};
  const body = mkEl();
  const toggleBtn = mkEl(['btn-secondary']);
  const toolbar = mkEl(['hidden']);
  let reloads = 0;
  let bulkModal = null;

  const document = {
    body,
    getElementById: (id) => ({ multiSelectToggleBtn: toggleBtn, bulkActionsToolbar: toolbar })[id] || null,
    querySelector: (sel) => {
      if (sel === '.files-grid') return mkEl();
      // ``addSelectedToCollection`` לוקח את שם הקובץ מהצ'קבוקס שבכרטיס.
      const m = /input\.file-checkbox\[data-file-id="([^"]+)"\]/.exec(sel);
      const f = m && files.find((x) => x.id === m[1]);
      return f ? f.checkbox : null;
    },
    querySelectorAll: (sel) => {
      if (sel === '.file-checkbox') return files.map((f) => f.checkbox);
      if (sel === '.file-checkbox:checked') return files.filter((f) => f.checkbox.checked).map((f) => f.checkbox);
      if (sel === '.file-card.selected') return files.filter((f) => f.card.classList.contains('selected')).map((f) => f.card);
      return [];
    },
    createElement: () => mkEl(),
    addEventListener: (t, fn) => { (docListeners[t] = docListeners[t] || []).push(fn); },
  };

  const sandbox = {
    console: { log: () => {}, warn: () => {}, error: () => {} },
    JSON, String, Promise, Error, Array, Map, Math, Date,
    document,
    // ``storageThrows``: ``'write'`` — מכסה מלאה (רק כתיבה זורקת); ``'all'`` — אחסון חסום.
    sessionStorage: {
      getItem: (k) => {
        if (storageThrows === 'all') throw new Error('SecurityError');
        return storage.has(k) ? storage.get(k) : null;
      },
      setItem: (k, v) => {
        if (storageThrows) throw new Error('QuotaExceededError');
        storage.set(k, String(v));
      },
      removeItem: (k) => {
        if (storageThrows === 'all') throw new Error('SecurityError');
        storage.delete(k);
      },
    },
    setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; },
    setInterval: () => 0,
    clearInterval: () => {},
    confirm: () => true,
    navigator: { clipboard: { writeText: async () => {} } },
    location: { reload: () => { reloads += 1; } },
    URL: { createObjectURL: () => 'blob:x', revokeObjectURL: () => {} },
    fetch: async (url, init) => {
      const req = init && init.body ? JSON.parse(init.body) : null;
      sent.push({ url, body: req });
      const out = respond ? respond(url, req) : { success: true };
      if (out && out.throws) throw new Error('network down');
      return { ok: true, status: 200, json: async () => out, blob: async () => ({}) };
    },
    openBulkAddToCollectionModal: (names, options) => { bulkModal = { names, options }; },
  };
  vm.createContext(sandbox);
  sandbox.window = sandbox;

  vm.runInContext(MULTI_SELECT, sandbox);
  vm.runInContext(BULK_ACTIONS, sandbox);
  // ``showNotification`` נקרא דרך ``window.bulkActions``; עוטפים כדי לראות מה הוצג.
  const realNotify = sandbox.bulkActions.showNotification.bind(sandbox.bulkActions);
  sandbox.bulkActions.showNotification = (msg, type, opts) => {
    notifications.push({ msg, type });
    return realNotify(msg, type, opts);
  };
  (docListeners.DOMContentLoaded || []).forEach((fn) => fn());

  const ms = sandbox.multiSelect;
  ok(ms, 'MultiSelectManager לא אותחל');

  return {
    sandbox, ms, files, body, storage, sent, timers, notifications,
    get reloads() { return reloads; },
    get bulkModal() { return bulkModal; },
    /** מדליק את המצב ובוחר שני קבצים — דרך הכפתור והצ'קבוקסים, כמו משתמש. */
    enterAndSelect() {
      toggleBtn.__fire('click');
      files.slice(0, 2).forEach((f) => {
        f.checkbox.checked = true;
        (docListeners.change || []).forEach((fn) => fn({ target: f.checkbox }));
      });
      eq(ms.getSelectedCount(), 2, 'הכנה: שני קבצים נבחרו');
      ok(body.classList.contains('multi-select-active'), 'הכנה: המצב דלוק');
    },
  };
}

/** המצב "יצאנו": אין בחירה, המחלקה ירדה, וב-sessionStorage נשמר כבוי. */
function assertExited(h, what) {
  eq(h.ms.getSelectedCount(), 0, `${what}: הבחירה לא נוקתה`);
  eq(h.ms.modeActive, false, `${what}: modeActive`);
  eq(h.body.classList.contains('multi-select-active'), false, `${what}: הצ'קבוקסים עדיין מוצגים`);
  eq(h.storage.get('multiModeActive'), 'false', `${what}: sessionStorage`);
}

/** המצב "נשארנו": הבחירה והמחלקה במקומן. */
function assertStayed(h, what) {
  eq(h.ms.getSelectedCount(), 2, `${what}: הבחירה נמחקה`);
  eq(h.ms.modeActive, true, `${what}: modeActive`);
  ok(h.body.classList.contains('multi-select-active'), `${what}: הצ'קבוקסים נעלמו`);
}

// ── הצלחה: יוצאים מהמצב ────────────────────────────────────────────────
const SUCCESS_CASES = [
  ['הוספה למועדפים', (h) => h.sandbox.bulkAddToFavorites(), { success: true, updated: 2 }],
  ['הסרה ממועדפים', (h) => h.sandbox.bulkRemoveFromFavorites(), { success: true, updated: 2 }],
  ['הורדת ZIP', (h) => h.sandbox.bulkDownloadZip(), { success: true }],
  ['שיתוף', (h) => h.sandbox.bulkShareFiles(), { success: true, share_url: 'https://x/s/t', expires_at: null }],
  ['מחיקה', (h) => h.sandbox.bulkActions.deleteSelected(), { success: true, deleted: 2 }],
];

for (const [name, run, reply] of SUCCESS_CASES) {
  await acheck(`${name}: הצלחה יוצאת ממצב הבחירה`, async () => {
    const h = load({ respond: () => reply });
    h.enterAndSelect();
    await run(h);
    assertExited(h, name);
  });
}

await acheck('הוספת תגיות יוצאת מהמצב לפני הרענון, והרענון לא מחזיר את הצ\'קבוקסים', async () => {
  const storage = new Map();
  const h = load({ storage, respond: () => ({ success: true, updated: 2 }) });
  h.enterAndSelect();
  // הדיאלוג של התגיות הוא חלון אמיתי בדפדפן; כאן הוא מחזיר תגית מיד.
  h.sandbox.bulkActions.showTagDialog = async () => ['todo'];
  await h.sandbox.showBulkTagDialog();
  assertExited(h, 'תגיות');
  const reload = h.timers.find((t) => String(t.fn).includes('reload'));
  ok(reload, 'לא תוזמן רענון');
  reload.fn();
  eq(h.reloads, 1, 'הרענון לא רץ');

  // "אחרי הרענון": מנהל חדש באותו sessionStorage.
  const after = load({ storage });
  eq(after.ms.modeActive, false, 'אחרי הרענון המצב חזר להיות דלוק');
  eq(after.body.classList.contains('multi-select-active'), false, 'אחרי הרענון הצ\'קבוקסים חזרו');
});

await acheck('הוספה לאוסף יוצאת מהמצב רק כשהחלון מדווח הצלחה', async () => {
  const h = load();
  h.enterAndSelect();
  h.sandbox.bulkAddSelectedToCollection();
  ok(h.bulkModal, 'החלון לא נפתח');
  eq(JSON.stringify(h.bulkModal.names), '["a1.py","b2.py"]', 'השמות שנשלחו לחלון');
  // פתיחת החלון לבדה — וגם ביטול שלו — לא נוגעת בבחירה.
  assertStayed(h, 'אחרי פתיחת החלון');
  ok(h.bulkModal.options && typeof h.bulkModal.options.onSuccess === 'function', 'לא הועבר onSuccess');
  h.bulkModal.options.onSuccess();
  assertExited(h, 'אחרי הצלחה בחלון');
});

// ── כשל: נשארים, ומוצגת שגיאה ─────────────────────────────────────────
const FAILURE_CASES = [
  ['הוספה למועדפים', (h) => h.sandbox.bulkAddToFavorites()],
  ['הסרה ממועדפים', (h) => h.sandbox.bulkRemoveFromFavorites()],
  ['שיתוף', (h) => h.sandbox.bulkShareFiles()],
  ['מחיקה', (h) => h.sandbox.bulkActions.deleteSelected()],
];

for (const [name, run] of FAILURE_CASES) {
  await acheck(`${name}: דחייה מהשרת משאירה את הבחירה ומציגה שגיאה`, async () => {
    const h = load({ respond: () => ({ success: false, error: 'nope' }) });
    h.enterAndSelect();
    await run(h);
    assertStayed(h, name);
    ok(h.notifications.some((n) => n.type === 'error'), `${name}: לא הוצגה שגיאה — ${JSON.stringify(h.notifications)}`);
  });
}

await acheck('הוספת תגיות שהשרת דחה משאירה את הבחירה, מציגה שגיאה ולא מרעננת', async () => {
  const h = load({ respond: () => ({ success: false, error: 'nope' }) });
  h.enterAndSelect();
  h.sandbox.bulkActions.showTagDialog = async () => ['todo'];
  await h.sandbox.showBulkTagDialog();
  assertStayed(h, 'תגיות');
  ok(h.notifications.some((n) => n.type === 'error'), `לא הוצגה שגיאה — ${JSON.stringify(h.notifications)}`);
  eq(h.timers.some((t) => String(t.fn).includes('reload')), false, 'תוזמן רענון על כשל');
});

await acheck('שגיאת רשת משאירה את הבחירה', async () => {
  const h = load({ respond: () => ({ throws: true }) });
  h.enterAndSelect();
  await h.sandbox.bulkAddToFavorites();
  assertStayed(h, 'שגיאת רשת');
});

// ── אחסון שזורק ─────────────────────────────────────────────────────────
for (const mode of ['write', 'all']) {
  await acheck(`אחסון שזורק (${mode}): מחיקה שהצליחה יוצאת מהמצב, ובלי שגיאה למשתמש`, async () => {
    // לפני התיקון ``persistSelection`` כתב בלי ``try``: הכתיבה זרקה בתוך ``clearSelection``,
    // הצ'קבוקסים נשארו, והמשתמש קיבל "שגיאה במחיקה" על מחיקה שהשרת ביצע.
    const h = load({ storageThrows: mode, respond: () => ({ success: true, deleted: 2 }) });
    h.enterAndSelect();
    await h.sandbox.bulkActions.deleteSelected();
    eq(h.ms.getSelectedCount(), 0, 'הבחירה נוקתה');
    eq(h.ms.modeActive, false, 'modeActive');
    eq(h.body.classList.contains('multi-select-active'), false, 'הצ\'קבוקסים עדיין מוצגים');
    eq(h.notifications.some((n) => n.type === 'error'), false, `הוצגה שגיאה — ${JSON.stringify(h.notifications)}`);
  });
}

// ── "ביטול בחירה" ───────────────────────────────────────────────────────
await acheck('"ביטול בחירה" מנקה את הבחירה ונשאר במצב הבחירה', async () => {
  const h = load();
  h.enterAndSelect();
  h.sandbox.clearSelection();
  eq(h.ms.getSelectedCount(), 0, 'הבחירה לא נוקתה');
  eq(h.ms.modeActive, true, 'ביטול בחירה יצא מהמצב');
  ok(h.body.classList.contains('multi-select-active'), 'הצ\'קבוקסים נעלמו');
});

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
