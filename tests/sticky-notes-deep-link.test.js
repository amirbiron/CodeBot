'use strict';
// בדיקות על הקישור העמוק לפתק — ``?note=<id>`` שמגיע מהתראת תזכורת.
//
// **מה נשמר כאן:** דפדפן הריפו מנקה את ``?note=`` מה-URL מיד אחרי הצריכה
// (``consumeOneShotUrlParams`` ב-``repo-browser.js``), אחרת הפרמטר היה שורד
// לריענון ומנסה לפתוח פתק ששייך לקובץ בריפו אחר. לכן ``sticky-notes.js``
// לוכד את המזהה בזמן טעינת הסקריפט, לפני הניקוי.
//
// אבל לכידה אינה צריכה: ``init`` עושה ``await this.loadNotes()`` **לפני**
// ניסיון הגלילה, ו-``loadNotes`` נכשלת בשקט בשלושה מסלולים (חריגה שנתפסת,
// ``_destroyed``, ו-``data.ok === false``). בכל אחד מהם ה-Map נשאר ריק. אם
// המזהה נצרך בקריאה, הוא נשרף על טעינה שנכשלה והכוונה אבודה לצמיתות —
// גם כשטעינה מאוחרת יותר הייתה מוצאת את הפתק.
//
// ולכן הכלל שנבדק כאן: **המזהה נצרך רק כשהפתק נמצא בפועל.**
//
// ההתקנה: sandbox של vm משלו, לפי המוסכמה בריפו. ``_maybeScrollToNoteFromUrl``
// נשענת רק על ``this.notes`` ועל ``this.scrollToNote``, ולכן היא נקראת כאן
// על אובייקט סטאב דרך ה-prototype — בלי להרכיב מנהל אמיתי.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'sticky-notes.js');
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
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}
const tick = () => new Promise((r) => setTimeout(r, 0));

function makeSandbox(href) {
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
      location: { href, hash: new URL(href).hash },
      addEventListener() {}, removeEventListener() {},
      innerWidth: 1024, innerHeight: 768,
      matchMedia: () => ({ matches: false }),
      getComputedStyle: () => ({}),
      localStorage: store,
      scrollTo() {},
    },
    document: {
      body: el(), documentElement: el(),
      getElementById: () => null, querySelector: () => null, querySelectorAll: () => [],
      createElement: () => el(),
      // ראו ההסבר ב-``sticky-notes-size-intent.test.js``: ``_createFab``
      // בונה את האייקון ב-``createElementNS``, וחריגה כאן נבלעת ב-``_init``.
      createElementNS: () => el(),
      addEventListener() {}, removeEventListener() {},
      dispatchEvent() { return true; },
    },
    localStorage: store,
    navigator: {},
    URL, URLSearchParams, TextEncoder,
    // **הרצה קדימה של הזמן.** לולאת הניסיונות היא 8 פעמים כל 200ms; בבדיקה
    // מעניין הרצף, לא ההמתנה. בלי זה הבדיקה על מסלול הכישלון הייתה לוקחת
    // 1.6 שניות רק כדי להגיע לנקודה שנבדקת.
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

const NOTE_ID = '6a8db3a3fa82385c8dccc5dd';
const HREF = `https://x.test/repo/?repo=amir-bug-patterns&note=${NOTE_ID}#file=INTEGRATION.md`;

/**
 * מנהל-סטאב היושב על ה-prototype האמיתי.
 *
 * ``Object.create`` ולא אובייקט ליטרלי: ``_maybeScrollToNoteFromUrl`` קוראת
 * ל-``this._parseNoteIdFromUrl()``, ולכן הסטאב חייב לרשת אותה. מה שנדרס
 * הוא בדיוק שני הדברים שהיא נוגעת בהם — ``notes`` ו-``scrollToNote``.
 */
function stubManager(sb, notes) {
  const proto = sb.window.StickyNotesManager.prototype;
  const m = Object.create(proto);
  m.scrolled = [];
  m.notes = notes || new Map();
  m.scrollToNote = (id) => { m.scrolled.push(String(id)); };
  m.run = () => proto._maybeScrollToNoteFromUrl.call(m);
  m.read = () => proto._parseNoteIdFromUrl.call(m);
  return m;
}
const withNote = () => new Map([[NOTE_ID, { el: {}, data: { id: NOTE_ID } }]]);

// -- הרגרסיה: טעינה שנכשלה לא שורפת את הכוונה --

check('טעינה שנכשלה אינה מאבדת את מזהה הפתק', async () => {
  // ``loadNotes`` נכשלה, ולכן ה-Map ריק וכל שמונת הניסיונות מחטיאים. הכוונה
  // חייבת לשרוד כדי שטעינה מוצלחת אחריה עדיין תגלול לפתק.
  //
  // נופל אם ``_parseNoteIdFromUrl`` מרוקנת את המזהה בקריאה.
  const sb = makeSandbox(HREF);

  const failed = stubManager(sb, new Map());   // הטעינה נכשלה — אין פתקים
  failed.run();
  await tick(); await tick();
  eq(failed.scrolled.length, 0, 'אין למה לגלול');

  const loaded = stubManager(sb, withNote());  // הטעינה הבאה הצליחה
  loaded.run();
  await tick(); await tick();
  eq(loaded.scrolled.join(','), NOTE_ID, 'והפעם נגלל לפתק הנכון');
});

// -- הצריכה, כשהיא כן מתרחשת --

check('המזהה נצרך רק אחרי שהפתק נמצא', async () => {
  const sb = makeSandbox(HREF);
  const m = stubManager(sb, withNote());

  eq(m.read(), NOTE_ID, 'קריאה בלבד אינה צורכת');
  eq(m.read(), NOTE_ID, 'וגם קריאה שנייה מחזירה אותו');

  m.run();
  await tick(); await tick();
  eq(m.scrolled.join(','), NOTE_ID, 'נגלל');
  eq(m.read(), '', 'ואחרי הגלילה המזהה נצרך');
});

check('אחרי גלילה מוצלחת, מנהל נוסף אינו גולל שוב', async () => {
  // בלי הצריכה בנקודת ההתאמה, כל מנהל שיורכב אחר כך על אותו קובץ היה גולל
  // מחדש — כלומר הכוונה הייתה חוזרת על עצמה במקום להתממש פעם אחת.
  const sb = makeSandbox(HREF);

  const first = stubManager(sb, withNote());
  first.run();
  await tick(); await tick();
  eq(first.scrolled.length, 1, 'הראשון גלל');

  const second = stubManager(sb, withNote());
  second.run();
  await tick(); await tick();
  eq(second.scrolled.length, 0, 'והשני כבר לא');
});

// -- מה שכבר עבד, ונשמר --

check('URL בלי note אינו מייצר כוונה', async () => {
  const sb = makeSandbox('https://x.test/repo/#file=INTEGRATION.md');
  const m = stubManager(sb, withNote());
  eq(m.read(), '', 'אין מזהה');
  m.run();
  await tick(); await tick();
  eq(m.scrolled.length, 0, 'ולכן אין גלילה');
});

check('הצורה #note=ID בהאש נתמכת גם היא', async () => {
  // צורה שנתמכה מאז ומתמיד ב-``_parseNoteIdFromUrl``; הלכידה בטעינה
  // חייבת לשמר אותה.
  const sb = makeSandbox(`https://x.test/md/7#note=${NOTE_ID}`);
  const m = stubManager(sb, withNote());
  eq(m.read(), NOTE_ID, 'נלכד מה-hash');
});

// -- שרשור מהקישור (``?thread=``, מלחיצה על התראת תגובה) --
//
// נצרך באותה נקודת התאמה כמו ``?note=``. הסטאב דורס גם את ``_openThread`` —
// הפתיחה עצמה (חלונית, טעינה) נבדקת בדפדפן, ב-``test_note_threads_browser.py``.

const THREAD_ID = '64b7f1d2e3a4b5c6d7e8f901';
const HREF_THREAD = `https://x.test/repo/?repo=amir-bug-patterns&note=${NOTE_ID}&thread=${THREAD_ID}#file=INTEGRATION.md`;
const settle = async () => { for (let i = 0; i < 6; i += 1) await tick(); };

check('שרשור מהקישור נפתח פעם אחת, על הפתק שנמצא', async () => {
  const sb = makeSandbox(HREF_THREAD);
  const notes = withNote();
  const first = stubManager(sb, notes);
  first.opened = [];
  first._openThread = (el, threadId) => { first.opened.push([el, threadId]); };
  first.run();
  await settle();
  eq(first.opened.length, 1, 'נפתח שרשור אחד');
  eq(first.opened[0][0], notes.get(NOTE_ID).el, 'על הפתק מהקישור');
  eq(first.opened[0][1], THREAD_ID, 'והשרשור מהקישור');

  const second = stubManager(sb, withNote());
  second.opened = [];
  second._openThread = (el, threadId) => { second.opened.push([el, threadId]); };
  second.run();
  await settle();
  eq(second.opened.length, 0, 'והכוונה נצרכה — מנהל נוסף אינו פותח שוב');
});

check('כשל בפתיחת השרשור אינו גולל שוב לפתק, ונרשם', async () => {
  // הניסיון החוזר נועד לפתק שעוד לא נטען. חריגה מפתיחת השרשור, אחרי שהפתק כבר
  // נמצא, הייתה נבלעת ב-``catch`` של הניסיון ומפעילה ניסיון נוסף — קריאה שנייה
  // ל-``scrollToNote``, ובלי שום עקבה למה השרשור לא נפתח.
  //
  // נופל אם ``_openThread`` אינה עטופה ב-``try`` משלה בתוך ``_maybeScrollToNoteFromUrl``.
  const sb = makeSandbox(HREF_THREAD);
  const warns = [];
  sb.console.warn = (...args) => { warns.push(args); };
  const m = stubManager(sb, withNote());
  m._openThread = () => { throw new Error('boom'); };
  m.run();
  await settle();
  eq(m.scrolled.length, 1, 'הגלילה לפתק קרתה פעם אחת');
  eq(warns.length, 1, 'והכשל נרשם');
  eq(warns[0][0], 'sticky note: opening the linked thread failed', 'בהודעה שמזהה אותו');
  eq(warns[0][1], THREAD_ID, 'עם מזהה השרשור');
});

await Promise.all(pending);
console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
