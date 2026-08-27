/**
 * טסטים ל-webapp/static/js/sticky-notes.js — התאמת פתק לגבולות המסך.
 *
 * הרצה:  node tests/sticky-notes-viewport-fit.test.js
 * (אין ברפו runner ל-JS, ולכן הקובץ עצמאי ומחזיר קוד יציאה 1 בכישלון —
 *  אותה תבנית כמו tests/sticky-notes-target.test.js.)
 *
 * **מה נבדק כאן.** מיקום וגודל של פתק נשמרים בפיקסלים מוחלטים, ולכן פתק
 * שנוצר על מסך רחב חוצה את הגבול כשמציגים אותו על מסך צר — בסיבוב מכשיר,
 * במעבר טאבלט←טלפון, ובפתיחה מפוש על מכשיר אחר. שלושת התסמינים הם אותו
 * שורש, והבדיקות כאן מכסות אותו בשלושת סוגי הפתקים: לוח, קובץ, וקובץ
 * בריפו הממורר.
 *
 * **החוזה שהקובץ הזה מגן עליו** הוא ההפרדה בין שתי שכבות:
 *   ``entry.data.size``/``position``  — הכוונה של המשתמש. נשמרת במסד.
 *   ``el.style.*``                    — מה שמוצג. נגזר בזמן ריצה מהכוונה.
 * ההקטנה למסך צר חיה בשכבה השנייה בלבד, ולעולם אינה זולגת לראשונה —
 * אחרת חזרה למכשיר הרחב הייתה מציגה את הגודל של הטלפון.
 *
 * **הרצה מול הקוד הישן** (בדיקת מוטציה — הבדיקה חייבת ליפול בלעדיו):
 *   git show HEAD:webapp/static/js/sticky-notes.js > /tmp/old-sticky.js
 *   STICKY_NOTES_SRC=/tmp/old-sticky.js node tests/sticky-notes-viewport-fit.test.js
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
//: ברירת המחדל היא המקור שבריפו; העקיפה קיימת רק כדי להריץ את אותן
//: בדיקות מול גרסה קודמת של הקובץ ולוודא שהן נופלות שם.
const MODULE_PATH = process.env.STICKY_NOTES_SRC
  || path.join(__dirname, '..', 'webapp', 'static', 'js', 'sticky-notes.js');

// ── DOM מזויף, עשיר מספיק כדי שהמיקום יהיה בר-מדידה ─────────────────────

/**
 * ``classList`` אמיתי ולא בובה.
 *
 * ``_applyPositionMode`` מסתעף על ``contains('is-pinned')``, ו-
 * ``_reflowWithinViewport`` מדלג לפיו. בובה שמחזירה ``false`` תמיד הייתה
 * מריצה את הענף הלא נכון ומדווחת "עבר".
 */
function makeClassList() {
  const set = new Set();
  return {
    add: (c) => set.add(c),
    remove: (c) => set.delete(c),
    contains: (c) => set.has(c),
    toggle: (c, on) => (on ? set.add(c) : set.delete(c)),
    _set: set,
  };
}

/**
 * אלמנט פתק שה-``getBoundingClientRect`` שלו **נגזר מה-style**.
 *
 * זו הנקודה שבלעדיה הבדיקה חסרת ערך: כל החישוב בקוד עובר בין ``style``
 * למדידה וחזרה, ומלבן קבוע היה מנתק את שני הצדדים זה מזה.
 *
 * ``originX``/``originY`` הם ראשית המרחב שבו ``left``/``top`` נמדדים —
 * אפס בכל המקרים שנבדקים כאן, בדיוק כמו קונטיינר שיושב בראש המסמך.
 */
function makeNoteEl(sandbox, id, opts) {
  const o = opts || {};
  const originX = o.originX || 0;
  const originY = o.originY || 0;
  const el = {
    style: {},
    dataset: { noteId: id },
    classList: makeClassList(),
    querySelector: () => null,
    querySelectorAll: () => [],
    setAttribute() {},
    getAttribute: () => null,
    addEventListener() {},
    removeEventListener() {},
    appendChild() {},
    getBoundingClientRect() {
      const num = (v, dflt) => {
        const n = parseInt(v || '', 10);
        return Number.isFinite(n) ? n : dflt;
      };
      const left = originX + num(el.style.left, 0);
      const top = originY + num(el.style.top, 0);
      const width = num(el.style.width, 0);
      const height = num(el.style.height, 0);
      return { left, top, width, height, right: left + width, bottom: top + height };
    },
  };
  // ``_reflowWithinViewport`` בודק ``instanceof HTMLElement`` ויוצא מוקדם
  // אם הבדיקה נכשלת — כלומר בובה פשוטה הייתה מדווחת "עבר" בלי שהפונקציה
  // רצה בכלל. השרשור לפרוטוטיפ שבתוך ה-sandbox מעביר את הבדיקה הזו.
  Object.setPrototypeOf(el, sandbox.HTMLElement.prototype);
  return el;
}

function makeSandbox(screenW, screenH) {
  const tracking = () => ({ addEventListener() {}, removeEventListener() {} });
  const plain = () => ({
    style: {}, dataset: {}, classList: makeClassList(),
    appendChild() {}, ...tracking(), querySelectorAll: () => [], querySelector: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0, right: 0, bottom: 0 }),
    setAttribute() {}, getAttribute: () => null,
  });
  const body = plain();
  const docEl = plain();
  docEl.clientWidth = screenW;
  docEl.clientHeight = screenH;
  docEl.scrollTop = 0;
  docEl.scrollLeft = 0;
  body.scrollTop = 0;
  body.scrollLeft = 0;
  const sandbox = {
    console,
    document: {
      body,
      documentElement: docEl,
      scrollingElement: docEl,
      getElementById: () => null,
      createElement: () => plain(),
      ...tracking(),
      querySelectorAll: () => [],
      get activeElement() { return null; },
    },
    window: {
      ...tracking(),
      innerWidth: screenW,
      innerHeight: screenH,
      pageXOffset: 0,
      pageYOffset: 0,
      scrollX: 0,
      scrollY: 0,
      matchMedia: () => ({ matches: false }),
      location: { search: '', hash: '' },
      visualViewport: null,
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: async () => ({ json: async () => ({ ok: true, notes: [] }) }),
    HTMLElement: function HTMLElement() {},
    // ``screen.orientation`` — המנהל נרשם עליו אם קיים. כאן הוא קיים כדי
    // שהענף ירוץ בבדיקות ולא יישאר קוד מת שאיש לא הפעיל.
    screen: { orientation: { ...tracking(), type: 'portrait-primary', angle: 0 } },
    setTimeout, clearTimeout, setInterval, clearInterval,
    MutationObserver: undefined, ResizeObserver: undefined,
  };
  sandbox.window.document = sandbox.document;
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox;
}

/** משטח לוח/ריפו — קונטיינר ממוקם שיושב בראש המסך וברוחב המסך. */
function makeSurface(width, height) {
  return {
    style: {},
    clientWidth: width,
    clientHeight: height,
    clientLeft: 0,
    clientTop: 0,
    scrollLeft: 0,
    scrollTop: 0,
    appendChild() {},
    addEventListener() {},
    removeEventListener() {},
    querySelectorAll: () => [],
    querySelector: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, width, height, right: width, bottom: height }),
  };
}

// ── תשתית בדיקה ────────────────────────────────────────────────────────

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

function atMost(actual, limit, what) {
  if (!(actual <= limit)) {
    throw new Error(`${what || ''} — ציפיתי ל-<= ${limit}, קיבלתי ${actual}`);
  }
}

function atLeast(actual, limit, what) {
  if (!(actual >= limit)) {
    throw new Error(`${what || ''} — ציפיתי ל->= ${limit}, קיבלתי ${actual}`);
  }
}

const px = (v) => {
  const n = parseInt(v || '', 10);
  if (!Number.isFinite(n)) throw new Error(`ערך style חסר או לא מספרי: ${JSON.stringify(v)}`);
  return n;
};

/**
 * בונה מנהל עם פתק אחד שכבר "נטען מהמסד", ומחזיר את שניהם.
 *
 * הפתק מקבל ב-``style`` את הכוונה כפי ש-``_renderNote`` כותב אותה — כך
 * שקוד שאינו מתאים אותו לגבולות פשוט משאיר את הערכים האלה, וזה בדיוק מה
 * שהבדיקה תופסת.
 */
function mount(sandbox, opts, noteData) {
  const Manager = sandbox.window.StickyNotesManager;
  const m = new Manager(opts);
  const el = makeNoteEl(sandbox, noteData.id);
  el.style.left = noteData.position.x + 'px';
  el.style.top = noteData.position.y + 'px';
  el.style.width = noteData.size.width + 'px';
  el.style.height = noteData.size.height + 'px';
  m.notes.set(noteData.id, { el, data: noteData });
  return { m, el };
}

const TABLET = { w: 1024, h: 768 };
const PHONE_PORTRAIT = { w: 390, h: 844 };
const PHONE_LANDSCAPE = { w: 844, h: 390 };

/** פתק גדול כפי שנוצר בטאבלט: רחב מהטלפון וגבוה מהטלפון-לרוחב. */
function bigNote(id, mode) {
  return {
    id,
    mode,
    position: { x: 200, y: 300 },
    size: { width: 700, height: 620 },
  };
}

// ── 1. לוח: פתק גדול מטאבלט, נפתח בטלפון ────────────────────────────────

check('לוח — פתק שנוצר בטאבלט נכנס בגבולות הטלפון', () => {
  const sb = makeSandbox(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const surface = makeSurface(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const note = bigNote('n1', 'surface');
  const { m, el } = mount(sb, { board: 'b1', container: surface, anchorHost: null }, note);

  m._applyPositionMode(el, note, { reflow: false });

  atMost(px(el.style.width), PHONE_PORTRAIT.w, 'רוחב מוצג');
  atMost(px(el.style.left) + px(el.style.width), PHONE_PORTRAIT.w, 'הקצה הימני');
  atLeast(px(el.style.left), 0, 'הקצה השמאלי');
  // הכותרת (ידית הגרירה) חייבת להישאר בתוך המשטח, אחרת אין דרך לגרור בחזרה
  atLeast(px(el.style.top), 0, 'הקצה העליון');
});

check('לוח — הכוונה לא נדרסה ע"י ההקטנה', () => {
  const sb = makeSandbox(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const surface = makeSurface(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const note = bigNote('n1', 'surface');
  const { m, el } = mount(sb, { board: 'b1', container: surface, anchorHost: null }, note);

  m._applyPositionMode(el, note, { reflow: false });

  eq(note.size.width, 700, 'userSize.width');
  eq(note.size.height, 620, 'userSize.height');
  eq(note.position.x, 200, 'userPosition.x');
  eq(note.position.y, 300, 'userPosition.y');
});

check('לוח — מה שנשמר הוא הכוונה, לא המוצג', () => {
  // זו הבדיקה שמונעת את הנזק האמיתי: פעולה שנעשית על הטלפון (נעיצה,
  // מעבר מצב) עוברת דרך ``_notePayloadFromEl``, וללא ההפרדה היא הייתה
  // כותבת את הגודל והמיקום המוקטנים בחזרה למסד — לתמיד.
  const sb = makeSandbox(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const surface = makeSurface(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const note = bigNote('n1', 'surface');
  const { m, el } = mount(sb, { board: 'b1', container: surface, anchorHost: null }, note);

  m._applyPositionMode(el, note, { reflow: false });
  const payload = m._notePayloadFromEl(el);

  eq(payload.size.width, 700, 'הגודל שנשמר');
  eq(payload.size.height, 620, 'הגובה שנשמר');
  eq(payload.position.x, 200, 'המיקום שנשמר');
  eq(payload.position.y, 300, 'המיקום האנכי שנשמר');
});

check('לוח — חזרה לטאבלט מציגה את הגודל המקורי', () => {
  const note = bigNote('n1', 'surface');

  // ביקור בטלפון
  const phone = makeSandbox(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const phoneSurface = makeSurface(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const a = mount(phone, { board: 'b1', container: phoneSurface, anchorHost: null }, note);
  a.m._applyPositionMode(a.el, note, { reflow: false });

  // ואז חזרה לטאבלט — אותו מסמך פתק בדיוק
  const tablet = makeSandbox(TABLET.w, TABLET.h);
  const tabletSurface = makeSurface(TABLET.w, TABLET.h);
  const b = mount(tablet, { board: 'b1', container: tabletSurface, anchorHost: null }, note);
  b.m._applyPositionMode(b.el, note, { reflow: false });

  eq(px(b.el.style.width), 700, 'רוחב בטאבלט');
  eq(px(b.el.style.height), 620, 'גובה בטאבלט');
  eq(px(b.el.style.left), 200, 'מיקום בטאבלט');
});

// ── 2. סיבוב מכשיר ──────────────────────────────────────────────────────

check('לוח — סיבוב לרוחב משאיר את הפתק בגבול', () => {
  const sb = makeSandbox(PHONE_LANDSCAPE.w, PHONE_LANDSCAPE.h);
  const surface = makeSurface(PHONE_LANDSCAPE.w, PHONE_LANDSCAPE.h);
  const note = { id: 'n1', mode: 'surface', position: { x: 700, y: 40 }, size: { width: 700, height: 620 } };
  const { m, el } = mount(sb, { board: 'b1', container: surface, anchorHost: null }, note);

  m._applyPositionMode(el, note, { reflow: false });

  atMost(px(el.style.left) + px(el.style.width), PHONE_LANDSCAPE.w, 'הקצה הימני אחרי סיבוב');
  atLeast(px(el.style.top), 0, 'הכותרת נשארה בתוך המשטח');
});

check('שינוי גבולות מריץ חישוב מחדש גם לפתקים נעוצים', () => {
  // ``_reflowWithinViewport`` מדלג על ``is-pinned``, ולכן לפני התיקון
  // סיבוב מכשיר לא נגע בפתקי לוח/ריפו/מעוגנים בכלל.
  const sb = makeSandbox(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const surface = makeSurface(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const note = bigNote('n1', 'surface');
  const { m, el } = mount(sb, { board: 'b1', container: surface, anchorHost: null }, note);
  el.classList.add('is-pinned');

  m._refitAll();

  atMost(px(el.style.width), PHONE_PORTRAIT.w, 'רוחב אחרי refit');
  atMost(px(el.style.left) + px(el.style.width), PHONE_PORTRAIT.w, 'הקצה הימני אחרי refit');
});

check('שינוי רוחב הקונטיינר מריץ התאמה מחדש, גם בקריאה שנייה', () => {
  // ``_refitAll`` מדלג כשהגבולות לא זזו, כדי לא להריץ מאות חישובי פריסה
  // בכל פתיחת מקלדת. השסתום הזה חייב **לא** לדלג כשהם כן זזו — אחרת
  // הוא הופך בעצמו לבאג שקט של סיבוב מכשיר.
  const sb = makeSandbox(TABLET.w, TABLET.h);
  const surface = makeSurface(TABLET.w, TABLET.h);
  const note = bigNote('n1', 'surface');
  const { m, el } = mount(sb, { board: 'b1', container: surface, anchorHost: null }, note);
  el.classList.add('is-pinned');

  m._refitAll();
  eq(px(el.style.width), 700, 'בטאבלט לא הוקטן');

  // סיבוב/מעבר מכשיר: רוחב הקונטיינר משתנה
  surface.clientWidth = PHONE_PORTRAIT.w;
  sb.window.innerWidth = PHONE_PORTRAIT.w;
  sb.document.documentElement.clientWidth = PHONE_PORTRAIT.w;
  m._refitAll();

  atMost(px(el.style.width), PHONE_PORTRAIT.w, 'הוקטן אחרי שינוי הרוחב');
});

check('רוחב שלא השתנה — הלולאה על הנעוצים מדולגת', () => {
  // הצד השני של אותו שסתום: פתיחת מקלדת משנה את גובה ה-viewport ולא את
  // רוחב הקונטיינר, ואין שום סיבה לגעת בפתקים הנעוצים.
  const sb = makeSandbox(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const surface = makeSurface(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const note = bigNote('n1', 'surface');
  const { m, el } = mount(sb, { board: 'b1', container: surface, anchorHost: null }, note);
  el.classList.add('is-pinned');

  m._refitAll();
  let calls = 0;
  const real = m._applyPositionMode.bind(m);
  m._applyPositionMode = (...a) => { calls += 1; return real(...a); };

  // אותו רוחב בדיוק, רק הגובה קטן — כמו מקלדת שנפתחה
  sb.window.innerHeight = 400;
  m._refitAll();

  eq(calls, 0, 'מספר החישובים על פתקים נעוצים');
});

// ── 3. פתק על קובץ — מצב צף (``screen``) ────────────────────────────────

check('קובץ — פתק צף גדול נכנס לאזור התצוגה בשני הצירים', () => {
  // פתק צף הוא ``position: fixed``, ולכן אין לאן לגלול כדי להגיע לפינה
  // שיצאה — כאן גם הגובה חייב להצטמצם, לא רק הרוחב.
  const sb = makeSandbox(PHONE_LANDSCAPE.w, PHONE_LANDSCAPE.h);
  const note = { id: 'f1', mode: 'screen', position: { x: 500, y: 300 }, size: { width: 700, height: 620 } };
  const { m, el } = mount(sb, 'file-1', note);

  m._applyPositionMode(el, note, { reflow: false });

  atMost(px(el.style.width), PHONE_LANDSCAPE.w, 'רוחב מוצג');
  atMost(px(el.style.height), PHONE_LANDSCAPE.h, 'גובה מוצג');
  atMost(px(el.style.left) + px(el.style.width), PHONE_LANDSCAPE.w, 'הקצה הימני');
  atMost(px(el.style.top) + px(el.style.height), PHONE_LANDSCAPE.h, 'הקצה התחתון — שם יושבת ידית שינוי הגודל');
  atLeast(px(el.style.top), 0, 'הקצה העליון — שם יושבת ידית הגרירה');
});

check('קובץ — פתק צף שומר את הכוונה גם אחרי הקטנה', () => {
  const sb = makeSandbox(PHONE_LANDSCAPE.w, PHONE_LANDSCAPE.h);
  const note = { id: 'f1', mode: 'screen', position: { x: 500, y: 300 }, size: { width: 700, height: 620 } };
  const { m, el } = mount(sb, 'file-1', note);

  m._applyPositionMode(el, note, { reflow: false });
  const payload = m._notePayloadFromEl(el);

  eq(payload.size.width, 700, 'הגודל שנשמר');
  eq(payload.size.height, 620, 'הגובה שנשמר');
  eq(payload.position.x, 500, 'המיקום שנשמר');
  eq(payload.position.y, 300, 'המיקום האנכי שנשמר');
});

check('קובץ — פתק מעוגן נכנס ברוחב המסך', () => {
  // הענף ה-``anchored`` לא הצמיד כלום עד התיקון, והוא גם ``is-pinned``
  // ולכן ``_reflowWithinViewport`` דילג עליו — פתק מעוגן שנשמר על מסך
  // רחב פשוט יצא מהצד ולא הייתה שום דרך להחזירו.
  const sb = makeSandbox(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const note = { id: 'a1', mode: 'anchored', line_start: 12, position: { x: 900, y: 400 }, size: { width: 700, height: 620 } };
  const { m, el } = mount(sb, 'file-1', note);

  m._applyPositionMode(el, note, { reflow: false });

  atMost(px(el.style.width), PHONE_PORTRAIT.w, 'רוחב מוצג');
  atMost(px(el.style.left) + px(el.style.width), PHONE_PORTRAIT.w, 'הקצה הימני');
});

// ── 4. פתק על קובץ בריפו הממורר ─────────────────────────────────────────

check('ריפו — פתק גדול נכנס בגבולות תצוגת הקובץ', () => {
  const sb = makeSandbox(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const surface = makeSurface(PHONE_PORTRAIT.w, PHONE_PORTRAIT.h);
  const note = bigNote('r1', 'surface');
  const { m, el } = mount(
    sb,
    { repo: 'CodeBot', path: 'webapp/app.py', container: surface, anchorHost: null },
    note,
  );

  m._applyPositionMode(el, note, { reflow: false });

  atMost(px(el.style.width), PHONE_PORTRAIT.w, 'רוחב מוצג');
  atMost(px(el.style.left) + px(el.style.width), PHONE_PORTRAIT.w, 'הקצה הימני');
  eq(note.size.width, 700, 'userSize נשמר');
});

// ── 5. שינוי גודל ידני — הכוונה **כן** מתעדכנת ──────────────────────────

check('שינוי גודל מהפינה מעדכן את הכוונה', () => {
  // ההבחנה שבלעדיה כל הפיצ'ר חסר טעם: הקטנה אוטומטית אינה נשמרת,
  // אבל גרירה מהפינה כן — היא הדרך היחידה שבה המשתמש קובע גודל.
  const sb = makeSandbox(TABLET.w, TABLET.h);
  const surface = makeSurface(TABLET.w, TABLET.h);
  const note = bigNote('n1', 'surface');
  const { m, el } = mount(sb, { board: 'b1', container: surface, anchorHost: null }, note);

  let saved = null;
  m._queueSave = (_el, fragment) => { saved = fragment; };
  m._flushFor = () => {};
  m._updateSurfaceExtent = () => {};

  const handle = { style: {}, addEventListener(type, fn) { (this._h = this._h || {})[type] = fn; } };
  m._enableResize(el, handle);
  handle._h.mousedown({ clientX: 0, clientY: 0, preventDefault() {} });
  // מדמים את מה ש-``onMove`` כותב: המשתמש הקטין ל-320x240
  el.style.width = '320px';
  el.style.height = '240px';
  // ``onUp`` רשום על ``window`` דרך ``_on``; קוראים לו ישירות דרך הלכידה
  m._boundHandlers.filter((h) => h.type === 'mouseup').forEach((h) => h.fn());

  eq(note.size.width, 320, 'userSize.width התעדכן');
  eq(note.size.height, 240, 'userSize.height התעדכן');
  if (!saved) throw new Error('לא נשמר כלום');
  eq(saved.size.width, 320, 'הגודל שנשלח לשרת');
  eq(saved.size.height, 240, 'הגובה שנשלח לשרת');
});

// ── 6. פתק ממוזער — המדידה משקרת, הכוונה לא ─────────────────────────────

check('פתק ממוזער לא מאבד את גובהו', () => {
  // ``.sticky-note.is-minimized { height: auto !important }`` — המדידה
  // מחזירה את גובה הכותרת בלבד. הצורה הקודמת של ``_reflowWithinViewport``
  // כתבה את המדידה הזו בחזרה ל-``style``, ואז פתיחה אחרי מיזעור הציגה
  // פתק בגובה הרצפה במקום בגובה שנקבע.
  const sb = makeSandbox(TABLET.w, TABLET.h);
  const note = { id: 'f1', mode: 'screen', position: { x: 100, y: 100 }, size: { width: 300, height: 500 } };
  const { m, el } = mount(sb, 'file-1', note);
  el.classList.add('is-floating');
  // ממוזער: ה-CSS מכריח גובה כותרת בלבד
  el.style.height = '42px';

  m._reflowWithinViewport(el);

  eq(px(el.style.height), 500, 'הגובה חזר מהכוונה');
  eq(note.size.height, 500, 'הכוונה לא השתנתה');
});

// ── 7. גבולות שאי אפשר למדוד אינם ראיה למסך צר ──────────────────────────

check('קונטיינר שלא נמדד — לא מקטין ולא מצמיד', () => {
  // "כשל שאילתה נבדל תמיד מ'אין'". קונטיינר עם ``clientWidth`` אפס הוא
  // מדידה שלא הצליחה, ולא מסך ברוחב אפס.
  const sb = makeSandbox(TABLET.w, TABLET.h);
  const surface = makeSurface(0, 0);
  surface.clientWidth = 0;
  const note = bigNote('n1', 'surface');
  const { m, el } = mount(sb, { board: 'b1', container: surface, anchorHost: null }, note);

  m._applyPositionMode(el, note, { reflow: false });

  eq(px(el.style.width), 700, 'הרוחב לא הוקטן');
  eq(px(el.style.left), 200, 'המיקום לא הוצמד');
});

// ── סיכום ───────────────────────────────────────────────────────────────

console.log(`\n${passed} עברו, ${failed} נכשלו`);
if (failed > 0) process.exit(1);
