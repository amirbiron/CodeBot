'use strict';
/**
 * בדיקות ל-``webapp/static/js/utils/editor-page-utils.js`` — העזרים של עמודי העורך והטיוטה.
 *
 * הרצה:  node tests/editor-page-utils.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * הקובץ נטען כמו בדפדפן — script קלאסי שמגדיר ``window.EditorPageUtils`` — כי ``package.json`` מוגדר
 * ``"type": "module"``, כמו ב-``tests/size-format.test.js``.
 *
 * **שני חלקים.** הראשון בודק את הפונקציות. השני בודק את החיווט, ושם הסיכון האמיתי: הצרכנים קוראים את
 * ``window.EditorPageUtils`` כבר כשהם נטענים, ולכן תבנית שטוענת צרכן בלי לטעון את העזרים לפניו מפילה את
 * הסקריפט כולו — בעמוד העריכה זו הטיוטה, בעמוד ההעלאה גם העורך עצמו (``file-form-manager.js``). והוא בודק
 * שאף צרכן לא חזר להחזיק עותק משלו: עד העורך הציבורי היו שלושה.
 *
 * **ומה לא:** שהטיוטה נשמרת ומשוחזרת בדפדפן אמיתי. את זה בודק ``tests/test_markdown_editor_browser.py``.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.join(__dirname, '..');
const JS_DIR = path.join(REPO_ROOT, 'webapp', 'static', 'js');
const TEMPLATES_DIR = path.join(REPO_ROOT, 'webapp', 'templates');
const MODULE_PATH = path.join(JS_DIR, 'utils', 'editor-page-utils.js');

/** הצרכנים — קבצים שקוראים את ``window.EditorPageUtils`` בזמן הטעינה. */
const CONSUMERS = ['edit-draft.js', 'upload-page.js', 'file-form-manager.js', 'markdown-editor.js'];
/** הפונקציות שהיו מועתקות; צרכן שמגדיר אחת מהן מחדש הוא עותק חדש. */
const SHARED_NAMES = ['sleep', 'waitFor', 'debounce', 'formatTime', 'getEditorContent', 'setEditorContent'];

class FakeEvent {
  constructor(type, init) { this.type = type; this.bubbles = !!(init && init.bubbles); }
}

function load(extra) {
  const sandbox = {
    window: {}, setTimeout, clearTimeout, Promise, Date, Intl, Event: FakeEvent, ...extra,
  };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return { utils: sandbox.window.EditorPageUtils, sandbox };
}

let passed = 0, failed = 0;
const pending = [];
function check(name, fn) {
  const run = async () => {
    try { await fn(); passed += 1; }
    catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
  };
  pending.push(run);
}
function eq(actual, expected, what) {
  if (actual !== expected) {
    throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(expected)}, קיבלתי ${JSON.stringify(actual)}`);
  }
}
function ok(value, what) { if (!value) throw new Error(what || 'ציפיתי לאמת'); }

// ── הפונקציות ───────────────────────────────────────────────────────────────

check('המודול מוקפא וחושף את כל העזרים', () => {
  const { utils } = load();
  ok(Object.isFrozen(utils), 'לא מוקפא');
  [...SHARED_NAMES, 'storageAvailable'].forEach((name) => eq(typeof utils[name], 'function', name));
});

check('waitFor מחזיר את הערך כשהוא מופיע', async () => {
  const { utils } = load();
  let calls = 0;
  const value = await utils.waitFor(() => (++calls >= 3 ? 'ready' : null), { timeoutMs: 1000, intervalMs: 5 });
  eq(value, 'ready');
  eq(calls, 3, 'מספר הבדיקות');
});

check('waitFor מחזיר null כשהזמן עבר', async () => {
  const { utils } = load();
  const value = await utils.waitFor(() => undefined, { timeoutMs: 30, intervalMs: 5 });
  eq(value, null);
});

check('waitFor — חריגה מ-fn היא באג ועולה, ולא נבלעת כ"עוד לא"', async () => {
  // R10: עד המעבר לקובץ המשותף היא נבלעה, ובאג ב-fn נראה כמו "לא נטען בזמן".
  const { utils } = load();
  let error = null;
  try {
    await utils.waitFor(() => { throw new TypeError('bug'); }, { timeoutMs: 30, intervalMs: 5 });
  } catch (e) { error = e; }
  ok(error && error.message === 'bug', 'החריגה לא עלתה');
});

check('debounce קורא פעם אחת, עם הארגומנטים האחרונים', async () => {
  const { utils } = load();
  const seen = [];
  const fn = utils.debounce((v) => seen.push(v), 20);
  fn(1); fn(2); fn(3);
  await new Promise((r) => setTimeout(r, 60));
  eq(JSON.stringify(seen), '[3]');
});

check('formatTime מחזיר שעה ודקה', () => {
  const { utils } = load();
  const text = utils.formatTime(new Date(2026, 9, 31, 9, 5).getTime());
  ok(/^\d{2}:\d{2}$/.test(text), `לא בצורת HH:MM: ${JSON.stringify(text)}`);
  ok(text.endsWith(':05'), text);
});

check('storageAvailable — כן כשאפשר לכתוב, לא כשהכתיבה זורקת', () => {
  const store = {};
  const good = { setItem: (k, v) => { store[k] = v; }, removeItem: (k) => { delete store[k]; } };
  eq(load({ localStorage: good }).utils.storageAvailable(), true);
  eq(Object.keys(store).length, 0, 'מפתח הבדיקה נשאר באחסון');
  const bad = { setItem: () => { throw new Error('QuotaExceededError'); }, removeItem: () => {} };
  eq(load({ localStorage: bad }).utils.storageAvailable(), false);
});

check('getEditorContent קורא מ-CodeMirror כשהוא קיים, ואחרת מה-textarea', () => {
  const textarea = { value: 'from-textarea' };
  const { utils, sandbox } = load();
  eq(utils.getEditorContent(textarea), 'from-textarea');
  sandbox.window.editorManager = { cmInstance: { state: { doc: { toString: () => 'from-cm' } } }, textarea };
  eq(utils.getEditorContent(textarea), 'from-cm');
});

check('setEditorContent — כשל של CodeMirror עולה, וה-textarea לא משתנה לבד', () => {
  // עד המעבר לכאן הכשל נבלע וה-textarea התעדכן, כלומר העורך והטיוטה הציגו טקסטים שונים.
  const textarea = { value: 'old', dispatchEvent: () => {} };
  const view = { state: { doc: { length: 3 } }, dispatch: () => { throw new Error('cm broke'); } };
  const { utils, sandbox } = load();
  sandbox.window.editorManager = { cmInstance: view, textarea };
  let error = null;
  try { utils.setEditorContent('new', textarea); } catch (e) { error = e; }
  ok(error && error.message === 'cm broke', 'החריגה לא עלתה');
  eq(textarea.value, 'old', 'ה-textarea');
});

check('setEditorContent מחליף את כל התוכן ומודיע ב-input', () => {
  const events = [];
  const textarea = { value: 'old', dispatchEvent: (e) => events.push(e) };
  const dispatched = [];
  const view = { state: { doc: { length: 3 } }, dispatch: (tr) => dispatched.push(tr) };
  const { utils, sandbox } = load();
  sandbox.window.editorManager = { cmInstance: view, textarea };
  utils.setEditorContent('new', textarea);
  eq(JSON.stringify(dispatched), JSON.stringify([{ changes: { from: 0, to: 3, insert: 'new' } }]));
  eq(textarea.value, 'new');
  eq(events.length, 1);
  eq(events[0].type, 'input');
  eq(events[0].bubbles, true, 'bubbles');
});

// ── החיווט ──────────────────────────────────────────────────────────────────

function templates(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) return templates(full);
    return entry.name.endsWith('.html') ? [full] : [];
  });
}

/** המיקום של תגית ה-script שטוענת את הקובץ, או -1. */
function scriptIndex(src, file) {
  const re = new RegExp(`<script[^>]*filename='js/${file.replace(/[.]/g, '\\.')}'[^>]*>`);
  const m = re.exec(src);
  return m ? m.index : -1;
}

check('כל תבנית שטוענת צרכן טוענת את העזרים לפניו', () => {
  let consumersSeen = 0;
  templates(TEMPLATES_DIR).forEach((file) => {
    const src = fs.readFileSync(file, 'utf8');
    const utilsAt = scriptIndex(src, 'utils/editor-page-utils.js');
    CONSUMERS.forEach((consumer) => {
      const at = scriptIndex(src, consumer);
      if (at === -1) return;
      consumersSeen += 1;
      const name = path.relative(TEMPLATES_DIR, file);
      ok(utilsAt !== -1, `${name} טוען את ${consumer} בלי utils/editor-page-utils.js`);
      ok(utilsAt < at, `${name} טוען את utils/editor-page-utils.js אחרי ${consumer}`);
    });
  });
  // בקרה: אם התבניות יפסיקו לטעון צרכנים בשמות האלה, הבדיקה הייתה עוברת בלי לבדוק כלום
  ok(consumersSeen >= CONSUMERS.length, `נמצאו רק ${consumersSeen} טעינות של צרכנים`);
});

check('אף צרכן אינו מחזיק עותק משלו של העזרים', () => {
  CONSUMERS.forEach((consumer) => {
    const src = fs.readFileSync(path.join(JS_DIR, consumer), 'utf8');
    ok(src.includes('window.EditorPageUtils'), `${consumer} אינו קורא את window.EditorPageUtils`);
    SHARED_NAMES.forEach((name) => {
      ok(!new RegExp(`function\\s+${name}\\s*\\(`).test(src), `${consumer} מגדיר עותק של ${name}`);
    });
  });
});

(async () => {
  for (const run of pending) {
    // eslint-disable-next-line no-await-in-loop
    await run();
  }
  console.log(`editor-page-utils: ${passed} passed, ${failed} failed`);
  if (failed) process.exit(1);
})();
