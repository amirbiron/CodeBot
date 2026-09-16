'use strict';
// תיבת התוצאות של דפדפן הקוד כששרת החיפוש מחזיר שגיאה.
//
// **הבאג שהטסט הזה שומר מפניו.** ‏``/repo/api/search`` מחזיר שגיאות
// ב-HTTP 200 עם ``{"error": ..., "results": []}``, ומאז שמצב החיפוש
// ב-``RepoSearchService`` נעשה מפורש הוא מחזיר גם קודי מכונה —
// ``invalid_pattern`` ו-``search_failed``. ‏``performRepoSearch`` הדפיס את
// ``data.error`` כמו שהוא, ולכן המשתמש ראה את המילה ``invalid_pattern``
// בתיבת התוצאות, ואת ``data.message`` — שנושא את הסיבה האמיתית מ-git —
// לא ראה כלל.
//
// **נמדד בדפדפן אמיתי** (Chromium, שרת מקומי, ``fetch`` מוחלף בתשובת
// שגיאה): על הקוד שלפני התיקון הוצג ``invalid_pattern``, ואחריו
// ``תבנית החיפוש אינה חוקית`` ואחריה הודעת git. הטסט כאן הוא **השומר**
// של אותה מסקנה, לא מדידה חוזרת — הוא רץ ב-Node, וזה מה ש-CI מריץ על
// כל PR (``.github/workflows/ci.yml``, לולאת ``tests/*.test.js``).
//
// ההתקנה: sandbox של vm משלו, לפי המוסכמה בריפו — כל קובץ טסט כאן עצמאי
// ומגדיר את הסביבה שהוא צריך. ה-DOM כאן מינימלי בכוונה: שני האלמנטים
// ש-``performRepoSearch`` נוגעת בהם, ותו לא.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'repo-browser.js');
const SRC = fs.readFileSync(MODULE_PATH, 'utf8');

let passed = 0, failed = 0;
const pending = [];
function check(name, fn) {
  try {
    const out = fn();
    if (out && typeof out.then === 'function') {
      pending.push(out.then(() => { passed += 1; },
        (e) => { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }));
    } else { passed += 1; }
  } catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function ok(cond, what) {
  if (!cond) throw new Error(what || 'ציפיתי לאמת');
}
function has(haystack, needle, what) {
  if (!String(haystack).includes(needle)) {
    throw new Error(`${what || ''} — ציפיתי למצוא ${JSON.stringify(needle)} בתוך ${JSON.stringify(haystack)}`);
  }
}
function hasNot(haystack, needle, what) {
  if (String(haystack).includes(needle)) {
    throw new Error(`${what || ''} — לא ציפיתי למצוא ${JSON.stringify(needle)} בתוך ${JSON.stringify(haystack)}`);
  }
}
const delay = (ms) => new Promise((r) => setTimeout(r, ms));

// ``textContent`` מספיק-אמיתי: מפשיט תגיות מה-``innerHTML`` שהקוד כתב,
// כדי שהאסרשנים יבדקו **מה שהמשתמש קורא** ולא את צורת ה-HTML.
function stripTags(html) {
  return String(html || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
}

function makeSandbox(payload) {
  const input = { value: '', addEventListener() {}, focus() {}, select() {}, blur() {} };
  const resultsList = { innerHTML: '' };
  const dropdown = {
    dataset: {},
    classList: {
      _s: new Set(['hidden']),
      add(c) { this._s.add(c); },
      remove(c) { this._s.delete(c); },
      contains(c) { return this._s.has(c); },
    },
    querySelector: (sel) => (sel === '.search-results-list' ? resultsList : null),
    addEventListener() {},
  };
  const byId = { 'global-search': input, 'search-results-dropdown': dropdown };
  const store = new Map();
  const calls = [];

  const sandbox = {
    console: { log() {}, warn() {}, error() {}, debug() {} },
    document: {
      getElementById: (id) => byId[id] || null,
      querySelector: () => null,
      querySelectorAll: () => [],
      addEventListener() {},
      removeEventListener() {},
      createElement: () => ({ style: {}, classList: { add() {}, remove() {} }, appendChild() {}, remove() {} }),
      body: { appendChild() {}, classList: { add() {}, remove() {} } },
      documentElement: { style: { setProperty() {} }, classList: { add() {}, remove() {} } },
    },
    window: {
      addEventListener() {}, removeEventListener() {},
      innerWidth: 1024, innerHeight: 768,
      matchMedia: () => ({ matches: false, addEventListener() {} }),
      location: { href: 'https://x.test/repo/', search: '', hash: '', pathname: '/repo/' },
      history: { replaceState() {} },
      scrollTo() {},
    },
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => { store.set(k, String(v)); },
      removeItem: (k) => { store.delete(k); },
    },
    navigator: { clipboard: {} },
    AbortController: function () { this.signal = {}; this.abort = () => {}; },
    fetch(url) {
      calls.push(String(url));
      return Promise.resolve({ ok: true, json: async () => payload });
    },
    setTimeout, clearTimeout, setInterval, clearInterval,
    requestAnimationFrame: (f) => setTimeout(f, 0),
    URL, URLSearchParams,
    CustomEvent: function (type, init) { return { type, detail: (init || {}).detail }; },
  };
  sandbox.location = sandbox.window.location;
  sandbox.history = sandbox.window.history;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);

  return { sandbox, input, resultsList, dropdown, calls };
}

async function search(env, query) {
  env.input.value = query;
  await env.sandbox.performRepoSearch(query);
  await delay(0);
}

// -- הבאג עצמו --

check('קוד מכונה מוחלף בכותרת קריאה, ו-message מוצג כפירוט', async () => {
  const env = makeSandbox({
    error: 'invalid_pattern',
    message: "fatal: command line, 'dict[': Invalid regular expression",
    results: [],
  });

  await search(env, 'dict[');

  // בקרת שפיות: בלעדיה "לא הוצג הטוקן" יכול להיות נכון מהסיבה הלא נכונה
  // — למשל שהבקשה בכלל לא יצאה והתיבה נשארה ריקה.
  ok(env.calls.length === 1, `ציפיתי לבקשה אחת, יצאו ${env.calls.length}`);

  const shown = stripTags(env.resultsList.innerHTML);
  has(shown, 'תבנית החיפוש אינה חוקית', 'הכותרת');
  has(shown, 'Invalid regular expression', 'הפירוט מ-git');
  hasNot(shown, 'invalid_pattern', 'הטוקן הגולמי אינו אמור להגיע למשתמש');
  ok(env.dropdown.dataset.hasResults === 'false', 'שגיאה אינה "יש תוצאות"');
  ok(!env.dropdown.classList.contains('hidden'), 'התיבה חייבת להיות גלויה');
});

check('search_failed מקבל כותרת משלו', async () => {
  const env = makeSandbox({ error: 'search_failed', message: 'fatal: bad revision', results: [] });

  await search(env, 'abc');

  const shown = stripTags(env.resultsList.innerHTML);
  has(shown, 'החיפוש נכשל', 'הכותרת');
  has(shown, 'bad revision', 'הפירוט');
  hasNot(shown, 'search_failed', 'הטוקן הגולמי');
});

check('שגיאה שכבר בפרוזה נשארת כמו שהיא, עם הפירוט שלה', async () => {
  // שלושת המצבים הישנים של ``/repo/api/search`` נושאים ``error`` בפרוזה
  // ו-``message`` תמציתי. החלפה פשוטה של ``error`` ב-``message`` הייתה
  // מוחקת כאן את הכותרת המסבירה, ולכן מוצגים שניהם.
  const env = makeSandbox({
    error: 'Repository mirror not initialized',
    message: 'Please run initial_import first',
    results: [],
  });

  await search(env, 'abc');

  const shown = stripTags(env.resultsList.innerHTML);
  has(shown, 'Repository mirror not initialized', 'הכותרת המקורית');
  has(shown, 'Please run initial_import first', 'הפירוט');
});

check('שגיאה בלי message מציגה רק את הכותרת, בלי שורה ריקה', async () => {
  const env = makeSandbox({ error: 'Unknown search type: banana', results: [] });

  await search(env, 'abc');

  const shown = stripTags(env.resultsList.innerHTML);
  has(shown, 'Unknown search type: banana', 'הכותרת');
  ok(!env.resultsList.innerHTML.includes('search-result-preview'),
     'בלי message אין שורת פירוט');
});

check('HTML בהודעה עובר escape ואינו מרונדר', async () => {
  // ``message`` הוא stderr גולמי של git ולא עבר ניקוי בשום שלב.
  const env = makeSandbox({
    error: 'invalid_pattern',
    message: "fatal: command line, '<img src=x onerror=boom>': Invalid regular expression",
    results: [],
  });

  await search(env, 'x[');

  has(env.resultsList.innerHTML, '&lt;img', 'התגית חייבת לצאת משורשרת');
  hasNot(env.resultsList.innerHTML, '<img', 'תגית חיה בתוך ה-DOM');
});

check('תשובה תקינה ממשיכה להיות מרונדרת כתוצאות', async () => {
  // בלי זה, מימוש שמפיל כל תשובה לענף השגיאה היה עובר את כל מה שמעל.
  const env = makeSandbox({ results: [{ path: 'a/b.py', line: 3, content: 'x = 1' }] });

  await search(env, 'x =');

  const shown = stripTags(env.resultsList.innerHTML);
  has(shown, 'a/b.py', 'נתיב התוצאה');
  ok(env.dropdown.dataset.hasResults === 'true', 'תוצאות אמיתיות');
});

await Promise.all(pending);
console.log(`${passed} עברו, ${failed} נכשלו`);
if (failed) process.exit(1);
