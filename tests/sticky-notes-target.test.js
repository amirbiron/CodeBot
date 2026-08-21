/**
 * טסטים ל-webapp/static/js/sticky-notes.js — הפרמטריזציה ליעד (קובץ מול לוח).
 *
 * הרצה:  node tests/sticky-notes-target.test.js
 * (אין ברפו runner ל-JS, ולכן הקובץ עצמאי ומחזיר קוד יציאה 1 בכישלון —
 *  אותה תבנית כמו tests/md-anchors.test.js.)
 *
 * מה נבדק כאן: **רק** בחירת היעד ומצב המיקום. גרירה, שינוי גודל ותור
 * השמירה אינם נבדקים — הם דורשים DOM אמיתי, והם גם לא השתנו.
 *
 * הדבר החשוב ביותר שהקובץ הזה מגן עליו: שהצורה ההיסטורית
 * ``new StickyNotesManager('<file_id>')`` ממשיכה להתנהג בדיוק כמו קודם.
 * md_preview.html קורא כך, ורגרסיה שם שוברת פיצ'ר קיים בפרודקשן.
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'sticky-notes.js');

/** DOM מינימלי — רק מה ש-``_init`` נוגע בו לפני שהוא נכשל בשקט. */
function makeSandbox() {
  const el = () => ({
    style: {}, dataset: {}, classList: { add() {}, remove() {}, contains: () => false },
    appendChild() {}, addEventListener() {}, querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }),
    setAttribute() {}, getAttribute: () => null,
  });
  const body = el();
  const sandbox = {
    console,
    document: {
      body,
      getElementById: () => null,
      createElement: () => el(),
      addEventListener() {},
      querySelectorAll: () => [],
    },
    window: {
      addEventListener() {},
      innerWidth: 1024,
      innerHeight: 768,
      matchMedia: () => ({ matches: false }),
      location: { search: '', hash: '' },
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: async () => ({ json: async () => ({ ok: true, notes: [] }) }),
    setTimeout, clearTimeout, setInterval, clearInterval,
    MutationObserver: undefined, ResizeObserver: undefined,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox;
}

const sandbox = makeSandbox();
const StickyNotesManager = sandbox.window.StickyNotesManager;

let passed = 0;
let failed = 0;

function check(name, fn) {
  try {
    fn();
    passed += 1;
  } catch (err) {
    failed += 1;
    console.error(`✗ ${name}\n    ${err && err.message}`);
  }
}

function eq(actual, expected, what) {
  if (actual !== expected) {
    throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(expected)}, קיבלתי ${JSON.stringify(actual)}`);
  }
}

// -- תאימות לאחור: הצורה ההיסטורית --

check('מחרוזת נקראת כמזהה קובץ', () => {
  const m = new StickyNotesManager('abc123');
  eq(m.fileId, 'abc123', 'fileId');
  eq(m.boardId, null, 'boardId');
  eq(m._scopeUrl, '/api/sticky-notes/abc123', 'scopeUrl');
  eq(m.container, sandbox.document.body, 'container');
});

check('מפתח הקאש של קובץ לא השתנה', () => {
  const m = new StickyNotesManager('abc123');
  eq(m._cacheKey, 'sticky-notes:abc123');
});

// -- לוח --

check('אובייקט עם board נקרא כלוח', () => {
  const m = new StickyNotesManager({ board: 'b1' });
  eq(m.boardId, 'b1', 'boardId');
  eq(m.fileId, null, 'fileId');
  eq(m._scopeUrl, '/api/sticky-notes/board/b1', 'scopeUrl');
});

check('מפתח הקאש של לוח נפרד מזה של קובץ', () => {
  // בלי ההפרדה, לוח וקובץ עם אותה מחרוזת מזהה היו מרנדרים זה את הפתקים של זה
  const board = new StickyNotesManager({ board: 'same' });
  const file = new StickyNotesManager('same');
  eq(board._cacheKey, 'sticky-notes:board:same');
  eq(file._cacheKey, 'sticky-notes:same');
  if (board._cacheKey === file._cacheKey) throw new Error('מפתחות הקאש התנגשו');
});

check('הקונטיינר של לוח אינו ה-body', () => {
  const surface = { appendChild() {}, querySelectorAll: () => [] };
  const m = new StickyNotesManager({ board: 'b1', container: surface });
  eq(m.container, surface);
});

check('יעד חסר נכשל מיד ולא בשקט', () => {
  let threw = false;
  try { new StickyNotesManager({}); } catch (_) { threw = true; }
  if (!threw) throw new Error('ציפיתי לחריגה כשאין file ואין board');
});

// -- _resolveMode --

const fileMgr = new StickyNotesManager('f1');
const boardMgr = new StickyNotesManager({ board: 'b1' });

check('סנטינל הנעיצה ממופה ל-surface', () => {
  eq(fileMgr._resolveMode({ anchor_id: '__pinned__' }), 'surface');
});

check('סנטינל הציפה ממופה ל-screen', () => {
  eq(fileMgr._resolveMode({ anchor_id: '__floating__' }), 'screen');
});

check('פתק בלי שום סימון הוא screen', () => {
  eq(fileMgr._resolveMode({}), 'screen');
});

check('שורת מקור ממפה ל-anchored — רק בקובץ', () => {
  eq(fileMgr._resolveMode({ line_start: 12 }), 'anchored', 'קובץ');
  // בלוח אין שורות מקור, ולכן אין מצב anchored בכלל. בלי זה, כל מחרוזת
  // שתזלוג ל-anchor_id הייתה מעבירה את הפתק למצב שבו ה-top מחושב מול
  // עוגן שאינו קיים — פתק שנעלם.
  eq(boardMgr._resolveMode({ line_start: 12 }), 'screen', 'לוח');
});

check('עוגן טקסטואלי ממפה ל-anchored רק בקובץ', () => {
  eq(fileMgr._resolveMode({ anchor_id: 'some-heading' }), 'anchored', 'קובץ');
  eq(boardMgr._resolveMode({ anchor_id: 'some-heading' }), 'screen', 'לוח');
});

check('שדה mode מנצח את הסנטינלים', () => {
  eq(boardMgr._resolveMode({ mode: 'screen', anchor_id: '__pinned__' }), 'screen');
  eq(boardMgr._resolveMode({ mode: 'surface' }), 'surface');
});

check('mode לא חוקי נופל חזרה לגזירה מהסנטינלים', () => {
  eq(boardMgr._resolveMode({ mode: 'diagonal', anchor_id: '__pinned__' }), 'surface');
});

check('anchored בלי מקור שורות יורד ל-surface', () => {
  eq(boardMgr._resolveMode({ mode: 'anchored' }), 'surface');
});

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
