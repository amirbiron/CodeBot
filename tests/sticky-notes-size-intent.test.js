/**
 * גודל הפתק: הכוונה של המשתמש מול הגודל המוצג.
 *
 * הרצה:  node tests/sticky-notes-size-intent.test.js
 *
 * **למה קובץ נפרד.** ``sticky-notes-target.test.js`` עוסק בבחירת היעד
 * ובמחזור החיים של המנהל, ומצהיר במפורש ששינוי גודל נבדק בו ברמת רישום
 * המאזינים בלבד. כאן נבדק החוזה שהגודל **הנשמר** הוא מה שהמשתמש קבע, ולא
 * מה שמוצג כרגע על המסך.
 *
 * **הבאג שזה מגן מפניו.** ``_notePayloadFromEl`` הוא המשפך שדרכו עוברות
 * כל חמש נקודות השמירה שלוכדות גודל — גרירה, נעיצה, ביטול עיגון, החלפת
 * מצב, ושינוי גודל ידני. כשהוא קורא את הגודל מ-``getBoundingClientRect``,
 * כל דבר שמכווץ את האלמנט על המסך נשמר כאילו זו הייתה בחירת המשתמש:
 *
 *   - פתק ממוזער (``height: auto !important`` ב-CSS) שנגרר ← הגובה המכווץ נשמר.
 *   - פתק שהוקטן כדי להיכנס למסך צר ואז נגרר ← הגודל המוקטן נשמר, והפתק
 *     לא יחזור לגודלו במסך הרחב לעולם.
 *
 * ההתנהגות החזותית עצמה — שהפתק באמת נכנס בגבול — דורשת דפדפן, ונבדקת שם.
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'sticky-notes.js');

/** DOM מינימלי — רק מה שהמתודות הנבדקות כאן נוגעות בו. */
function makeSandbox() {
  const stub = () => ({
    style: {}, dataset: {},
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    appendChild() {}, addEventListener() {}, removeEventListener() {},
    querySelectorAll: () => [], querySelector: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }),
    setAttribute() {}, getAttribute: () => null,
  });
  const sandbox = {
    console,
    document: {
      body: stub(),
      getElementById: () => null,
      createElement: () => stub(),
      addEventListener() {}, removeEventListener() {},
      querySelectorAll: () => [],
      get activeElement() { return null; },
    },
    window: {
      addEventListener() {}, removeEventListener() {},
      innerWidth: 1024, innerHeight: 768,
      matchMedia: () => ({ matches: false }),
      location: { search: '', hash: '' },
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: async () => ({ json: async () => ({ ok: true, notes: [] }) }),
    HTMLElement: function HTMLElement() {},
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

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}

/** אלמנט פתק מדומה: מלבן שמייצג את המוצג, ו-dataset שנושא את הכוונה. */
function noteEl({ rect, intent }) {
  const el = {
    style: {}, dataset: {},
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    getBoundingClientRect: () => Object.assign({ left: 0, top: 0, width: 0, height: 0 }, rect),
    querySelector: () => null, querySelectorAll: () => [],
  };
  if (intent) {
    el.dataset.userWidth = String(intent.width);
    el.dataset.userHeight = String(intent.height);
  }
  return el;
}

const mgr = new StickyNotesManager('f1');

// ─── המשפך: הגודל הנשמר הוא הכוונה ─────────────────────────────────────

check('גודל שנשמר נלקח מהכוונה ולא מהמלבן המוצג', () => {
  // התרחיש: פתק ברוחב 600 שהוקטן ל-320 כדי להיכנס למסך צר, ואז נגרר.
  // הגרירה מפעילה שמירה; בלי החוזה הזה, 320 נשמר כבחירת המשתמש.
  const el = noteEl({ rect: { width: 320, height: 240 }, intent: { width: 600, height: 480 } });
  const p = mgr._notePayloadFromEl(el);
  eq(p.size.width, 600, 'רוחב');
  eq(p.size.height, 480, 'גובה');
});

check('פתק ממוזער שנגרר שומר את גובהו האמיתי', () => {
  // ``.sticky-note.is-minimized { height: auto !important }`` מכווץ את
  // האלמנט לגובה הכותרת. בלי הכוונה, הגובה הזה נשמר והפתק נשאר גדם.
  const el = noteEl({ rect: { width: 300, height: 34 }, intent: { width: 300, height: 400 } });
  const p = mgr._notePayloadFromEl(el);
  eq(p.size.height, 400, 'גובה');
});

check('בלי כוונה — נפילה למלבן, כדי שפתק ישן לא יאבד גודל', () => {
  const el = noteEl({ rect: { width: 260, height: 200 } });
  const p = mgr._notePayloadFromEl(el);
  eq(p.size.width, 260, 'רוחב');
  eq(p.size.height, 200, 'גובה');
});

check('כוונה פגומה נחשבת כלא-קיימת ולא מזליגה NaN לשמירה', () => {
  const el = noteEl({ rect: { width: 260, height: 200 } });
  el.dataset.userWidth = 'לא-מספר';
  el.dataset.userHeight = '';
  const p = mgr._notePayloadFromEl(el);
  eq(Number.isFinite(p.size.width), true, 'רוחב סופי');
  eq(p.size.width, 260, 'נפילה למלבן');
});

check('המיקום ממשיך להיקרא מהמלבן', () => {
  // המיקום מוצמד ולא מוקטן, ולכן אין בו פער בין מוצג לכוונה.
  const el = noteEl({ rect: { left: 40, top: 90, width: 320, height: 240 },
                      intent: { width: 600, height: 480 } });
  const p = mgr._notePayloadFromEl(el);
  eq(p.position.x, 40, 'x');
  eq(p.position.y, 90, 'y');
});

// ─── הצמצום עצמו ───────────────────────────────────────────────────────

check('גודל שנכנס בגבולות אינו משתנה', () => {
  const r = mgr._fitSizeToBounds({ width: 300, height: 200 }, { width: 800, height: 600 });
  eq(r.width, 300, 'רוחב'); eq(r.height, 200, 'גובה');
});

check('רוחב גדול מהגבול מוקטן אליו', () => {
  const r = mgr._fitSizeToBounds({ width: 900, height: 200 }, { width: 400, height: 600 });
  eq(r.width <= 400, true, `רוחב ${r.width} חייב להיכנס ב-400`);
});

check('גובה גדול מהגבול מוקטן אליו', () => {
  const r = mgr._fitSizeToBounds({ width: 200, height: 900 }, { width: 400, height: 500 });
  eq(r.height <= 500, true, `גובה ${r.height} חייב להיכנס ב-500`);
});

check('הצמצום אינו יורד מתחת למינימום שהקוד אוכף ממילא', () => {
  // מסך צר במיוחד לא יכול לייצר פתק ברוחב 20 — הידית והכפתורים לא נכנסים.
  const r = mgr._fitSizeToBounds({ width: 900, height: 900 }, { width: 60, height: 40 });
  eq(r.width >= 120, true, `רוחב ${r.width}`);
  eq(r.height >= 80, true, `גובה ${r.height}`);
});

check('כוונה חסרה או פגומה אינה מפילה את הצמצום', () => {
  const r = mgr._fitSizeToBounds(null, { width: 400, height: 300 });
  eq(Number.isFinite(r.width), true, 'רוחב סופי');
  eq(Number.isFinite(r.height), true, 'גובה סופי');
});

// ─── מחזור החיים: מאיפה הכוונה מגיעה ───────────────────────────────────

check('הרינדור קובע את הכוונה מהערך שהגיע מה-DB', () => {
  // בלי זה, פתק שנטען מה-DB מגיע בלי כוונה, ``_notePayloadFromEl`` נופל
  // חזרה למלבן, וכל התיקון מתבטל בשקט — בלי שאף בדיקה אחרת תתריע.
  const m = new StickyNotesManager('f-render');
  m._renderNote({ id: 'n1', content: '', position: { x: 10, y: 20 },
                  size: { width: 640, height: 500 } });
  const entry = m.notes.get('n1');
  eq(!!entry, true, 'הפתק נרשם');
  const intent = m._getSizeIntent(entry.el);
  eq(!!intent, true, 'יש כוונה');
  eq(intent.width, 640, 'רוחב');
  eq(intent.height, 500, 'גובה');
});

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
