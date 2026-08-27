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
      // **מתעד ולא מתעלם.** בדיקת הסיבוב חייבת לירות את אותו מאזין
      // שהקוד רשם בפועל — בדיקה שקוראת ישירות לפונקציה הפנימית הייתה
      // עוברת גם אם החיווט לאירוע נשבר, וזה בדיוק מה שהיה שבור.
      addEventListener(type, fn) {
        (sandbox.__listeners[type] || (sandbox.__listeners[type] = [])).push(fn);
      },
      removeEventListener() {},
      innerWidth: 1024, innerHeight: 768,
      matchMedia: () => ({ matches: false }),
      location: { search: '', hash: '' },
      // ה-``visualViewport`` הוא מסלול נפרד: הקוד רושם עליו מאזינים משלו,
      // והוא — לא ``innerWidth`` — מה שמשתנה בפינץ'-זום ובפתיחת מקלדת.
      visualViewport: {
        width: 1024, height: 768,
        addEventListener(type, fn) {
          (sandbox.__vvListeners[type] || (sandbox.__vvListeners[type] = [])).push(fn);
        },
        removeEventListener() {},
      },
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: async () => ({ json: async () => ({ ok: true, notes: [] }) }),
    HTMLElement: function HTMLElement() {},
    setTimeout, clearTimeout, setInterval, clearInterval,
    MutationObserver: undefined, ResizeObserver: undefined,
    __listeners: {},
    __vvListeners: {},
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

/**
 * מריץ עם אזור תצוגה אחר.
 *
 * ``_viewportBox`` מעדיף את ``visualViewport`` על פני ``innerWidth``, ולכן
 * בדיקה ששינתה רק את ``innerWidth`` הריצה בפועל את גודל ברירת המחדל —
 * ועברה או נפלה מסיבה שאינה זו שנבדקה.
 */
function withViewport(width, height, fn) {
  const w = sandbox.window, vv = w.visualViewport;
  const prev = { iw: w.innerWidth, ih: w.innerHeight, vw: vv.width, vh: vv.height };
  w.innerWidth = width; vv.width = width;
  if (height != null) { w.innerHeight = height; vv.height = height; }
  try { return fn(); }
  finally { w.innerWidth = prev.iw; w.innerHeight = prev.ih; vv.width = prev.vw; vv.height = prev.vh; }
}

/**
 * מריץ כששני מקורות הרוחב **חלוקים** זה על זה.
 *
 * ``withViewport`` מצמיד את ``innerWidth`` ואת ``visualViewport.width``
 * לאותו ערך — נכון לבדיקה שרק רוצה "אזור התצוגה הוא עכשיו N", ועיוור
 * לחלוטין בבדיקה ששואלת **איזה מהם נקרא**. עם שני מקורות שווים, קוד
 * שיחליף ביניהם מחזיר בדיוק אותו מספר וההצהרה עוברת מסיבה שאינה זו
 * שנטענת.
 */
function withSplitViewport(innerWidth, vvWidth, fn) {
  const w = sandbox.window, vv = w.visualViewport;
  const prev = { iw: w.innerWidth, vw: vv.width };
  w.innerWidth = innerWidth; vv.width = vvWidth;
  try { return fn(); }
  finally { w.innerWidth = prev.iw; vv.width = prev.vw; }
}

/** מריץ כש-``visualViewport`` אינו קיים כלל — ענף הנפילה של ``_viewportBox``. */
function withoutVisualViewport(fn) {
  const w = sandbox.window;
  const prev = w.visualViewport;
  w.visualViewport = undefined;
  try { return fn(); }
  finally { w.visualViewport = prev; }
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

// ─── קדימות אחת לגודל, בכל ארבע נקודות השאילה ──────────────────────────
//
// **למה זה בדיקה ולא ניקיון.** ארבע נקודות שואלות "מה הרוחב של הפתק
// הזה" — שתיים ב-``_applyPositionMode``, ``_clampToSurface``
// ו-``_reflowWithinViewport``. כל אחת ענתה בסדר משלה, ושתיים מהן היו
// הפוכות זו לזו: אחת העדיפה את הכוונה שעל האלמנט, השנייה את ``note.size``.
// סדר שונה לאותה שאלה אינו "כפילות סגנונית": ההצמדה מחשבת כמה מקום נשאר
// לפי רוחב אחד בזמן שהתצוגה כותבת רוחב אחר, והפתק נצמד למקום שנכון
// לגודל שאינו הגודל שיוצג.

check('הכוונה שעל האלמנט גוברת על note.size', () => {
  // ``_enableResize`` הוא הכותב היחיד של הכוונה, והוא מעדכן אותה **לפני**
  // שהשמירה יוצאת. ``note.size`` הוא הערך שהגיע מה-DB.
  const el = noteEl({ rect: { width: 300, height: 200 }, intent: { width: 600, height: 400 } });
  const r = mgr._resolveDisplaySize(el, { size: { width: 260, height: 200 } }, { width: 1000 });
  eq(r.intent.width, 600, 'רוחב הכוונה');
  eq(r.fitted.width, 600, 'רוחב מוצג');
});

check('בלי כוונה — note.size', () => {
  const el = noteEl({ rect: { width: 300, height: 200 } });
  const r = mgr._resolveDisplaySize(el, { size: { width: 640, height: 480 } }, { width: 1000 });
  eq(r.intent.width, 640, 'רוחב');
  eq(r.intent.height, 480, 'גובה');
});

check('בלי כוונה ובלי note.size — el.style, ואז המלבן', () => {
  const el = noteEl({ rect: { width: 333, height: 222 } });
  el.style.width = '410px';
  const r = mgr._resolveDisplaySize(el, null, { width: 1000 });
  eq(r.intent.width, 410, 'רוחב מ-style');
  eq(r.intent.height, 222, 'גובה מהמלבן');
});

check('אין שום מקור — ברירות המחדל, ולא המינימום', () => {
  // הבאג שזה מגן מפניו: ``_fitSizeToBounds(null, …)`` מחזירה 120×80, ולכן
  // אתר שהעביר לה ``null`` היה מכווץ פתק תקין לגודם. בענף המשטח זה קרה
  // בפועל לכל פתק בלי כוונה ובלי ``note.size``.
  const el = noteEl({ rect: { width: 0, height: 0 } });
  const r = mgr._resolveDisplaySize(el, null, { width: 1000 });
  eq(r.intent.width, 260, 'רוחב');
  eq(r.intent.height, 200, 'גובה');
});

check('ארבע נקודות השאילה מחזירות את אותו רוחב לאותו פתק', () => {
  // התרחיש שהפריד ביניהן: הכוונה 600, ו-``note.size`` תקוע על 260.
  // ``_clampToSurface`` העדיף את 260 ו-``_applyPositionMode`` את 600.
  const m = new StickyNotesManager({ board: 'b-precedence', container: surfaceStub(400) });
  const note = { size: { width: 260, height: 200 } };
  const el = noteEl({ rect: { width: 300, height: 200 }, intent: { width: 600, height: 400 } });
  const viaResolver = m._resolveDisplaySize(el, note, { width: 400 }).fitted.width;
  eq(viaResolver, 400, 'הרוחב המוצג במשטח ברוחב 400');
  // ``_clampToSurface`` נגזר מאותו מספר: ``maxX`` הוא הרוחב שנשאר.
  const clamped = m._clampToSurface(el, 9999, 0, note);
  eq(clamped.x, 400 - viaResolver, 'x המקסימלי נגזר מאותו רוחב');
});

// ─── סיבוב המכשיר: פתק משטח שכבר נטען ──────────────────────────────────

/** משטח לוח מדומה שרוחבו ניתן לשינוי — "סיבוב". */
function surfaceStub(width) {
  return {
    clientWidth: width,
    style: {},
    dataset: {},
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    appendChild() {}, addEventListener() {}, removeEventListener() {},
    querySelectorAll: () => [], querySelector: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, width, height: 600 }),
  };
}

/** פתק נעוץ למשטח, עם ``classList`` אמיתי — הלולאה מסננת לפיו. */
function pinnedEl(intent) {
  const classes = new Set(['sticky-note', 'is-pinned']);
  return {
    style: {},
    dataset: { noteId: 'n-rot', userWidth: String(intent.width), userHeight: String(intent.height) },
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c), toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
    },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: intent.width, height: intent.height }),
    querySelector: () => null, querySelectorAll: () => [],
    setAttribute() {}, getAttribute: () => null,
  };
}

// הבנאי יורה ``_init() → loadNotes()`` ברקע, וכשהיא נפתרת היא קוראת
// ``_clearAllNotes()``. לכן ממתינים **לפני** רישום הפתק הידני, אחרת הוא
// נמחק ב-microtask הראשון והבדיקה רצה על מפה ריקה — מוקש שכבר תועד
// ב-``sticky-notes-target.test.js``.
await new Promise((resolve) => setTimeout(resolve, 0));

// ההכנה מחוץ ל-``check``: ``check`` הוא סינכרוני, ופונקציה אסינכרונית
// בתוכו הייתה מחזירה promise שנכשל בשקט — כלומר בדיקה שעוברת תמיד.

/** בונה מנהל לוח ופתק נעוץ, ומחזיר את המאזינים שנרשמו בפועל. */
async function rotatingBoard(boardId, startWidth) {
  const surface = surfaceStub(startWidth);
  sandbox.__listeners.resize = [];
  const m = new StickyNotesManager({ board: boardId, container: surface });
  await new Promise((resolve) => setTimeout(resolve, 0));
  const handlers = (sandbox.__listeners.resize || []).slice();
  const el = pinnedEl({ width: 600, height: 400 });
  m.notes.set('n-rot', { el, data: { id: 'n-rot', anchor_id: '__pinned__',
                                     position: { x: 0, y: 0 },
                                     size: { width: 600, height: 400 } } });
  return { m, el, surface, fire: () => handlers.forEach((fn) => fn()), handlers };
}

const rotateIn = await rotatingBoard('b-rotate', 900);
const rotateBack = await rotatingBoard('b-rotate-back', 320);

check('סיבוב מצמצם פתק משטח שכבר היה על המסך', () => {
  // **התסמין המקורי.** לוח נטען במסך רחב, המכשיר מסתובב לצר: הפתק נשאר
  // ברוחבו הישן, גולש מעבר לקצה, והידית שלו יוצאת מהמסך.
  //
  // ``_reflowWithinViewport`` — היחיד שהיה מחובר ל-``resize`` — מדלג על
  // ``is-pinned`` בכוונה, כי המיקום שם נמדד במרחב המשטח ולא במסך. לכן
  // בלי מסלול נפרד לפתקי משטח, שינוי גבולות פשוט לא הגיע אליהם.
  eq(rotateIn.handlers.length > 0, true, 'נרשם מאזין resize');
  rotateIn.surface.clientWidth = 320;   // סיבוב לטלפון
  rotateIn.fire();
  eq(rotateIn.el.style.width, '320px', 'הרוחב המוצג נכנס במשטח');
  eq(rotateIn.el.dataset.userWidth, '600', 'הכוונה לא נדרסה');
});

check('סיבוב חזרה למסך רחב מחזיר את הפתק לגודל שנקבע', () => {
  rotateBack.fire();
  eq(rotateBack.el.style.width, '320px', 'צר');
  rotateBack.surface.clientWidth = 1200;  // חזרה לטאבלט
  rotateBack.fire();
  eq(rotateBack.el.style.width, '600px', 'חזר לגודל שנקבע');
});

// ─── הענף הצף ──────────────────────────────────────────────────────────

check('פתק צף רחב מצטמצם בענף עצמו, ולא רק ב-reflow שאחריו', () => {
  // הענף הצף לא התייעץ בכוונה כלל ולא צמצם דבר: הוא חישב ``maxLeft``
  // מהרוחב הלא-מצומצם וכיסה על כך רק בזכות ``_reflowWithinViewport``
  // שרץ אחריו. עם ``reflow: false`` — שלושה אתרים בקוד קוראים כך —
  // הגודל פשוט לא נגע.
  const m = new StickyNotesManager({ board: 'b-float', container: surfaceStub(420) });
  const classes = new Set(['sticky-note']);
  const el = {
    style: {}, dataset: { noteId: 'nf' },
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c), toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
    },
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 600, height: 300 }),
    querySelector: () => null, querySelectorAll: () => [],
  };
  const note = { id: 'nf', anchor_id: '__floating__',
                 position: { x: 40, y: 100 }, size: { width: 600, height: 300 } };
  withViewport(420, null, () => m._applyPositionMode(el, note, { reflow: false }));
  eq(el.style.width, '396px', 'הרוחב המוצג — 420 פחות שוליים משני הצדדים');
  eq(el.classList.contains('is-floating'), true, 'אכן הענף הצף');
});

// ─── המצב המעוגן ───────────────────────────────────────────────────────
//
// **המצב השלישי, שלא הייתה לו מדיניות גודל בכלל.** הענף המעוגן מוסיף
// ``is-pinned``, כותב ``left``, ויוצא — ולכן ``_reflowWithinViewport``
// מדלג עליו (הוא מדלג על ``is-pinned``) ואף אחד אחר לא נגע בו.
// ``_renderNote`` כותב 600px ל-``el.style.width``, וב-CSS אין
// ``max-width`` על ``.sticky-note``. פתק מעוגן ברוחב 600 על מסך 320
// גלש מהרגע הראשון, לא רק אחרי סיבוב.

/** מנהל קובץ עם מארח עוגנים — התנאי ש-``_resolveMode`` דורש למצב anchored. */
function anchoredManager(fileId) {
  const host = {
    style: {}, dataset: {},
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    appendChild() {}, addEventListener() {}, removeEventListener() {},
    querySelector: () => null, querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 2000 }),
  };
  return new StickyNotesManager({ file: fileId, anchorHost: host });
}

function anchoredEl(width, height) {
  const classes = new Set(['sticky-note']);
  return {
    style: { top: '500px' }, dataset: { noteId: 'na' },
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c), toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
    },
    getBoundingClientRect: () => ({ left: 0, top: 500, width, height }),
    querySelector: () => null, querySelectorAll: () => [],
  };
}

check('פתק מעוגן מצטמצם לרוחב אזור התצוגה', () => {
  const m = anchoredManager('f-anchored');
  const el = anchoredEl(600, 400);
  const note = { id: 'na', anchor_id: 'a1', position: { x: 0, y: 500 },
                 size: { width: 600, height: 400 } };
  withViewport(320, null, () => {
    eq(m._resolveMode(note), 'anchored', 'אכן המצב המעוגן');
    m._applyPositionMode(el, note, { reflow: false });
  });
  eq(el.style.width, '296px', 'רוחב — 320 פחות שוליים משני הצדדים');
  eq(el.dataset.userWidth, undefined, 'הכוונה לא נכתבה כאן');
});

check('פתק מעוגן — ה-top שלו אינו מוצמד לאזור התצוגה', () => {
  // ה-``top`` נגזר מהעוגן ב-``_updateAnchoredNotePosition``. הצמדתו
  // לאזור התצוגה הייתה מנתקת את הפתק מהשורה שהוא מצביע עליה — וזו בדיוק
  // הסיבה ש-``_reflowWithinViewport`` מדלג על ``is-pinned`` מלכתחילה.
  const m = anchoredManager('f-anchored-top');
  const el = anchoredEl(600, 400);
  const note = { id: 'na', anchor_id: 'a1', position: { x: 0, y: 500 },
                 size: { width: 600, height: 400 } };
  withViewport(320, 400, () => m._applyPositionMode(el, note, { reflow: false }));
  eq(el.style.top, '500px', 'ה-top נשאר כפי שהיה');
});

check('פתק מעוגן — X מוצמד כך שהוא נכנס', () => {
  const m = anchoredManager('f-anchored-x');
  const el = anchoredEl(600, 400);
  const note = { id: 'na', anchor_id: 'a1', position: { x: 9999, y: 500 },
                 size: { width: 600, height: 400 } };
  withViewport(320, null, () => m._applyPositionMode(el, note, { reflow: false }));
  eq(el.style.left, '12px', 'הוצמד לגבול שנגזר מהרוחב המצומצם');
});

// ─── מקור אחד גם למה שנעשה עם הגודל, ולא רק לגודל עצמו ────────────────

check('הענף הצף וה-reflow מגיעים לאותה תוצאה', () => {
  // אחרי הסבב הקודם שניהם הריצו את אותו רצף בדיוק — אותם גבולות, אותו
  // clamp, אותן ארבע כתיבות — וההערה בקוד ביקשה לשמור עליהם מסונכרנים.
  // בדיקה שמשווה את שתי התוצאות הופכת את הסנכרון למאוכף במקום מבוקש.
  const mk = () => {
    const classes = new Set(['sticky-note']);
    return {
      style: { left: '40px', top: '100px' }, dataset: { noteId: 'nf' },
      classList: {
        add: (c) => classes.add(c), remove: (c) => classes.delete(c),
        contains: (c) => classes.has(c), toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
      },
      getBoundingClientRect: () => ({ left: 40, top: 100, width: 600, height: 300 }),
      querySelector: () => null, querySelectorAll: () => [],
    };
  };
  const note = { id: 'nf', anchor_id: '__floating__',
                 position: { x: 40, y: 100 }, size: { width: 600, height: 300 } };

  const viaBranch = new StickyNotesManager({ board: 'b-cmp-a', container: surfaceStub(420) });
  const elBranch = mk();
  const viaReflow = new StickyNotesManager({ board: 'b-cmp-b', container: surfaceStub(420) });
  // ``_reflowWithinViewport`` מסנן ב-``instanceof HTMLElement``, ולכן סטאב
  // שאינו יורש ממנו מדולג בשקט — והבדיקה הייתה משווה שתי אי-כתיבות.
  const elReflow = Object.setPrototypeOf(mk(), sandbox.HTMLElement.prototype);
  viaReflow.notes.set('nf', { el: elReflow, data: note });

  withViewport(420, null, () => {
    viaBranch._applyPositionMode(elBranch, note, { reflow: false });
    elReflow.classList.add('is-floating');
    viaReflow._reflowWithinViewport(elReflow);
  });

  eq(elBranch.style.width, elReflow.style.width, 'רוחב');
  eq(elBranch.style.height, elReflow.style.height, 'גובה');
  eq(elBranch.style.left, elReflow.style.left, 'left');
  eq(elBranch.style.top, elReflow.style.top, 'top');
});

// ─── ‏visualViewport: פינץ'-זום ומקלדת ─────────────────────────────────
//
// **מסלול שני, לא אותו מסלול.** ``window.resize`` ו-``visualViewport``
// הם שני אירועים שונים: הראשון על שינוי החלון, השני על שינוי החלון
// ה**נראה** — פינץ'-זום, פתיחת מקלדת. הרוחב של פתק מעוגן נגזר
// מ-``_viewportBox()``, שקורא את ``visualViewport`` כשהוא קיים — ולכן
// המסלול הזה חייב לרענן אותו בדיוק כמו הראשון.
//
// זו לא הייתה בעיה כשרק פתקי משטח היו מצומצמים: הרוחב שלהם נגזר
// מ-``parent.clientWidth``, שפינץ'-זום אינו משנה. היא נולדה עם הענף
// המעוגן.

const vvAnchored = await (async () => {
  const host = {
    style: {}, dataset: {},
    classList: { add() {}, remove() {}, contains: () => false, toggle() {} },
    appendChild() {}, addEventListener() {}, removeEventListener() {},
    querySelector: () => null, querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 800, height: 2000 }),
  };
  sandbox.__vvListeners.resize = [];
  const m = new StickyNotesManager({ file: 'f-vv', anchorHost: host });
  // ``_init`` רץ ברקע ורק הוא רושם את המאזינים — בלי ההמתנה הרשימה ריקה
  // והבדיקה הייתה "עוברת" על אפס מאזינים.
  await new Promise((resolve) => setTimeout(resolve, 0));
  const handlers = (sandbox.__vvListeners.resize || []).slice();
  const el = anchoredEl(600, 400);
  const note = { id: 'na', anchor_id: 'a1', position: { x: 0, y: 500 },
                 size: { width: 600, height: 400 } };
  m.notes.set('na', { el, data: note });
  m._applyPositionMode(el, note, { reflow: false });   // רינדור ראשוני
  return { m, el, handlers, fire: () => handlers.forEach((fn) => fn()) };
})();

check('שינוי visualViewport מרענן את הרוחב של פתק מעוגן', () => {
  eq(vvAnchored.handlers.length > 0, true, 'נרשם מאזין ל-visualViewport');
  eq(vvAnchored.el.style.width, '600px', 'רוחב התחלתי — נכנס ב-1024, ולכן לא צומצם');
  withViewport(320, null, () => vvAnchored.fire());   // פינץ'-זום / מקלדת
  eq(vvAnchored.el.style.width, '296px', 'הרוחב התעדכן למסך הנראה החדש');
});

// ─── בעלים אחד לגבולות אזור התצוגה ─────────────────────────────────────

check('‏_clampToViewport נגזר מאותו מקור כמו _viewportBox', () => {
  // אין הבדל התנהגותי בין שני עותקים זהים — וזו בדיוק הסיבה שהם נסחפים
  // בשקט. הבדיקה נועלת אותם זה לזה.
  //
  // **שני המקורות חייבים להיות חלוקים.** ``visualViewport.width`` הוא
  // הנכון ו-``innerWidth`` הוא המלכודת: כשהם שווים, קוד שקורא את הלא-נכון
  // מחזיר אותו מספר, והבדיקה מאשרת סחיפה במקום לתפוס אותה.
  const m = new StickyNotesManager({ board: 'b-vpbox', container: surfaceStub(400) });
  const el = noteEl({ rect: { width: 200, height: 100 } });
  const { box, clamped } = withSplitViewport(600, 500, () => ({
    box: m._viewportBox(),
    clamped: m._clampToViewport(el, 99999, 100),
  }));
  eq(box.width, 500, '‏_viewportBox העדיף את visualViewport על פני innerWidth');
  eq(clamped.x, 500 - 200 - 12, '‏_clampToViewport נגזר מאותו מקור — 600 היה הכישלון');
});

check('בלי visualViewport — נפילה ל-innerWidth, בשני המסלולים', () => {
  // הענף השני של ``_viewportBox``, שאף בדיקה לא נגעה בו. הפונקציה היא
  // היום המקור היחיד לארבעה אתרים, ולכן גם הנפילה שלה שווה נעילה.
  const m = new StickyNotesManager({ board: 'b-novv', container: surfaceStub(400) });
  const el = noteEl({ rect: { width: 200, height: 100 } });
  // הסדר חשוב: withSplitViewport נוגע ב-visualViewport.width,
  // ולכן הוא חייב לרוץ לפני שהאובייקט עצמו מוסר.
  const { box, clamped } = withSplitViewport(700, 500, () =>
    withoutVisualViewport(() => ({
      box: m._viewportBox(),
      clamped: m._clampToViewport(el, 99999, 100),
    })));
  eq(box.width, 700, 'נפל ל-innerWidth');
  eq(clamped.x, 700 - 200 - 12, 'וגם ההצמדה נפלה לאותו מקור');
});

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
