'use strict';
/**
 * בדיקות ל-``webapp/static/js/utils/search-submit.js`` — הכלל "החיפוש רץ רק באנטר".
 *
 * הרצה:  node tests/search-submit.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * הקובץ נטען כמו בדפדפן — script קלאסי שמגדיר ``window.SubmitSearch`` — והבדיקות
 * מדברות איתו דרך אירועים על תיבה וכפתורים מדומים, כמו הדפדפן. המנוע מוחלף ביומן
 * שרושם מה נקרא, ולכן הבדיקות כאן הן על **מתי** ולא על **מה**: ההדגשה עצמה נבדקת
 * בכרומיום, ב-``tests/test_md_preview_search_browser.py`` וב-
 * ``tests/test_view_file_scroll_browser.py``.
 *
 * **ומה לא:** מה מקלדת וירטואלית שולחת כשלוחצים על מקש האנטר שלה. בדפדפן שולחני
 * אנטר הוא ``keydown`` עם ``key === 'Enter'``; במקלדת של טאבלט זה לא נמדד כאן.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'utils', 'search-submit.js');
const SRC = fs.readFileSync(MODULE_PATH, 'utf8');

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}
function escapeRegExp(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

function loadModule() {
  const sandbox = { TypeError, Object, String };
  vm.createContext(sandbox);
  sandbox.window = sandbox;
  vm.runInContext(SRC, sandbox);
  return sandbox.SubmitSearch;
}
const SubmitSearch = loadModule();

/** אלמנט מדומה שמחזיק מאזינים ויורה אירועים. */
function mkEl(extra = {}) {
  const listeners = {};
  return Object.assign({
    addEventListener: (t, fn) => { (listeners[t] = listeners[t] || []).push(fn); },
    fire: (t, ev = {}) => {
      const e = Object.assign({ defaultPrevented: false, preventDefault() { e.defaultPrevented = true; } }, ev);
      (listeners[t] || []).forEach((fn) => fn(e));
      return e;
    },
    count: (t) => (listeners[t] || []).length,
  }, extra);
}

/** תיבה, שלושה כפתורים ומנוע שרושם ביומן כל קריאה. */
function setup() {
  const log = [];
  const input = mkEl({ value: '' });
  const nextBtn = mkEl();
  const prevBtn = mkEl();
  const clearBtn = mkEl();
  const ctl = SubmitSearch.bind({
    input, nextBtn, prevBtn, clearBtn,
    search: (t) => log.push(`search:${t}`),
    next: () => log.push('next'),
    prev: () => log.push('prev'),
    reset: () => log.push('reset'),
  });
  return {
    log, input, nextBtn, prevBtn, clearBtn, ctl,
    /** הקלדה: הערך משתנה, ואז ``input`` — כמו בדפדפן. */
    type(v) { input.value = v; input.fire('input'); },
    enter(shiftKey = false) { return input.fire('keydown', { key: 'Enter', shiftKey }); },
  };
}

// ── הקלדה לא מחפשת ───────────────────────────────────────────────────────
check('הקלדה לבדה לא מפעילה את המנוע', () => {
  const h = setup();
  h.type('a'); h.type('al'); h.type('alice');
  eq(h.log.join(','), '', 'היומן');
  eq(h.ctl.submitted, '', 'submitted');
});

check('אנטר מחפש את מה שבתיבה, אחרי trim, ומונע את ברירת המחדל', () => {
  const h = setup();
  h.type('  alice ');
  const ev = h.enter();
  eq(h.log.join(','), 'search:alice', 'היומן');
  eq(h.ctl.submitted, 'alice', 'submitted');
  eq(ev.defaultPrevented, true, 'preventDefault');
});

check('אנטר שוב על אותו טקסט עובר להבא, ו-Shift+Enter לקודם — קריאה אחת לכל לחיצה', () => {
  // לפני המודול, בתצוגת הקוד המאזין של אנטר היה רשום פעמיים, ולחיצה אחת קידמה
  // שתי התאמות (ממצא 1 ב-#3477). כאן כל לחיצה היא בדיוק קריאה אחת.
  const h = setup();
  h.type('alice');
  h.enter(); h.enter(); h.enter(true);
  eq(h.log.join(','), 'search:alice,next,prev', 'היומן');
});

check('רווח שנוסף בסוף אינו טקסט חדש', () => {
  const h = setup();
  h.type('alice'); h.enter();
  h.type('alice ');
  h.enter();
  eq(h.log.join(','), 'search:alice,next', 'היומן');
});

check('אנטר על תיבה ריקה לא עושה כלום', () => {
  const h = setup();
  h.enter(); h.enter(true);
  eq(h.log.join(','), '', 'היומן');
});

check('אנטר בזמן הרכבה של מקלדת IME (isComposing או 229) — לא מחפש ולא נחסם', () => {
  // אותה בדיקה של החיפוש בתוך פתק (``sticky-notes.js``): האנטר מאשר מילה שעוד לא הושלמה.
  const h = setup();
  h.type('alice');
  for (const extra of [{ isComposing: true }, { keyCode: 229 }]) {
    const ev = h.input.fire('keydown', Object.assign({ key: 'Enter' }, extra));
    eq(ev.defaultPrevented, false, `preventDefault — ${JSON.stringify(extra)}`);
  }
  eq(h.log.join(','), '', 'היומן');
  // האנטר שאחרי סוף ההרכבה — מחפש.
  h.enter();
  eq(h.log.join(','), 'search:alice', 'אחרי ההרכבה');
});

check('מנוע שזרק בחיפוש — אנטר נוסף מחפש שוב, ולא עובר "להתאמה הבאה"', () => {
  const log = [];
  let fail = true;
  const input = mkEl({ value: 'alice' });
  const ctl = SubmitSearch.bind({
    input,
    search: (t) => { log.push(`search:${t}`); if (fail) throw new Error('engine bug'); },
    next: () => log.push('next'), prev: () => log.push('prev'), reset: () => log.push('reset'),
  });
  let threw = false;
  try { input.fire('keydown', { key: 'Enter' }); } catch (e) { threw = true; }
  eq(threw, true, 'החריגה עולה, ולא נבלעת');
  eq(ctl.submitted, '', 'submitted אחרי כשל');
  fail = false;
  input.fire('keydown', { key: 'Enter' });
  eq(log.join(','), 'search:alice,search:alice', 'היומן');
  eq(ctl.submitted, 'alice', 'submitted אחרי הצלחה');
});

check('מקש שאינו אנטר לא נוגע במנוע ולא בברירת המחדל', () => {
  const h = setup();
  h.type('alice');
  const ev = h.input.fire('keydown', { key: 'a' });
  eq(h.log.join(','), '', 'היומן');
  eq(ev.defaultPrevented, false, 'preventDefault');
});

// ── שינוי טקסט אחרי חיפוש מנקה ─────────────────────────────────────────
check('שינוי הטקסט אחרי חיפוש מנקה מיד — פעם אחת, לא בכל הקלדה', () => {
  const h = setup();
  h.type('alice'); h.enter();
  h.type('alic'); h.type('ali'); h.type('bo');
  eq(h.log.join(','), 'search:alice,reset', 'היומן');
  eq(h.ctl.submitted, '', 'submitted');
});

check('חזרה לאותו טקסט אחרי שינוי דורשת אנטר מחדש', () => {
  const h = setup();
  h.type('alice'); h.enter();
  h.type('alic'); h.type('alice');
  eq(h.log.join(','), 'search:alice,reset', 'אחרי ההקלדה');
  h.enter();
  eq(h.log.join(','), 'search:alice,reset,search:alice', 'אחרי האנטר');
});

check('הקלדה לפני כל חיפוש לא מנקה (אין מה לנקות)', () => {
  const h = setup();
  h.type('a'); h.type('');
  eq(h.log.join(','), '', 'היומן');
});

// ── הכפתורים ─────────────────────────────────────────────────────────────
check('▼ ו-▲ על טקסט שעוד לא חיפשו — מחפשים', () => {
  const h = setup();
  h.type('alice');
  h.nextBtn.fire('click');
  eq(h.log.join(','), 'search:alice', '▼');
  const k = setup();
  k.type('bob');
  k.prevBtn.fire('click');
  eq(k.log.join(','), 'search:bob', '▲');
});

check('▼ ו-▲ אחרי חיפוש — הבא והקודם', () => {
  const h = setup();
  h.type('alice'); h.enter();
  h.nextBtn.fire('click'); h.prevBtn.fire('click');
  eq(h.log.join(','), 'search:alice,next,prev', 'היומן');
});

check('✕ מרוקן את התיבה ומנקה, וטקסט חדש אחריו מחכה לאנטר', () => {
  const h = setup();
  h.type('alice'); h.enter();
  h.clearBtn.fire('click');
  eq(h.input.value, '', 'התיבה');
  eq(h.ctl.submitted, '', 'submitted');
  h.type('bob');
  eq(h.log.join(','), 'search:alice,reset', 'היומן');
});

// ── rerun ────────────────────────────────────────────────────────────────
check('rerun מחפש שוב את מה שחיפשו, לא את מה שכתוב עכשיו בתיבה', () => {
  const h = setup();
  h.type('alice'); h.enter();
  h.ctl.rerun();
  eq(h.log.join(','), 'search:alice,search:alice', 'אחרי חיפוש');

  const k = setup();
  k.type('typed-but-not-searched');
  k.ctl.rerun();
  eq(k.log.join(','), 'reset', 'בלי חיפוש — ניקוי, לא חיפוש של מה שבתיבה');
});

// ── החוזה ────────────────────────────────────────────────────────────────
check('מאזין אחד לכל אירוע — כלומר קריאה אחת לכל פעולה', () => {
  const h = setup();
  eq(h.input.count('keydown'), 1, 'keydown');
  eq(h.input.count('input'), 1, 'input');
  eq(h.nextBtn.count('click'), 1, '▼');
  eq(h.prevBtn.count('click'), 1, '▲');
  eq(h.clearBtn.count('click'), 1, '✕');
});

check('מנוע חסר או תיבה חסרה — TypeError בחיבור, ולא כשל שקט באנטר הראשון', () => {
  const input = mkEl({ value: '' });
  const full = { input, search() {}, next() {}, prev() {}, reset() {} };
  for (const missing of ['search', 'next', 'prev', 'reset', 'input']) {
    const opts = Object.assign({}, full);
    delete opts[missing];
    let threw = null;
    try { SubmitSearch.bind(opts); } catch (e) { threw = e; }
    eq(threw && threw.name, 'TypeError', `בלי ${missing}`);
  }
});

check('הממשק והבקר קפואים', () => {
  eq(Object.isFrozen(SubmitSearch), true, 'SubmitSearch');
  eq(Object.isFrozen(setup().ctl), true, 'הבקר');
});

// ── חיווט: כל תבנית שמשתמשת במודול טוענת אותו ─────────────────────────────

/** כל הקבצים תחת ``dir`` (רקורסיבי). */
function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]);
}

check('חיווט: כל תבנית שמשתמשת במודול טוענת אותו עם ?v=, בלי defer, ולפני השימוש', () => {
  // **הצרכנים נגזרים מהקוד, ולא נמנים כאן** — אותה גזירה כמו בבדיקת החיווט של
  // ``utils/text-highlight.js`` (``tests/text-highlight.test.js``). כל קובץ JS
  // שקורא ``window.SubmitSearch`` הוא צרכן, וכל תבנית שטוענת צרכן — או שקוראת
  // למודול בסקריפט אינליין — חייבת לטעון את המודול לפניו.
  //
  // בלי התג החיפוש נכבה: כל צרכן מטפל בהיעדר המודול כהיעדר יכולת (תיבה מושבתת
  // עם הסבר), ולכן אין שגיאה שתצעק.
  const jsRoot = path.join(__dirname, '..', 'webapp', 'static', 'js');
  const consumers = walk(jsRoot)
    .filter((f) => f.endsWith('.js') && !f.endsWith('.bundle.js') && f !== MODULE_PATH)
    .filter((f) => fs.readFileSync(f, 'utf8').includes('window.SubmitSearch'))
    .map((f) => "filename='js/" + path.relative(jsRoot, f).split(path.sep).join('/') + "'");

  const MODULE_REF = "filename='js/utils/search-submit.js'";
  const tplRoot = path.join(__dirname, '..', 'webapp', 'templates');
  const hosts = [];
  walk(tplRoot).filter((f) => f.endsWith('.html')).forEach((f) => {
    const src = fs.readFileSync(f, 'utf8');
    const uses = consumers.map((c) => src.indexOf(c)).filter((i) => i !== -1);
    const inline = src.indexOf('window.SubmitSearch');
    if (inline !== -1) uses.push(inline);
    if (!uses.length) return;
    const name = path.relative(tplRoot, f);
    hosts.push(name);
    const mod = src.indexOf(MODULE_REF);
    eq(mod !== -1, true, name + ' טוען את המודול');
    eq(mod < Math.min(...uses), true, name + ' טוען אותו לפני השימוש הראשון');
    const tag = new RegExp('<script[^>]*' + escapeRegExp(MODULE_REF) + '[^>]*>').exec(src);
    eq(/\?v=\{\{\s*static_version\s*\}\}/.test(tag ? tag[0] : ''), true, name + ' עם ?v=static_version');
    // מיקום בקובץ שווה לסדר הרצה רק כשהמודול אינו דחוי.
    eq(/\bdefer\b/.test(tag ? tag[0] : ''), false, name + ' בלי defer');
  });
  // שתי התבניות שהמודול נכתב בשבילן. רשימה מינימלית ולא סגורה: צרכן נוסף נבדק
  // מאליו בלולאה למעלה, וזו רק ההגנה מפני גזירה שמחזירה אפס בגלל שינוי שם.
  for (const expected of ['md_preview.html', 'view_file.html']) {
    eq(hosts.includes(expected), true, expected + ' משתמש במודול');
  }
});

check('בתצוגת הקוד אף מנוע לא מאזין לתיבה בעצמו', () => {
  // הבקר הוא היחיד שמאזין. מנוע שמאזין בעצמו — כמו היירוט של התצוגה המתקדמת
  // לפני המודול — היה מחפש בהקלדה, או מריץ פעולה פעמיים.
  const toggle = fs.readFileSync(path.join(__dirname, '..', 'webapp', 'static', 'js', 'view-codemirror-toggle.js'), 'utf8');
  eq(/codeSearchInput|nextMatchBtn|prevMatchBtn|closeSearchBtn/.test(toggle), false,
    'view-codemirror-toggle.js נוגע ברכיבי החיפוש');
});

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
