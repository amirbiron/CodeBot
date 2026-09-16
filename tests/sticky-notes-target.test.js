/**
 * טסטים ל-webapp/static/js/sticky-notes.js — הפרמטריזציה ליעד (קובץ מול לוח).
 *
 * הרצה:  node tests/sticky-notes-target.test.js
 * (אין ברפו runner ל-JS, ולכן הקובץ עצמאי ומחזיר קוד יציאה 1 בכישלון —
 *  אותה תבנית כמו tests/md-anchors.test.js.)
 *
 * מה נבדק כאן: בחירת היעד ומצב המיקום, ובנוסף **מחזור החיים של המנהל** —
 * ``destroy`` שמרוקן את התור לפני שהוא מפרק, הסרת כל מאזין שנרשם (כולל
 * אלה של הגרירה ושינוי הגודל), וביטול תשובה שנחתה אחרי הפירוק. הגרירה
 * ושינוי הגודל נבדקים ברמת **רישום המאזינים** בלבד; ההתנהגות החזותית
 * שלהם דורשת DOM אמיתי ואינה נבדקת כאן.
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
// **המטא-דאטה של סוגי האלרט נטענת לפני המודול, בדיוק כמו בתבניות.**
// ``_containerSpec`` קורא את ``window.ADMONITION_TITLES`` ואת
// ``window.DETAILS_DEFAULT_TITLE`` כדי לדעת מהו סוג מוכר,
// ובלי הטעינה כאן אף אלרט לא היה מזוהה וכל הבדיקות עליו היו נכשלות — או
// גרוע מכך, עוברות מהסיבה הלא נכונה אילו היו בודקות רק שהשורה נשארה טקסט.
const ADMONITION_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'admonition-icons.js');

/** DOM מינימלי — רק מה ש-``_init`` נוגע בו לפני שהוא נכשל בשקט. */
function makeSandbox() {
  // רישום **זהות** המאזינים שהוסרו, ולא רק ספירה. מונה גלובלי היה משותף
  // לכל המנהלים שנוצרים בקובץ הזה (סנדבוקס אחד, ``window``/``document``
  // משותפים), ובדיקה אסינכרונית אחת הייתה יכולה להסיט את הספירה של אחרת.
  // עם ``Set`` של הפונקציות עצמן, כל בדיקה שואלת רק על המאזינים שלה.
  //
  // **כל אלמנט נספר, לא רק window/document:** המנהל רושם מאזין גם על
  // הקונטיינר (גלילה פנימית בדפדפן הריפו), ויעד שאינו נספר היה מדווח על
  // מאזין שלא הוסר — כשל רפאים.
  const listenerLedger = { added: 0, removed: 0, removedFns: new Set() };
  const tracking = () => ({
    addEventListener() { listenerLedger.added += 1; },
    removeEventListener(_type, fn) { listenerLedger.removed += 1; listenerLedger.removedFns.add(fn); },
  });
  const el = () => ({
    style: {}, dataset: {}, classList: { add() {}, remove() {}, contains: () => false },
    appendChild() {}, ...tracking(), querySelectorAll: () => [], querySelector: () => null,
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }),
    setAttribute() {}, getAttribute: () => null,
  });
  const body = el();
  const mdContent = el();
  const sandbox = {
    console,
    __listeners: listenerLedger,
    document: {
      body,
      // מחזיר אלמנט אמיתי, אחרת הבדיקה על _anchorHost לא יכולה להיכשל
      getElementById: (id) => (id === 'md-content' ? mdContent : null),
      createElement: () => el(),
      // ראו ההסבר ב-``sticky-notes-size-intent.test.js``.
      createElementNS: () => el(),
      ...tracking(),
      querySelectorAll: () => [],
      // ``_setTitleEditing`` מקזז ``document.activeElement === input`` לפני
      // שהוא קורא ל-``blur``. בלי החשיפה הזו התנאי לעולם אינו מתקיים,
      // הענף לא רץ באף בדיקה, ומחיקתו הייתה עוברת בשקט.
      get activeElement() { return sandbox.__focused || null; },
    },
    window: {
      ...tracking(),
      innerWidth: 1024,
      innerHeight: 768,
      matchMedia: () => ({ matches: false }),
      location: { search: '', hash: '' },
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: async () => ({ json: async () => ({ ok: true, notes: [] }) }),
    // ``_reflowWithinViewport`` בודק ``instanceof HTMLElement``. בלי
    // ההגדרה כאן הוא זרק ``ReferenceError`` שנבלע ב-try/catch של
    // ``_applyPositionMode`` — כלומר חלק מהפונקציה לא רץ, בשקט.
    HTMLElement: function HTMLElement() {},
    setTimeout, clearTimeout, setInterval, clearInterval,
    MutationObserver: undefined, ResizeObserver: undefined,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(ADMONITION_PATH, 'utf8'), sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox;
}

const sandbox = makeSandbox();
const StickyNotesManager = sandbox.window.StickyNotesManager;

let passed = 0;
let failed = 0;

// בדיקה אסינכרונית שנכשלת מחזירה promise דחוי, וגרסה סינכרונית של
// ``check`` הייתה סופרת אותה כ"עברה" ומדפיסה אזהרת unhandled rejection.
// לכן התור מצטבר ומוצה בסוף הקובץ.
const pending = [];

function check(name, fn) {
  try {
    const out = fn();
    if (out && typeof out.then === 'function') {
      pending.push(out.then(
        () => { passed += 1; },
        (err) => { failed += 1; console.error(`✗ ${name}\n    ${err && err.message}`); },
      ));
      return;
    }
    passed += 1;
  } catch (err) {
    failed += 1;
    console.error(`✗ ${name}\n    ${err && err.message}`);
  }
}

function eq(actual, expected, what) {
  if (actual !== expected) {
    // ``JSON.stringify`` על צומת DOM מדומה קורס על ``parentNode`` המעגלי,
    // וההודעה שהייתה יוצאת מתארת את הקריסה ולא את הכשל שנבדק.
    const show = (v) => {
      try { return JSON.stringify(v); } catch (_) { return String(v && v.tagName || v); }
    };
    throw new Error(`${what || ''} — ציפיתי ל-${show(expected)}, קיבלתי ${show(actual)}`);
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

check('פתק קובץ מקבל את #md-content כמקור עוגנים', () => {
  // רגרסיה אמיתית: החלפה גורפת של getElementById פגעה גם בשורת
  // הקונסטרקטור, ו-_anchorHost יצא undefined — כלומר כל מסלול העיגון
  // בפתקי קובץ מנוטרל, בשקט. ה-sandbox כאן מחזיר אלמנט אמיתי ל-md-content.
  const m = new StickyNotesManager('f1');
  if (m._anchorHost === undefined) throw new Error('_anchorHost הוא undefined');
  eq(m._hasAnchorHost, true, '_hasAnchorHost');
});

check('לוח מקבל anchorHost ריק במפורש', () => {
  const m = new StickyNotesManager({ board: 'b1', anchorHost: null });
  eq(m._hasAnchorHost, false);
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
const mdMgr = new StickyNotesManager({ board: 'md-tests' });  // מארקדאון דלוק

// **מוקש בהארנס, ולא בקוד הנבדק.**
//
// הבנאי יורה ``_init() → loadNotes()`` ברקע, וכשהיא נפתרת היא קוראת
// ``_clearAllNotes()`` — כלומר **כל פתק שנרשם ידנית ב-``notes`` נמחק
// ב-microtask הראשון**. כל הבדיקות עד היום היו סינכרוניות ורצו לפני
// הרגע הזה, ולכן לא הרגישו. הראשונה שהוסיפה ``await`` נפלה על מפה ריקה,
// ובלי הבדיקה הזו כל בדיקה אסינכרונית עתידית הייתה משקרת באותו אופן.
//
// ממתינים כאן, פעם אחת, עד שהטעינה ברקע מסיימת.
await new Promise((resolve) => setTimeout(resolve, 0));

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


// -- צ'קבוקסים: תצוגת התוכן --
//
// הזרימה המלאה (fetch, אימות, חזרה אחורה) נבדקת בפייתון ב-
// tests/test_sticky_notes_tasks.py, כי שם היא באמת נכתבת למסד. כאן נבדק
// מה שחי בדפדפן: מה ``_syncTaskView`` מרנדר, ומה הוא **לא** נוגע בו.
//
// למה DOM מדומה ולא בדיקת פונקציית עזר טהורה: הגרסה הקודמת בדקה
// ``_parseTasks``, שהחזירה רק את שורות המשימה. היא עברה בהצלחה בזמן
// שהתצוגה הסתירה 400 שורות טקסט — כי היא בדקה את המסננת, לא את מה
// שהמשתמש רואה. הבדיקה חייבת לגעת במה שנשבר.

/** DOM מינימלי — בדיוק מה ש-``_syncTaskView`` ו-``_enterEditAt`` נוגעים בו. */
class FakeEl {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.dataset = {}; this.style = {};
    this.hidden = false; this._text = ''; this._attrs = {}; this._classes = new Set();
    this.classList = {
      add: (...c) => c.forEach((x) => this._classes.add(x)),
      remove: (c) => this._classes.delete(c),
      contains: (c) => this._classes.has(c),
      toggle: (c, on) => { if (on) this._classes.add(c); else this._classes.delete(c); },
    };
  }
  set className(v) { this._classes = new Set(String(v || '').split(/\s+/).filter(Boolean)); }
  get className() { return [...this._classes].join(' '); }
  appendChild(c) { this.children.push(c); c.parentNode = this; return c; }
  // ``Element.remove`` קיים בכל דפדפן, והקוד קורא לו מאחורי guard. בלי
  // מימוש כאן ה-guard מדלג בשקט, והבדיקה "החיווי נעלם" עוברת סתם.
  remove() {
    const p = this.parentNode;
    if (p) { p.children = p.children.filter((c) => c !== this); this.parentNode = null; }
  }
  // ``innerHTML`` קיים בכל דפדפן, ו-``_appendAlertIcon`` משתמש בו — פעם
  // אחת, על ``span`` ייעודי לאייקון SVG סטטי. בלי מימוש כאן ההשמה הייתה
  // נוחתת על תכונה סתמית, והבדיקה "האייקון נכנס" הייתה עוברת סתם — אותה
  // מלכודת של ``remove``/``blur`` בסבבים קודמים. הוא נשמר בנפרד מ-
  // ``_text`` בכוונה, כדי שבדיקה תוכל להבדיל בין "נכתב כ-HTML" לבין
  // "נכתב כטקסט" — וזו בדיוק ההבחנה שהבדיקה על הכותרת המותאמת עושה.
  set innerHTML(v) { this.children = []; this._html = String(v == null ? '' : v); }
  get innerHTML() { return this._html == null ? '' : this._html; }
  set textContent(v) { this.children = []; this._text = String(v); }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join('') : this._text; }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; }
  // ``removeAttribute``, ``select`` ו-``blur`` קיימים בכל דפדפן, והקוד
  // קורא להם מאחורי guard. בלי מימוש כאן ה-guard מדלג בשקט והבדיקה
  // עוברת סתם — בדיוק כמו שקרה עם ``remove`` בסבב קודם.
  removeAttribute(k) { delete this._attrs[k]; }
  hasAttribute(k) { return k in this._attrs; }
  // **המאזינים נרשמים ולא נבלעים.** ``addEventListener`` ריק הוא בדיוק
  // המלכודת של ``remove``/``blur``/``createTextNode`` בסבבים קודמים:
  // הכפתור נבנה, המאזין "נרשם", ובדיקה שמנסה ללחוץ עליו לא יכולה
  // אפילו להיכשל — אין על מה ללחוץ. כאן הם נשמרים לפי סוג אירוע,
  // והאחרון גובר, כמו שקורא בודד בדפדפן.
  addEventListener(type, fn) { (this._listeners || (this._listeners = {}))[type] = fn; }
  focus() { FakeEl.focused = this; sandbox.__focused = this; }
  blur() {
    if (FakeEl.focused === this) FakeEl.focused = null;
    if (sandbox.__focused === this) sandbox.__focused = null;
  }
  select() { this._selected = true; }
  _matches(sel) {
    // תומך ב-``.class``, ב-``tag``, וב-``tag.class`` מורכב — הקוד משתמש
    // ב-``closest('a.sticky-md-link')``, ובלי זה הבדיקה עברה מהסיבה הלא
    // נכונה (או נפלה) על סלקטור שהסטאב לא הבין.
    if (sel.startsWith('.')) return this._classes.has(sel.slice(1));
    const dot = sel.indexOf('.');
    if (dot > 0) {
      const tag = sel.slice(0, dot), cls = sel.slice(dot + 1);
      return this.tagName === tag && this._classes.has(cls);
    }
    return this.tagName === sel;
  }
  // ``closest`` אמיתי שמטפס דרך ``parentNode``, כמו בדפדפן.
  closest(sel) {
    let node = this;
    while (node) {
      if (node._matches && node._matches(sel)) return node;
      node = node.parentNode || null;
    }
    return null;
  }
  querySelector(sel) {
    for (const c of this.children) {
      if (c._matches(sel)) return c;
      const deep = c.querySelector(sel);
      if (deep) return deep;
    }
    return null;
  }
  querySelectorAll(sel) {
    const out = [];
    for (const c of this.children) { if (c._matches(sel)) out.push(c); out.push(...c.querySelectorAll(sel)); }
    return out;
  }
  getBoundingClientRect() { return { left: 0, top: 0, width: 0, height: 0 }; }
}

sandbox.document.createElement = (tag) => new FakeEl(tag);
// גם ``createElementNS``, ומאותו מפעל בדיוק: שתי מתודות שבונות אלמנטים
// אך מחזירות דמויות שונות היו נותנות לעץ אחד שני סוגי אלמנטים, ובדיקה
// שנוגעת באייקון של הכפתור הצף הייתה מקבלת התנהגות שאינה תואמת לשאר העץ.
sandbox.document.createElementNS = (_ns, tag) => new FakeEl(tag);
// ``_appendInline`` בונה טקסט עם ``createTextNode``. בלי מימוש כאן,
// רינדור המארקדאון נכשל בשקט (עטוף ב-try/catch) והבדיקות היו עוברות
// על התנהגות שבורה — אותה מלכודת של ``remove``/``blur`` בסבבים קודמים.
sandbox.document.createTextNode = (t) => ({
  nodeType: 3, textContent: String(t == null ? '' : t),
  _matches: () => false, querySelector: () => null, querySelectorAll: () => [],
});

/** פתק מדומה עם טקסטריה ותצוגה, כמו ש-``_renderNote`` בונה. */
function makeNote(content) {
  const el = new FakeEl('div');
  el.className = 'sticky-note';
  const ta = new FakeEl('textarea');
  ta.className = 'sticky-note-content';
  ta.value = content;
  const view = new FakeEl('div');
  view.className = 'sticky-note-tasks';
  el.appendChild(ta);
  el.appendChild(view);
  return { el, ta, view };
}

const CONTENT = 'כותרת\n- [ ] אחת\nשורת טקסט\n- פריט רגיל\n- [x] שתיים';

check('תצוגה: **כל** השורות מרונדרות, לא רק המשימות', () => {
  // זה הבאג שמחק 400 שורות מהמסך. הגרסה הקודמת הייתה מרנדרת 2.
  const { el, view } = makeNote(CONTENT);
  fileMgr._syncTaskView(el);
  eq(view.children.length, 5, 'מספר השורות');
});

check('תצוגה: טקסט שאינו משימה נשאר גלוי', () => {
  const { el, view } = makeNote(CONTENT);
  fileMgr._syncTaskView(el);
  eq(view.textContent.includes('שורת טקסט'), true, 'טקסט חופשי');
  eq(view.textContent.includes('פריט רגיל'), true, 'פריט רשימה — התוכן, בלי הסימן שהפך לתבליט');
});

check('תצוגה: הסידור נספר על שורות משימה בלבד', () => {
  // הסידור הוא מה שנשלח לשרת. ספירה על כל השורות הייתה מסמנת שורה אחרת.
  const { el, view } = makeNote(CONTENT);
  fileMgr._syncTaskView(el);
  const boxes = view.querySelectorAll('.sticky-task-box');
  eq(boxes.length, 2, 'מספר תיבות');
  eq(boxes[0].dataset.taskIndex, '0');
  eq(boxes[1].dataset.taskIndex, '1');
  eq(boxes[1].checked, true, '[x] מסומנת');
});

check('תצוגה: X גדולה נחשבת מסומנת', () => {
  const { el, view } = makeNote('- [X] בוצע');
  fileMgr._syncTaskView(el);
  eq(view.querySelectorAll('.sticky-task-box')[0].checked, true);
});

check('תצוגה: תוכן בלי משימות משאיר את הטקסטריה גלויה', () => {
  // זה מה ששומר על פתק רגיל בדיוק כפי שהיה
  const { el, ta, view } = makeNote('סתם טקסט');
  fileMgr._syncTaskView(el);
  eq(view.hidden, true, 'התצוגה מוסתרת');
  eq(ta.hidden, false, 'הטקסטריה גלויה');
});

check('רינדור הוא חד-כיווני: התוכן לא נכתב מהתצוגה', () => {
  // **החוק שמעל כל השאר.** ``content → HTML``, לעולם לא חזרה. היחידים
  // שרשאים לכתוב ל-content הם הטקסטריה וראוט ``/task``.
  const { el, ta } = makeNote(CONTENT);
  const before = ta.value;
  const saves = [];
  const realQueue = fileMgr._queueSave;
  fileMgr._queueSave = (...a) => { saves.push(a); };
  try {
    fileMgr._syncTaskView(el);
    fileMgr._syncTaskView(el, { editing: true });
    fileMgr._syncTaskView(el);
  } finally {
    fileMgr._queueSave = realQueue;
  }
  eq(ta.value, before, 'התוכן לא השתנה');
  eq(saves.length, 0, 'לא נשלחה שום שמירה');
});

check('חזרה לעריכה: הסמן נוחת בתחילת השורה שנלחצה', () => {
  // בלי זה התצוגה היא דלת חד-כיוונית — אי אפשר להוסיף או למחוק מלל
  const { el, ta, view } = makeNote(CONTENT);
  fileMgr._syncTaskView(el);
  const row = view.children[2];              // 'שורת טקסט'
  fileMgr._enterEditAt(el, parseInt(row.dataset.charOffset, 10));
  eq(ta.hidden, false, 'הטקסטריה חזרה');
  eq(FakeEl.focused, ta, 'הפוקוס עבר לטקסטריה');
  eq(CONTENT.slice(ta.selectionStart, ta.selectionStart + 4), 'שורת', 'מיקום הסמן');
});

check('אורך: התקרה מגיעה מהשרת, לא מוקלדת בלקוח', () => {
  // בלי ערך מהשרת אין מספר להשוות אליו — ואז לא מזהירים, במקום להזהיר
  // לפי מספר שאולי כבר לא נכון.
  const { el } = makeNote('קצר');
  sandbox.window.STICKY_NOTE_MAX_CHARS = undefined;
  eq(fileMgr._checkContentLength(el, 'א'.repeat(999999)), false, 'אין תקרה ידועה');
  eq(el.querySelector('.sticky-note-warn'), null, 'אין חיווי');
});

check('אורך: בדיוק בגבול מתקבל, ומעליו מוצג חיווי', () => {
  sandbox.window.STICKY_NOTE_MAX_CHARS = 20000;
  const { el } = makeNote('קצר');

  eq(fileMgr._checkContentLength(el, 'קצר'), false, 'תוכן קצר');
  eq(el.querySelector('.sticky-note-warn'), null, 'אין חיווי');

  // הגבול עצמו חוקי — off-by-one כאן פוסל תוכן תקין
  eq(fileMgr._checkContentLength(el, 'א'.repeat(20000)), false, 'בדיוק בגבול');
  eq(el.querySelector('.sticky-note-warn'), null, 'אין חיווי בגבול');

  eq(fileMgr._checkContentLength(el, 'א'.repeat(20001)), true, 'תו אחד מעל');
  const warn = el.querySelector('.sticky-note-warn');
  eq(warn !== null, true, 'יש חיווי');
  eq(warn.textContent.includes('20001'), true, 'החיווי מציין את האורך בפועל');
  eq(warn.textContent.includes('20000'), true, 'והתקרה שהשרת נתן');
});

check('אורך: החיווי מתנקה כשחוזרים מתחת לתקרה', () => {
  // כשל שנשאר על המסך אחרי שתוקן משקר בדיוק כמו כשל שלא הוצג
  sandbox.window.STICKY_NOTE_MAX_CHARS = 20000;
  const { el } = makeNote('קצר');

  fileMgr._checkContentLength(el, 'א'.repeat(20001));
  eq(el.querySelector('.sticky-note-warn') !== null, true, 'החיווי הופיע');
  eq(el.classList.contains('has-length-error'), true, 'קלאס השגיאה נוסף');

  eq(fileMgr._checkContentLength(el, 'א'.repeat(100)), false, 'שוב מתחת לתקרה');
  eq(el.querySelector('.sticky-note-warn'), null, 'החיווי נעלם');
  eq(el.classList.contains('has-length-error'), false, 'קלאס השגיאה הוסר');
});

check('אורך: אימוג\'י נספר כמו בפייתון, לא כיחידות UTF-16', () => {
  // ``String.length`` סופר יחידות UTF-16 והשרת סופר תווי Unicode. בלי
  // ההתאמה, 10,001 אימוג\'ים קיבלו אזהרה על תוכן שהשרת מקבל — פי שניים.
  sandbox.window.STICKY_NOTE_MAX_CHARS = 20000;
  const { el } = makeNote('קצר');
  const emoji = '🙂'.repeat(10001);          // 20,002 יחידות, 10,001 תווים

  eq(fileMgr._checkContentLength(el, emoji), false, 'השרת היה מקבל, ולכן אין אזהרה');
  eq(el.querySelector('.sticky-note-warn'), null, 'אין חיווי');

  // ומעל התקרה האמיתית — כן מזהירים, עם המספר של פייתון
  eq(fileMgr._checkContentLength(el, '🙂'.repeat(20001)), true, 'מעל התקרה');
  eq(el.querySelector('.sticky-note-warn').textContent.includes('20001'), true, 'ספירת קוד-פוינטים');
});

check('אורך: הניסוח תואם לחוזה השרת — העדכון כולו נדחה', () => {
  // "מה שמעבר לא יישמר" שיקר: השרת דוחה את כל העדכון, לא חותך זנב
  sandbox.window.STICKY_NOTE_MAX_CHARS = 20000;
  const { el } = makeNote('קצר');
  fileMgr._checkContentLength(el, 'א'.repeat(20001));
  const text = el.querySelector('.sticky-note-warn').textContent;
  eq(text.includes('מה שמעבר'), false, 'לא מבטיח שמירה חלקית');
  eq(text.includes('לקצר'), true, 'אומר מה לעשות');
});

check('שמירה: עריכה חדשה תוך כדי טיסה שורדת כשל', () => {
  // **אובדן תוכן שנמדד בדפדפן.** ``_flushFor`` מוציא את המטען מהתור לפני
  // שהוא ממתין לרשת. הקלדה בזמן ההמתנה יצרה רשומה חדשה, וכשל דרס אותה.
  const id = 'race1';
  fileMgr._pending.set(id, { content: 'העריכה החדשה' });
  fileMgr._restorePending(id, { content: 'המטען הישן', position: { x: 1, y: 2 } });

  const after = fileMgr._pending.get(id);
  eq(after.content, 'העריכה החדשה', 'החדש מנצח');
  eq(after.position.x, 1, 'והישן ממלא מה שחסר');
});

check('שמירה: מידע טרי מהשרת כן דורס את התור', () => {
  // הכיוון ההפוך, ובכוונה: ``prev_updated_at`` שחוזר מ-409 חייב לנצח,
  // אחרת הניסיון הבא נדחה שוב על אותה חותמת. שתי כוונות, שתי פונקציות.
  const id = 'race2';
  fileMgr._pending.set(id, { content: 'טקסט', prev_updated_at: 'ישן' });
  fileMgr._mergePending(id, { prev_updated_at: 'חדש-מהשרת' });

  const after = fileMgr._pending.get(id);
  eq(after.prev_updated_at, 'חדש-מהשרת', 'המידע הטרי ניצח');
  eq(after.content, 'טקסט', 'והתוכן לא נפגע');
});

check('שמירה: 400 אינו חוזר לתור, 500 כן', () => {
  // הבאג: כל !ok הוחזר ל-pending, וה-auto-flush ניסה שוב לנצח. תוכן
  // שנדחה ב-400 לא הופך לתקין — זו לולאה חמה שגם מסתירה את הכשל.
  eq(fileMgr._isPermanentFailure(400), true, '400 סופי');
  eq(fileMgr._isPermanentFailure(404), true, '404 סופי');
  eq(fileMgr._isPermanentFailure(409), false, '409 נפתר עם חותמת טרייה');
  eq(fileMgr._isPermanentFailure(429), false, '429 — לנסות שוב מאוחר יותר');
  eq(fileMgr._isPermanentFailure(500), false, '500 זמני');
  eq(fileMgr._isPermanentFailure(undefined), false, 'סטטוס לא ידוע — לא לזרוק מידע');
});

// ---------- ביטול פעולה ----------
//
// כל הבדיקות כאן רושמות את הפתק ב-``notes``, כי ``_undoState`` תלוי ב-
// ``entry.data.content`` בתור נקודת המוצא.

/** רושם פתק במנהל ומחזיר את החלקים שלו. */
function registerNote(mgr, id, content) {
  const parts = makeNote(content);
  parts.el.dataset.noteId = id;
  const undoBtn = new FakeEl('button');
  undoBtn.className = 'sticky-note-btn sticky-note-undo';
  undoBtn.disabled = true;
  parts.el.appendChild(undoBtn);
  const titleInput = new FakeEl('input');
  titleInput.className = 'sticky-note-title';
  parts.el.appendChild(titleInput);
  mgr.notes.set(id, { el: parts.el, data: { id, content } });
  return Object.assign(parts, { undoBtn, titleInput, entry: mgr.notes.get(id) });
}

check('ביטול: המשך רשימה אוטומטי נרשם למחסנית', () => {
  // ``_handleListContinuation`` כותב ל-``textarea.value`` ישירות, וכתיבה
  // תכנותית **אינה** משדרת ``input``. בלי רישום מפורש הצעד הזה היה יוצא
  // מחוץ להיסטוריה, והביטול היה מדלג עליו כאילו לא קרה.
  const n = registerNote(fileMgr, 'undo-list', '- [ ] ראשון');
  n.ta.value = '- [ ] ראשון\n- [ ] ';
  fileMgr._noteProgrammaticEdit(n.el, n.ta, '- [ ] ראשון');

  eq(fileMgr._undoState(n.el).stack.length, 1, 'צעד אחד במחסנית');
  eq(fileMgr._undoState(n.el).stack[0], '- [ ] ראשון', 'התוכן שלפני');
  eq(n.undoBtn.disabled, false, 'הכפתור פעיל');
});

check('ביטול: כתיבה תכנותית שלא שינתה דבר אינה נרשמת', () => {
  const n = registerNote(fileMgr, 'undo-noop', 'טקסט');
  fileMgr._noteProgrammaticEdit(n.el, n.ta, 'טקסט');
  eq(fileMgr._undoState(n.el).stack.length, 0, 'מחסנית ריקה');
});

check('ביטול: כפתור פעיל מיד אחרי הדבקה, לפני שהטיימר נסגר', () => {
  // התרחיש המרכזי של הפיצ'ר: בחירת-הכל ואז הדבקה בטעות. המחסנית עדיין
  // ריקה — הצילום ממתין ל-600ms של שקט — ובגרסה הקודמת הכפתור היה
  // מושבת בדיוק ברגע שבו הוא הכי נחוץ.
  const original = 'א'.repeat(750);
  const n = registerNote(fileMgr, 'undo-paste', original);
  n.ta.value = 'הדבקה קצרה';
  fileMgr._recordUndoBurst(n.el, n.ta);

  eq(fileMgr._undoState(n.el).stack.length, 0, 'המחסנית עדיין ריקה');
  eq(n.undoBtn.disabled, false, 'ובכל זאת הכפתור פעיל');

  fileMgr._undoLastChange(n.el);
  eq(n.ta.value, original, 'התוכן חזר במלואו');
  eq(n.ta.value.length, 750, 'ובאורך המקורי');
});

check('ביטול: תוכן סמכותי מהשרת מאפס את נקודת ההשוואה', () => {
  // אחרי סימון צ'קבוקס השרת מחזיר את התוכן הנכון. אם ``last`` נשאר על
  // התוכן שלפני הסימון, העריכה הבאה דוחפת אותו למחסנית — וביטול אחד היה
  // מוחק כתיבה שהשרת כבר אישר.
  const n = registerNote(fileMgr, 'undo-server', '- [ ] משימה');
  const entry = n.entry;

  // **חובה לייצר את מצב הביטול לפני התוכן מהשרת.** ``_undoState`` בונה
  // את עצמו מ-``entry.data.content``, ואם הוא נוצר רק אחרי — הוא נזרע
  // ממילא מהערך החדש והבדיקה עוברת גם בלי התיקון. נתפס במוטציה: ביטול
  // ``_resetUndoBaseline`` לא הפיל את הגרסה הראשונה של הבדיקה הזו.
  n.ta.value = '- [ ] משימה!';
  fileMgr._recordUndoBurst(n.el, n.ta);
  eq(fileMgr._undoState(n.el).last, '- [ ] משימה!', 'נקודת המוצא לפני השרת');

  fileMgr._applyServerContent(n.el, entry, '- [x] משימה', '2026-01-01T00:00:00Z');
  eq(fileMgr._undoState(n.el).last, '- [x] משימה', 'נקודת ההשוואה התעדכנה');
  eq(fileMgr._undoState(n.el).burstFrom, null, 'וההתפרצות הפתוחה נסגרה');

  // עכשיו המשתמש מקליד. מה שנשמר חייב להיות התוכן **שאחרי** הסימון.
  n.ta.value = '- [x] משימה ועוד';
  fileMgr._recordUndoBurst(n.el, n.ta);
  eq(fileMgr._undoState(n.el).burstFrom, '- [x] משימה', 'הצילום הוא מהתוכן המאושר');
});

check('ביטול: מחיקת פתק מנקה את הטיימר התלוי', () => {
  const n = registerNote(fileMgr, 'undo-timer', 'טקסט');
  n.ta.value = 'טקסט ועוד';
  fileMgr._recordUndoBurst(n.el, n.ta);
  eq(fileMgr._undoState(n.el).timer !== null, true, 'יש טיימר פתוח');

  fileMgr._clearUndoTimer(n.el);
  eq(fileMgr._undoState(n.el).timer, null, 'נוקה');
});

// ---------- שם תפוס ----------

check('שם: הסימון תלוי בקוד השגיאה, לא בכשל שמירה גנרי', () => {
  // הגרסה הקודמת הסיקה מ-``has-save-error``: כל נפילת רשת או חריגת מכסה
  // סימנה את השם כתפוס, ואילו 409 אמיתי — שאינו מסמן את המחלקה הזו —
  // לא סימן כלום. כלומר הסימון הופיע בכל מצב חוץ מהנכון.
  const n = registerNote(fileMgr, 'dup-1', 'תוכן');

  n.el.classList.add('has-save-error');       // כשל שמירה כלשהו
  fileMgr._syncTitleConflict(n.el);
  eq(n.titleInput.classList.contains('is-duplicate'), false, 'כשל גנרי אינו "שם תפוס"');

  fileMgr._markTitleConflict('dup-1', true);  // 409 duplicate_title
  eq(n.titleInput.classList.contains('is-duplicate'), true, 'ורק הקוד הספציפי מסמן');

  fileMgr._markTitleConflict('dup-1', false);
  eq(n.titleInput.classList.contains('is-duplicate'), false, 'שם חדש מנקה את הסימון');
});

check('ביטול: תוכן מהשרת שסוגר התפרצות מכבה גם את הכפתור', () => {
  // הכפתור נדלק על סמך התפרצות ממתינה. ``_resetUndoBaseline`` סוגר אותה,
  // ואם הוא לא מסנכרן — הכפתור נשאר דלוק על מחסנית ריקה, ולחיצה עליו
  // לא עושה כלום. כפתור שנראה זמין ולא עובד הוא בדיוק סוג השקר שהפיצ'ר
  // הזה נבנה כדי לא לספר.
  const n = registerNote(fileMgr, 'undo-sync', 'מקור');
  n.ta.value = 'מקור ועוד';
  fileMgr._recordUndoBurst(n.el, n.ta);
  eq(n.undoBtn.disabled, false, 'דלוק בזמן ההתפרצות');
  eq(fileMgr._undoState(n.el).stack.length, 0, 'והמחסנית עדיין ריקה');

  fileMgr._resetUndoBaseline(n.el, 'תוכן מהשרת');

  eq(fileMgr._undoState(n.el).stack.length, 0, 'המחסנית נשארה ריקה');
  eq(n.undoBtn.disabled, true, 'ולכן הכפתור כבוי');
});

check('ביטול: סימון צ׳קבוקס ניתן לביטול', () => {
  // התרחיש: פתק שלא נערך, המשתמש מסמן צ'קבוקס. המחסנית ריקה לגמרי,
  // ולכן לפני התיקון לא הייתה שום דרך לחזור מהסימון דרך הכפתור —
  // בעוד שההערה בקוד טענה שהמחסנית כבר שומרת את המצב שלפני.
  const n = registerNote(fileMgr, 'undo-toggle', '- [ ] משימה');
  eq(fileMgr._undoState(n.el).stack.length, 0, 'נקודת המוצא: מחסנית ריקה');

  fileMgr._applyServerContent(n.el, n.entry, '- [x] משימה', '2026-01-01T00:00:00Z');

  eq(n.ta.value, '- [x] משימה', 'התוכן הסמכותי הוחל');
  eq(n.undoBtn.disabled, false, 'ויש מה לבטל');
  fileMgr._undoLastChange(n.el);
  eq(n.ta.value, '- [ ] משימה', 'הסימון בוטל');
});

check('ביטול: תוכן זהה מהשרת אינו נחשב צעד', () => {
  const n = registerNote(fileMgr, 'undo-same', '- [x] משימה');
  fileMgr._applyServerContent(n.el, n.entry, '- [x] משימה', null);
  eq(fileMgr._undoState(n.el).stack.length, 0, 'שום דבר לא השתנה');
  eq(n.undoBtn.disabled, true);
});

// ``_sendUpdate`` אמיתי מול תשובה מבוקרת. בלי זה אין דרך לבדוק את ענפי
// הכשל של מסלול השמירה — והם בדיוק החלק שנשבר בשקט.
async function withFetch(handler, fn) {
  // ``await`` ולא ``return`` בתוך try: בלעדיו ה-``finally`` משחזר את
  // ה-fetch **לפני** שה-promise נפתר, והבדיקה רצה מול הפייק ברירת המחדל
  // של הסנדבוקס — שאין לו ``status`` בכלל. נתפס בהרצה: שתי בדיקות נפלו
  // על ענף הכשל במקום על הענף שנבדק.
  const original = sandbox.fetch;
  sandbox.fetch = handler;
  try { return await fn(); } finally { sandbox.fetch = original; }
}
const okResponse = async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) });

check('שם: שמירה שאינה של השם אינה מנקה את הסימון', async () => {
  // התרחיש: השם נדחה ב-409, ואז המשתמש גורר את הפתק. השמירה של המיקום
  // מצליחה — אבל היא לא אומרת דבר על השם, שנשאר תפוס בשרת. ניקוי הסימון
  // כאן היה מציג "נשמר" על שדה שהשרת לא קיבל.
  const n = registerNote(fileMgr, 'dup-keep', 'תוכן');
  fileMgr._markTitleConflict('dup-keep', true);
  eq(n.titleInput.classList.contains('is-duplicate'), true, 'מסומן אחרי 409');

  await withFetch(okResponse, () => fileMgr._sendUpdate('dup-keep', { position: { x: 1, y: 2 } }, 0));
  eq(n.titleInput.classList.contains('is-duplicate'), true, 'שמירת מיקום לא ניקתה');

  await withFetch(okResponse, () => fileMgr._sendUpdate('dup-keep', { title: 'שם אחר' }, 0));
  eq(n.titleInput.classList.contains('is-duplicate'), false, 'שמירת שם כן ניקתה');
});

check('שם: 409 duplicate_title מסמן ואינו חוזר לתור', async () => {
  // 409 גנרי חוזר לתור עם חותמת טרייה; שם תפוס לא ייפתר לעולם בניסיון
  // חוזר. בלי ההבחנה זו לולאת ניסיונות אינסופית, ובלי שום חיווי.
  const n = registerNote(fileMgr, 'dup-409', 'תוכן');
  const dup = async () => ({ ok: false, status: 409, json: async () => ({ ok: false, error: 'duplicate_title' }) });

  fileMgr._pending.set('dup-409', { title: 'תפוס' });
  fileMgr._pendingSeq.set('dup-409', 0);
  const result = await withFetch(dup, () => fileMgr._sendUpdate('dup-409', { title: 'תפוס' }, 0));

  eq(result, false, 'הכשל דווח');
  eq(n.titleInput.classList.contains('is-duplicate'), true, 'והשם מסומן');
  eq(fileMgr._pending.has('dup-409'), false, 'ולא נשאר בתור לניסיון נוסף');
});

check('ביטול: תוכן מהשרת באמצע הקלדה שומר את תחילת ההתפרצות', () => {
  // התרחיש: המשתמש מקליד, ובאמצע ההתפרצות מגיע תוכן סמכותי מהשרת
  // (סימון צ'קבוקס ממכשיר אחר, למשל). ``_resetUndoBaseline`` מוחק את
  // ``burstFrom`` — הצילום שנלקח **לפני** ההקלדה — ובלי לשמור אותו קודם
  // הביטול היה מחזיר לסוף ההתפרצות במקום לתחילתה, וההקלדה כולה אבודה.
  const n = registerNote(fileMgr, 'undo-mid-burst', 'התחלה');

  n.ta.value = 'התחלה + הקלדה';
  fileMgr._recordUndoBurst(n.el, n.ta);
  eq(fileMgr._undoState(n.el).burstFrom, 'התחלה', 'ההתפרצות פתוחה');

  fileMgr._applyServerContent(n.el, n.entry, 'מהשרת', null);

  // שני צעדים, LIFO: קודם חוזרים למה שהוקלד, ואז למה שהיה לפני
  eq(n.ta.value, 'מהשרת', 'התוכן הסמכותי הוחל');
  fileMgr._undoLastChange(n.el);
  eq(n.ta.value, 'התחלה + הקלדה', 'ביטול ראשון — מה שהוקלד');
  fileMgr._undoLastChange(n.el);
  eq(n.ta.value, 'התחלה', 'ביטול שני — לפני ההקלדה');
});

// ---------- עריכת שם הפתק ----------

check('שם: מצב העריכה מחליף נעילה, פוקוס וסמל', () => {
  // השדה נעול כברירת מחדל, וזה מה שמחזיר את שטח הגרירה: שדה נעול הוא
  // ``pointer-events: none`` ב-CSS, כלומר האירוע נופל דרכו אל ידית
  // הגרירה שמתחתיו. נמדד לפני התיקון: 1%-3% מהכותרת נגררו, כי שדה השם
  // תפס 218px–635px ממנה. אחרי: 73%.
  const n = registerNote(fileMgr, 'title-edit', 'תוכן');
  const btn = new FakeEl('button');
  btn.className = 'sticky-note-btn sticky-note-edit-title';
  btn.textContent = '✎';
  n.el.appendChild(btn);
  n.titleInput.setAttribute('readonly', 'readonly');
  n.titleInput.setAttribute('tabindex', '-1');

  fileMgr._setTitleEditing(n.el, true);
  eq(n.el.classList.contains('is-editing-title'), true, 'המצב נדלק');
  eq(n.titleInput.getAttribute('readonly'), null, 'הנעילה הוסרה');
  eq(n.titleInput.getAttribute('tabindex'), '0', 'נכנס לסדר ה-Tab');
  eq(btn.textContent, '✔', 'הסמל התחלף');
  eq(btn.getAttribute('aria-pressed'), 'true');
  eq(btn.getAttribute('aria-label'), 'סיום עריכת השם', 'התווית תואמת לפעולה');
  eq(sandbox.__focused === n.titleInput, true, 'השדה קיבל מיקוד');
  eq(n.titleInput._selected, true, 'והתוכן נבחר');

  fileMgr._setTitleEditing(n.el, false);
  eq(n.el.classList.contains('is-editing-title'), false, 'המצב כובה');
  eq(n.titleInput.getAttribute('readonly'), 'readonly', 'ננעל שוב');
  eq(n.titleInput.getAttribute('tabindex'), '-1', 'יצא מסדר ה-Tab');
  eq(btn.textContent, '✎', 'חזר לעיפרון');
  eq(btn.getAttribute('aria-pressed'), 'false');
  eq(btn.getAttribute('aria-label'), 'עריכת שם הפתק', 'והתווית חזרה');
  // **זה הענף שלא רץ באף בדיקה עד היום.** בלי ``document.activeElement``
  // בסנדבוקס התנאי לעולם לא התקיים, והשדה נשאר ממוקד אחרי הנעילה —
  // כלומר המקלדת במובייל לא הייתה נסגרת.
  eq(sandbox.__focused, null, 'והמיקוד שוחרר');
});

// ---------- גרירה: מה בכותרת הוא משטח גרירה ----------

check('גרירה: הידית היא הכותרת כולה, לא ``.sticky-note-drag``', () => {
  // ``cursor: move`` מוצהר על ``.sticky-note-header``, אבל המאזין ישב על
  // ילד אחד בתוכה. נמדד בכרומיום על כותרת שגלשה לשתי שורות: חמש נקודות
  // לרוחב הכותרת החזירו ``cursor: move`` ו**לא** הזיזו את הפתק — כל שורת
  // הכפתורים הייתה שטח מת שנראה גריר.
  //
  // נופל אם מחזירים את ``_enableDrag(el, drag)``.
  const captured = [];
  const orig = fileMgr._enableDrag;
  fileMgr._enableDrag = (el, handle) => { captured.push(handle); };
  try {
    fileMgr._renderNote({ id: 'drag-handle', content: '', position: { x: 0, y: 0 } });
  } finally {
    fileMgr._enableDrag = orig;
  }

  eq(captured.length, 1, '_enableDrag נקרא פעם אחת');
  eq(captured[0].classList.contains('sticky-note-header'), true,
     'הידית היא הכותרת');
});

check('גרירה: כפתור ושם בעריכה מוחרגים, שאר הכותרת לא', () => {
  // ההרחבה לכותרת שלמה מכניסה תחתיה את שורת הכפתורים ואת שדה השם.
  // ``_isDragExempt`` הוא מה שמחזיר לכל אחד מהם את תפקידו: כפתור נשאר
  // כפתור, ושדה השם **בזמן עריכה** נשאר שדה שאפשר למקם בו סמן. במצב
  // הנעול השדה הוא ``pointer-events: none`` וממילא אינו יעד האירוע.
  const header = new FakeEl('div'); header.className = 'sticky-note-header';
  const actions = new FakeEl('div'); actions.className = 'sticky-note-actions';
  const btn = new FakeEl('button'); btn.className = 'sticky-note-btn sticky-note-pin';
  const inner = new FakeEl('span');   // אמוג'י בתוך הכפתור
  const title = new FakeEl('input'); title.className = 'sticky-note-title';
  header.appendChild(actions); actions.appendChild(btn); btn.appendChild(inner);
  header.appendChild(title);

  eq(fileMgr._isDragExempt(header), false, 'הכותרת עצמה נגררת');
  eq(fileMgr._isDragExempt(actions), false, 'השטח הריק בשורת הכפתורים נגרר');
  eq(fileMgr._isDragExempt(btn), true, 'כפתור אינו משטח גרירה');
  // ``closest`` ולא השוואת target ישירה: לחיצה על האמוג'י שבתוך הכפתור
  // מחזירה את הצומת הפנימי, והשוואה ישירה הייתה מפספסת בדיוק את המקרה
  // שהיא נועדה לתפוס — כלומר הכפתור היה גורר את הפתק.
  eq(fileMgr._isDragExempt(inner), true, 'גם צומת בתוך כפתור');

  title.setAttribute('readonly', 'readonly');
  eq(fileMgr._isDragExempt(title), false, 'שם נעול — נגרר');
  title.removeAttribute('readonly');
  eq(fileMgr._isDragExempt(title), true, 'שם בעריכה — לא נגרר');

  // ספק ⇒ לא לגרור. גרירה שגויה מזיזה פתק בלי כוונת המשתמש; גרירה שלא
  // קרתה היא לכל היותר נגיעה שלא עשתה כלום.
  eq(fileMgr._isDragExempt(null), false, 'בלי יעד אין ממה להחריג');
  eq(fileMgr._isDragExempt({ closest(){ throw new Error('boom'); } }), true,
     'חריגה נסגרת לצד הבטוח');
});

// ---------- מארקדאון: פרסר אינליין טהור ----------

function inlineDump(mgr, text){
  return mgr._parseInline(text).map(s =>
    s.type === 'link' ? `link(${s.text}|${s.href})` : `${s.type}(${s.text})`
  ).join(' ');
}

check('אינליין: מודגש, נטוי, קוד, חוצה', () => {
  eq(inlineDump(fileMgr, '**מ**'), 'bold(מ)');
  eq(inlineDump(fileMgr, '*נ*'), 'italic(נ)');
  eq(inlineDump(fileMgr, '`c`'), 'code(c)');
  eq(inlineDump(fileMgr, '~~x~~'), 'strike(x)');
});

check('אינליין: ==מרקר==', () => {
  eq(inlineDump(fileMgr, '==מודגש=='), 'mark(מודגש)');
  eq(inlineDump(fileMgr, 'לפני ==באמצע== אחרי'), 'text(לפני ) mark(באמצע) text( אחרי)');
});

check('אינליין: מרקר לא-סגור נשאר טקסט', () => {
  // בדיוק כמו ``**`` ו-``~~``: מפרידן פתוח אינו הופך את שארית השורה.
  eq(inlineDump(fileMgr, '==לא'), 'text(==לא)');
  eq(inlineDump(fileMgr, 'a == b'), 'text(a == b)');
});

check('אינליין: קוד השוואה אינו נצבע', () => {
  // **בכלי קוד זה המקרה הנפוץ.** שרשור השוואות בפייתון מכיל שני ``==``
  // ובלי כלל הרווחים האופרנד האמצעי היה מרונדר כמרקר.
  eq(inlineDump(fileMgr, 'a == b == c'), 'text(a == b == c)');
  eq(inlineDump(fileMgr, '1 == 1 == True'), 'text(1 == 1 == True)');
  eq(inlineDump(fileMgr, 'if x == y == z:'), 'text(if x == y == z:)');
  // גם הצורה עם רווח בצד אחד בלבד
  eq(inlineDump(fileMgr, '== x =='), 'text(== x ==)');
});

check('אינליין: מרקר ריק אינו נתפס', () => {
  // ``====`` הוא ארבעה תווים, לא מרקר של כלום. הדרישה לתו אחד לפחות
  // באה מ-``[^=\s]``, שהוא חובה ולא quantifier.
  eq(inlineDump(fileMgr, '===='), 'text(====)');
});

check('אינליין: שורת מפריד של סימני שווה אינה מרקר', () => {
  // **באג אמיתי, לא תיאורטי.** כשהתו הראשון היה ``\S`` הוא התיר גם
  // ``=`` עצמו, ולכן ``=====`` התפרק ל-``==`` ‏+ ``=`` ‏+ ``==`` וצבע
  // תו אחד ורוד. מפריד ASCII בפתק הוא שימוש רגיל לגמרי.
  //
  // ``====`` ומטה עברו גם קודם, אבל **במקרה** — לא נשארו בהם מספיק
  // תווים. לכן הבדיקה מתחילה דווקא בחמישה, שם ההגנה הישנה נגמרה.
  eq(inlineDump(fileMgr, '====='), 'text(=====)');
  eq(inlineDump(fileMgr, '======'), 'text(======)');
  eq(inlineDump(fileMgr, '=========='), 'text(==========)');
  eq(inlineDump(fileMgr, '='.repeat(20)), `text(${'='.repeat(20)})`);
});

check('אינליין: מרקר אינו בולע סימן שווה בקצה', () => {
  // ``===ab==`` הצביע קודם ``=ab`` — סימן השווה העודף נכנס לתוך התוכן
  // במקום להישאר טקסט. אותו שורש בדיוק.
  eq(inlineDump(fileMgr, '===ab=='), 'text(=) mark(ab)');
});

check('אינליין: קוד מגן גם על מרקר', () => {
  // הקוד נתפס ראשון בסדר החלופות, ולכן ``==`` בתוכו ליטרלי.
  eq(inlineDump(fileMgr, '`a==b==c`'), 'code(a==b==c)');
});

check('אינליין: מרקר פותח את שער הרינדור', () => {
  // בלי זה פתק שכולו ``==טקסט==`` היה נשאר textarea ולא מתרנדר כלל —
  // כשל שקט בדיוק במקרה שהפיצ'ר נועד לו.
  eq(fileMgr._lineHasInline('==מודגש=='), true);
  eq(fileMgr._lineHasInline('טקסט רגיל'), false);
});

check('אינליין: קוד מגן על תוכנו', () => {
  // כוכביות בתוך קוד נשארות ליטרליות — הקוד נתפס ראשון.
  eq(inlineDump(fileMgr, '`a*b*c`'), 'code(a*b*c)');
});

check('אינליין: קו תחתון אינו נטוי', () => {
  // ``note_id`` ו-``user_id`` נפוצים מדי בכלי קוד. החלטה מתועדת.
  eq(inlineDump(fileMgr, 'note_id ו-user_id'), 'text(note_id ו-user_id)');
});

check('אינליין: קישור בטוח בלבד', () => {
  eq(inlineDump(fileMgr, '[ok](https://x.com)'), 'link(ok|https://x.com)');
  // סכימה חסומה → ליטרל, לא קישור. זה הגבול הביטחוני.
  eq(inlineDump(fileMgr, '[x](javascript:alert(1))'), 'text([x](javascript:alert(1)))');
  eq(inlineDump(fileMgr, '[y](data:text/html,x)'), 'text([y](data:text/html,x))');
});

check('אינליין: מפרידן לא-סגור נשאר טקסט', () => {
  eq(inlineDump(fileMgr, '**לא'), 'text(**לא)');
  eq(inlineDump(fileMgr, 'a ** b'), 'text(a ** b)');
});

// ---------- מארקדאון: סיווג בלוק ----------

check('בלוק: כותרות 1-3, ומעבר לרגיל', () => {
  eq(fileMgr._classifyLine('# א').kind, 'heading');
  eq(fileMgr._classifyLine('# א').level, 1);
  eq(fileMgr._classifyLine('### ג').level, 3);
  eq(fileMgr._classifyLine('#### ד').kind, 'plain');   // 4 = לא כותרת
  eq(fileMgr._classifyLine('#ללא רווח').kind, 'plain'); // #3262 בטוח
});

check('בלוק: ציטוט, קו, רשימות', () => {
  eq(fileMgr._classifyLine('> צ').kind, 'quote');
  eq(fileMgr._classifyLine('---').kind, 'hr');
  eq(fileMgr._classifyLine('- פ').kind, 'ul');
  eq(fileMgr._classifyLine('* פ').kind, 'ul');
  eq(fileMgr._classifyLine('1. פ').kind, 'ol');
  eq(fileMgr._classifyLine('1. פ').marker, '1.');
});

// ---------- מארקדאון: מתי התצוגה נפתחת ----------

check('פתיחה: טקסט רגיל נשאר textarea', () => {
  eq(fileMgr._hasRenderableMarkdown(['סתם טקסט', 'עוד שורה']), false);
  eq(fileMgr._hasRenderableMarkdown(['note_id ו-user_id']), false);
  eq(fileMgr._hasRenderableMarkdown(['כוכבית * בודדת']), false);
  eq(fileMgr._hasRenderableMarkdown(['קישור [x](javascript:y) פסול']), false);
});

check('פתיחה: מבנה מארקדאון פותח', () => {
  eq(fileMgr._hasRenderableMarkdown(['**מ**']), true);
  eq(fileMgr._hasRenderableMarkdown(['# כותרת']), true);
  eq(fileMgr._hasRenderableMarkdown(['- פריט']), true);
  eq(fileMgr._hasRenderableMarkdown(['```', 'code', '```']), true);
  eq(fileMgr._hasRenderableMarkdown(['ראה [כאן](https://x.com)']), true);
});

// ---------- מארקדאון: רינדור מלא ל-DOM ----------

function renderMd(mgr, content){
  const parts = makeNote(content);
  mgr._syncTaskView(parts.el);
  return parts;
}

check('רינדור: מרקר נבנה ל-DOM', () => {
  // שאר הסוגים האינליניים נבדקים גם ברמת ה-DOM ולא רק בפרסר. בלי זה
  // ``_appendInline`` יכול היה להפסיק לייצר ``<mark>`` בלי שאף טסט ייפול.
  const { view } = renderMd(mdMgr, 'לפני ==מסומן== אחרי');
  const mark = view.querySelector('mark.sticky-md-mark');
  eq(!!mark, true, 'נוצר mark.sticky-md-mark');
  eq(mark && mark.textContent, 'מסומן', 'התוכן');
  // ה-DOM המדומה מחזיר את השם באותיות קטנות, בדפדפן הוא גדולות.
  eq(mark && String(mark.tagName).toLowerCase(), 'mark', 'האלמנט הסמנטי ולא span');
});

check('רינדור: כל סוגי הבלוק נבנים', () => {
  const { el, view } = renderMd(mdMgr,
    '# כותרת\n> ציטוט\n---\n- פריט\n1. ממוספר\n**מודגש** רגיל');
  eq(!!view.querySelector('.sticky-md-h1'), true, 'H1');
  eq(!!view.querySelector('.sticky-md-quote'), true, 'ציטוט');
  eq(!!view.querySelector('.sticky-md-hr'), true, 'קו');
  eq(view.querySelectorAll('.sticky-md-li').length, 2, 'שני פריטי רשימה');
  eq(!!view.querySelector('.sticky-md-bold'), true, 'מודגש');
  eq(view.hidden, false, 'התצוגה גלויה');
});

check('רינדור: זריקה נשארת טקסט, לא תגית', () => {
  // **החוזה הקדוש.** ``createElement``+``textContent`` בלבד, ולכן
  // ``<script>`` לא יכול להפוך לתגית.
  const { view } = renderMd(mdMgr, '<script>alert(1)</script> **ok**');
  const text = view.textContent;
  eq(text.includes('<script>alert(1)</script>'), true, 'הסקריפט כטקסט');
  eq(!!view.querySelector('script'), false, 'ואין תגית script');
});

check('רינדור: קישור מקבל rel ו-target', () => {
  const { view } = renderMd(mdMgr, 'ראה [כאן](https://x.com)');
  const a = view.querySelector('.sticky-md-link');
  eq(a.getAttribute('href'), 'https://x.com');
  eq(a.getAttribute('target'), '_blank');
  eq(a.getAttribute('rel'), 'noopener noreferrer');
});

check('רינדור: בלוק קוד — הגדרות אינן מוצגות, התוכן ליטרלי', () => {
  const { view } = renderMd(mdMgr, '```\na*b*\n```');
  const pre = view.querySelectorAll('.sticky-md-pre');
  eq(pre.length, 1, 'שורת התוכן בלבד — שתי הגדרות נצרכו ואינן מוצגות');
  // התוכן בקוד אינו מפורש לאינליין — אין ``em``, והטקסט **מלא**.
  eq(!!view.querySelector('.sticky-md-italic'), false, 'אין נטוי בתוך קוד');
  eq(pre[0].textContent, 'a*b*', 'שורת התוכן ליטרלית, כולל הכוכביות');
  eq(!!view.querySelector('.sticky-md-code-block'), true, 'ונבנתה עוטפת לבלוק');
});

check('רינדור: משימה בגדר קוד — ליטרלית, אבל סופרת בסידור (מארקדאון דלוק)', () => {
  // **חוזה הסידור מול השרת.** ``sticky_notes_tasks`` סופר כל שורת
  // ``- [ ]``, כולל בתוך גדר. לכן המשימה שבגדר אינה אינטראקטיבית, אבל
  // הסידור שלה **נצרך**: המשימה האמיתית שאחריה היא אינדקס 1, לא 0.
  // אחרת הלקוח שולח 0 והשרת מסמן את זו שבגדר.
  const { view } = renderMd(mdMgr, '```\n- [ ] בקוד\n```\n- [ ] אמיתי');
  const boxes = view.querySelectorAll('.sticky-task-box');
  eq(boxes.length, 1, 'רק המשימה שמחוץ לגדר אינטראקטיבית');
  eq(boxes[0].dataset.taskIndex, '1', 'והסידור שלה 1 — כמו שהשרת סופר');
  const pre = view.querySelectorAll('.sticky-md-pre');
  eq(pre[0].textContent, '- [ ] בקוד', 'הדוגמה בגדר נשארה ליטרלית');
});

check('רינדור: משימה בגדר — הסידור עקבי גם כשמארקדאון כבוי', () => {
  // מארקדאון כבוי: אין פרסור גדר כלל, ולכן שתי שורות ה-``- [ ]`` הן
  // תיבות אינטראקטיביות 0 ו-1 — וזה **גם** מה שהשרת סופר. עקביות בשני
  // המצבים.
  const off = new StickyNotesManager({ board: 'md-off-fence', markdown: false });
  const parts = makeNote('```\n- [ ] בקוד\n```\n- [ ] אמיתי');
  off._syncTaskView(parts.el);
  const boxes = parts.view.querySelectorAll('.sticky-task-box');
  eq(boxes.length, 2, 'בלי פרסור גדר — שתי התיבות אינטראקטיביות');
  eq(boxes[0].dataset.taskIndex, '0', 'הראשונה 0');
  eq(boxes[1].dataset.taskIndex, '1', 'השנייה 1 — כמו השרת');
});


check('פתיחה: קישור פסול לפני מארקדאון תקין — עדיין נפתח', () => {
  // ``_lineHasInline`` סורק את כל ההתאמות. קישור פסול ראשון לא מסתיר
  // את המודגש שאחריו.
  eq(mdMgr._hasRenderableMarkdown(['[x](javascript:y) ואז **מ**']), true);
  const { view } = renderMd(mdMgr, '[x](javascript:y) ואז **מ**');
  eq(!!view.querySelector('.sticky-md-bold'), true, 'המודגש מרונדר');
  eq(!!view.querySelector('.sticky-md-link'), false, 'והקישור הפסול נשאר טקסט');
});

check('פתק קובץ: מארקדאון דלוק כברירת מחדל, כמו בלוח', () => {
  // ברירת המחדל אחידה לכל היעדים. היא הייתה פעם כבויה בפתקי קובץ מתוך
  // חשש שרינדור אוטומטי הוא שינוי שקט — אבל הדגל לבדו אינו מרנדר כלום,
  // ולכן מה שהשתנה הוא רק פתקים שכבר מכילים מבנה מארקדאון.
  eq(fileMgr.markdown, true, 'פתק קובץ — דלוק');
  eq(mdMgr.markdown, true, 'פתק לוח — דלוק');
  const parts = makeNote('# כותרת\n**מ**');
  fileMgr._syncTaskView(parts.el);
  eq(!!parts.view.querySelector('.sticky-md-h1'), true, 'מרונדר בפתק קובץ');
  eq(parts.ta.hidden, true, 'וה-textarea מוסתר');
});

check('פתק קובץ בלי מבנה מארקדאון נשאר תיבת עריכה', () => {
  // **זה מה שמחזיק את רדיוס השינוי קטן.** ``_syncTaskView`` דורש גם את
  // הדגל וגם מבנה בפועל, ולכן הדלקת ברירת המחדל אינה נוגעת בפתקי טקסט.
  // בלי הבדיקה הזו, הדלקה גורפת הייתה נראית זהה בטסטים.
  const parts = makeNote('סתם טקסט בלי שום מבנה');
  fileMgr._syncTaskView(parts.el);
  eq(parts.ta.hidden, false, 'ה-textarea גלוי');
  eq(parts.view.hidden, true, 'והתצוגה מוסתרת');
});

check('רינדור: charOffset נשמר לכל שורה', () => {
  // לחיצה חוזרת-לעריכה תלויה בזה. שורה עם מודגש וקוד סופרת על הגלם.
  const { view } = renderMd(mdMgr, 'אחת\n**שתיים** `קוד`\nשלוש');
  const rows = view.querySelectorAll('.sticky-task-line');
  eq(rows[0].dataset.charOffset, '0', 'שורה 1');
  eq(rows[1].dataset.charOffset, '4', 'שורה 2 — אחרי "אחת\\n"');
  eq(rows[2].dataset.charOffset, '20', 'שורה 3 — נספר על הגלם, לא על המרונדר');
});

// ---------- רשימות מקוננות ----------
//
// המודל נמדד מול ``markdown-it@14.1.0``, אותה ספרייה שמרנדרת את תצוגת
// ה-Markdown בריפו, ולכן היא הצרכן שהפתק צריך להסכים איתו על מה מקונן.
// הכלל: פריט נסגר כשההזחה של השורה הבאה **אינה מגיעה לעמודת התוכן שלו**.

/** עומקי הרשימה בכל שורה, לפי מחלקות ``is-depth-N``. */
function depths(view){
  return view.querySelectorAll('.sticky-task-line').map((r) => {
    for (let d = 1; d <= 9; d += 1) if (r.classList.contains('is-depth-' + d)) return d;
    return 0;
  });
}

check('קינון: רוחב הזחה — טאב מתקדם לעמודה שמתחלקת ב-4', () => {
  eq(mdMgr._indentCols(''), 0, 'ריק');
  eq(mdMgr._indentCols('   '), 3, 'שלושה רווחים');
  eq(mdMgr._indentCols('\t'), 4, 'טאב מעמודה 0');
  eq(mdMgr._indentCols(' \t'), 4, 'רווח ואז טאב — עדיין עמודה 4, לא 5');
  eq(mdMgr._indentCols('\t\t'), 8, 'שני טאבים');
  eq(mdMgr._indentCols('\t', 2), 4, 'טאב מעמודה 2');
  eq(mdMgr._indentCols('\t', 4), 8, 'טאב מעמודה 4 מדלג לתחנה הבאה');
});

check('קינון: עמודת התוכן של פריט', () => {
  const cc = (line) => mdMgr._listContentCol(line, mdMgr._classifyLine(line));
  eq(cc('- א'), 2, '"- " → עמודה 2');
  eq(cc('1. א'), 3, '"1. " → עמודה 3');
  eq(cc('12. א'), 4, '"12. " → עמודה 4');
  eq(cc('  - א'), 4, 'הזחה נספרת');
  // מעבר לארבעה רווחים זה בלוק קוד מוזח בתוך הפריט, ולכן ההזחה חוזרת ל-1.
  eq(cc('-      א'), 2, 'שישה רווחים → 1');
  eq(cc('-    א'), 5, 'ארבעה רווחים עדיין נספרים');
});

check('קינון: רשימה לא ממוספרת — שתי רמות', () => {
  const { view } = renderMd(mdMgr,
    '- פריט ראשון\n- פריט שני\n  - תת-פריט 2.1\n  - תת-פריט 2.2\n    - תת-תת-פריט\n- פריט שלישי');
  // בדיוק מה ש-markdown-it החזיר על אותו קלט: 0,0,1,1,2,0
  eq(depths(view).join(','), '0,0,1,1,2,0');
});

check('קינון: רשימה ממוספרת — הזחה של שלושה רווחים', () => {
  const { view } = renderMd(mdMgr,
    '1. שלב ראשון\n2. שלב שני\n   1. תת-שלב 2.1\n   2. תת-שלב 2.2\n3. שלב שלישי');
  eq(depths(view).join(','), '0,0,1,1,0');
});

check('קינון: המספר המוצג הוא מה שהוקלד, גם בתת-רשימה', () => {
  // התצוגה היא ראי חד-כיווני של המקור. מספור מחדש היה מציג משהו שאינו
  // כתוב בפתק.
  const { view } = renderMd(mdMgr, '2. שני\n   7. שבע');
  const bullets = view.querySelectorAll('.sticky-md-bullet');
  eq(bullets[0].textContent, '2.');
  eq(bullets[1].textContent, '7.');
});

check('קינון: התבליט משתנה עם העומק', () => {
  // נמדד בכרומיום: ``disc`` ← ``circle`` ← ``square``, והאחרון חוזר.
  const { view } = renderMd(mdMgr, '- א\n  - ב\n    - ג\n      - ד');
  const bullets = view.querySelectorAll('.sticky-md-bullet');
  eq(bullets.map((b) => b.textContent).join(''), '•◦▪▪');
});

check('קינון: רווח אחד אינו מגיע לעמודת התוכן — אחים, לא בן', () => {
  // זה מה שמבדיל בין "עמודת התוכן קובעת" לבין "כל הזחה = רמה".
  // נמדד מול markdown-it: שני הפריטים באותה רמה.
  const { view } = renderMd(mdMgr, '- א\n - ב');
  eq(depths(view).join(','), '0,0');
});

check('קינון: שורת צ\'קבוקס מוזחת מקבלת את אותו עומק', () => {
  const { view } = renderMd(mdMgr, '- [ ] משימה\n  - [ ] תת-משימה\n  - תת-פריט');
  eq(depths(view).join(','), '0,1,1', 'הצ\'קבוקס והפריט באותה רמה');
  eq(view.querySelectorAll('.sticky-task-box').length, 2, 'שתי תיבות סימון');
});

check('קינון: שורת צ\'קבוקס מזינה את מחסנית העומק', () => {
  // הבאג שהמבנה הזה מונע: כשהסיווג ישב בענף ה-wantMd בלבד, שורת המשימה
  // לא נכנסה למחסנית, והפריט שאחריה יצא בעומק 0 במקום 1.
  const { view } = renderMd(mdMgr, '- [ ] משימה\n  - תת-פריט');
  eq(depths(view).join(','), '0,1');
});

check('קינון: אינדקס המשימות אינו זז בגלל הזחה', () => {
  // ההתאמה מול ``sticky_notes_tasks`` בשרת היא מה שקובע איזו שורה
  // תסומן. הזחה היא תצוגה בלבד ואסור לה לגעת בסידור.
  const { view } = renderMd(mdMgr, '- [ ] א\n  - [ ] ב\n- פריט\n    - [x] ג');
  const boxes = view.querySelectorAll('.sticky-task-box');
  eq(boxes.length, 3, 'שלוש תיבות');
  eq(boxes.map((b) => b.dataset.taskIndex).join(','), '0,1,2', 'סידור רציף');
  eq(boxes[2].checked, true, 'המסומנת היא השלישית');
});

check('קינון: charOffset נשמר גם ברשימה מקוננת', () => {
  // החוזה הקדוש של המנוע: כל שורת מקור היא אלמנט אחד עם ההיסט שלה.
  // הזחה לא מקפלת שורות ולא מזיזה את החשבון.
  const content = '- א\n  - ב\n    - ג\nאחרי';
  const { view } = renderMd(mdMgr, content);
  const rows = view.querySelectorAll('.sticky-task-line');
  eq(rows.map((r) => Number(r.dataset.charOffset)).join(','),
     [0, content.indexOf('  - ב'), content.indexOf('    - ג'), content.indexOf('אחרי')].join(','));
});

check('קינון: שורה ריקה אינה סוגרת רשימה', () => {
  // נמדד מול markdown-it — גם שורה ריקה אחת וגם שתיים.
  const one = renderMd(mdMgr, '- א\n\n  - ב');
  eq(depths(one.view).join(','), '0,0,1', 'שורה ריקה אחת');
  const two = renderMd(mdMgr, '- א\n\n\n  - ב');
  eq(depths(two.view).join(','), '0,0,0,1', 'שתי שורות ריקות');
});

check('קינון: כותרת, קו מפריד וטקסט בעמודה 0 סוגרים רשימה', () => {
  const h = renderMd(mdMgr, '- א\n# כותרת\n  - ב');
  eq(depths(h.view).join(','), '0,0,0', 'כותרת');
  const hr = renderMd(mdMgr, '- א\n---\n  - ב');
  eq(depths(hr.view).join(','), '0,0,0', 'קו מפריד');
  // סטייה מכוונת מ-markdown-it, ששם רואה בשורה כזו המשך פסקה של הפריט.
  // בפתק כל שורת מקור היא שורת תצוגה נפרדת, ואין המשך פסקה.
  const t = renderMd(mdMgr, '- א\nטקסט\n  - ב');
  eq(depths(t.view).join(','), '0,0,0', 'שורת טקסט');
});

check('קינון: גדר מוזחת לתוך פריט אינה סוגרת אותו', () => {
  const { view } = renderMd(mdMgr, '- א\n  ```\n  - לא רשימה\n  ```\n  - ב');
  const d = depths(view);
  eq(d[0], 0, 'הפריט הראשון');
  eq(d.pop(), 1, 'הפריט שאחרי הגדר חוזר לעומק שלו');
  eq(view.querySelectorAll('.sticky-md-pre').length, 1, 'שורת תוכן אחת');
});

check('קינון: טבלה בעמודה 0 סוגרת רשימה', () => {
  const { view } = renderMd(mdMgr, '- א\n| א | ב |\n| --- | --- |\n| 1 | 2 |\n  - ב');
  eq(depths(view).pop(), 0, 'הפריט שאחרי הטבלה חוזר לעומק 0');
});

// ---------- גבול בלוק סוגר לפי ההזחה של עצמו ----------
//
// שורה נשארת בתוך פריט כל עוד ההזחה שלה מגיעה לעמודת התוכן שלו. לכן
// בלוק בעמודה 0 סוגר את הרשימה, ובלוק שמוזח לתוך הפריט נשאר בתוכו —
// **בלי קשר לסוג הבלוק.** לפני התיקון שורת גדר לא נגעה במחסנית כלל
// וכל בלוק אחר איפס אותה לגמרי, כלומר שתי התנהגויות שגויות בכיוונים
// הפוכים. כל המקרים כאן נמדדו מול markdown-it.

check('סגירה: _closeListsAbove סוגר רק את מה שמעל ההזחה', () => {
  const st = [2, 4, 6];
  mdMgr._closeListsAbove(st, 6);
  eq(st.join(','), '2,4,6', 'הזחה ששווה לעמודת התוכן נשארת בפנים');
  mdMgr._closeListsAbove(st, 5);
  eq(st.join(','), '2,4', 'הזחה נמוכה יותר סוגרת את הפנימי בלבד');
  mdMgr._closeListsAbove(st, 0);
  eq(st.join(','), '', 'עמודה 0 סוגרת הכול');
  mdMgr._closeListsAbove(st, 0);
  eq(st.join(','), '', 'ומחסנית ריקה אינה נשברת');
});

check('סגירה: _lineIndentCols הוא התשובה היחידה להזחה', () => {
  eq(mdMgr._lineIndentCols('- א'), 0);
  eq(mdMgr._lineIndentCols('  - א'), 2);
  eq(mdMgr._lineIndentCols('\t```'), 4, 'טאב בשורת גדר, לא רק ברשימה');
  eq(mdMgr._lineIndentCols('   # כותרת'), 3);
  eq(mdMgr._lineIndentCols(''), 0);
});

check('גדר: פתיחה בעמודה 0 סוגרת את הרשימה', () => {
  // הבאג שדווח: הגדר לא נגעה במחסנית, ולכן ``  - ב`` שאחריה יצא תת-פריט
  // של ``- א`` — למרות שהגדר בעמודה 0 סיימה את הרשימה.
  // ארבע שורות תצוגה ולא חמש: הבלוק נצרך שלם ומייצר כותרת ושורת תוכן,
  // במקום שלוש שורות (גדר, תוכן, גדר).
  const { view } = renderMd(mdMgr, '- א\n```\n- לא רשימה\n```\n  - ב');
  eq(depths(view).join(','), '0,0,0,0');
  const rows = view.querySelectorAll('.sticky-task-line');
  const last = rows[rows.length - 1];
  eq(last.classList.contains('is-depth-1'), false, 'ואין מחלקת עומק על השורה שאחריה');
  eq(last.classList.contains('sticky-md-li'), true, 'והיא עדיין פריט רשימה');
});

check('גדר: פתיחה שאינה מגיעה לעמודת התוכן סוגרת גם היא', () => {
  // רווח אחד אינו מגיע לעמודה 2 שבה מתחיל הטקסט של ``- א``.
  const { view } = renderMd(mdMgr, '- א\n ```\n x\n ```\n  - ב');
  eq(depths(view).join(','), '0,0,0,0');
});

check('גדר: מקוננת סוגרת רק את מה שמעליה', () => {
  // הגדר בעמודה 2 סוגרת את ``  - ב`` (עמודת תוכן 4) ומשאירה את ``- א``
  // (עמודת תוכן 2) פתוח, ולכן ``    - ג`` יוצא רמה 1 ולא רמה 2.
  const { view } = renderMd(mdMgr, '- א\n  - ב\n  ```\n  x\n  ```\n    - ג');
  eq(depths(view).join(','), '0,1,0,0,1');
  const rows = view.querySelectorAll('.sticky-task-line');
  const last = rows[rows.length - 1];
  eq(last.classList.contains('is-depth-1'), true, 'מחלקת רמה 1');
  eq(last.classList.contains('is-depth-2'), false, 'ולא רמה 2');
});

check('בלוק מוזח לתוך פריט אינו סוגר אותו', () => {
  const h = renderMd(mdMgr, '- א\n  # כותרת\n  - ב');
  eq(depths(h.view).join(','), '0,0,1', 'כותרת מוזחת');
  const hr = renderMd(mdMgr, '- א\n  ---\n  - ב');
  eq(depths(hr.view).join(','), '0,0,1', 'קו מפריד מוזח');
  const q = renderMd(mdMgr, '- א\n  > ציטוט\n  - ב');
  eq(depths(q.view).join(','), '0,0,1', 'ציטוט מוזח');
  const t = renderMd(mdMgr, '- א\n  טקסט\n  - ב');
  eq(depths(t.view).join(','), '0,0,1', 'טקסט מוזח');
});

check('טבלה מוזחת לתוך פריט אינה סוגרת אותו', () => {
  const { view } = renderMd(mdMgr, '- א\n  | א | ב |\n  | --- | --- |\n  | 1 | 2 |\n  - ב');
  eq(depths(view).pop(), 1, 'הפריט שאחרי הטבלה נשאר בתוך הפריט שמעליה');
});

check('גדר: סגירה באותה הזחה — ההחרגה היא no-op הוכיח', () => {
  // התיעוד טוען שהחרגת שורת הסגירה מהכלל אינה בחירה אלא no-op, כל עוד
  // היא באותה הזחה שבה נפתחה: הפותחת כבר הוציאה כל פריט שמעל אותה
  // עמודה, ובתוך הגדר שום דבר אינו נדחף. זו טענה בת-בדיקה, ולכן היא
  // נבדקת ולא נשארת פרוזה.
  const stack = [2, 4];
  mdMgr._closeListsAbove(stack, 4);          // הגדר הפותחת, בעמודה 4
  const afterOpen = stack.join(',');
  mdMgr._closeListsAbove(stack, 4);          // אותה הזחה — הסגירה
  eq(stack.join(','), afterOpen, 'הרצה שנייה באותה הזחה אינה משנה דבר');
  eq(afterOpen, '2,4', 'ושתי הרמות נשארו פתוחות');
});

check('גדר: רק ההזחה של שורת הפתיחה קובעת', () => {
  // הטענה שעמוד המשתמש מבטיח, בארבעת הצירופים: הבלוק שייך למקום שבו
  // הוא **נפתח**, והזחת שורת הסגירה אינה משנה דבר. בלי הבדיקה הזו
  // ההבטחה שבתיעוד הייתה פרוזה שאפשר לשבור בשקט.
  const build = (open, close) =>
    ['- א', ' '.repeat(open) + '```', '  x', ' '.repeat(close) + '```', '  - ב'].join('\n');
  const last = (c) => depths(renderMd(mdMgr, c).view).pop();

  eq(last(build(0, 0)), 0, 'נפתחה בעמודה 0, נסגרה בעמודה 0 — הרשימה הסתיימה');
  eq(last(build(0, 2)), 0, 'נפתחה בעמודה 0, נסגרה מוזחת — עדיין הסתיימה');
  eq(last(build(2, 2)), 1, 'נפתחה מוזחת, נסגרה מוזחת — הפריט נשאר בפנים');
  eq(last(build(2, 0)), 1, 'נפתחה מוזחת, נסגרה בעמודה 0 — עדיין בפנים');
});

check('גדר: סגירה מוזחת החוצה — סטייה מתועדת, לא באג', () => {
  // ``- א`` (עמודת תוכן 2), גדר שנפתחת בעמודה 2 ונסגרת בעמודה 0.
  //
  // **הפער אינו במחסנית, ולכן גם לא ייסגר שם.** נמדד על כל צירוף של
  // הזחת פותחת × סוגרת × הפריט שאחריה: מימוש שבו גם שורת הסגירה
  // מעדכנת את המחסנית אינו מנצח באף צירוף — בשישה-עשר שני המימושים
  // תואמים ל-markdown-it, ובעשרים אף אחד לא. במקרה הזה הקוד נותן 0,1,
  // המימוש ההוא נותן 0,0, ו-markdown-it נותן 0 בלבד: שם הסגירה
  // המוזחת אינה סוגרת את הגדר כלל אלא מסיימת את הפריט, והתו נקרא
  // כפתיחת גדר חדשה שבולעת את שאר הפתק לבלוק קוד. השורש הוא התאמת
  // גדרות מודעת-מכולה, שהמנוע הזה אינו מממש בכוונה.
  //
  // הבדיקה מצמידה את ההתנהגות כדי שהיא תהיה החלטה ולא פער שנשכח.
  const { view } = renderMd(mdMgr, '- א\n  ```\n  x\n```\n  - ב');
  eq(depths(view).join(','), '0,0,0,1', 'הפריט שאחרי הסגירה נשאר בתוך הפריט שמעליו');
});

check('קינון: התקרה עוצרת את ההזחה ולא את התצוגה', () => {
  const deep = ['- 0', '  - 1', '    - 2', '      - 3', '        - 4',
                '          - 5', '            - 6'].join('\n');
  const { view } = renderMd(mdMgr, deep);
  eq(depths(view).join(','), '0,1,2,3,4,5,5', 'עומק 6 מקבל את מחלקת רמה 5');
  eq(view.querySelectorAll('.sticky-md-li').length, 7, 'וכל שבע השורות מוצגות');
});

check('קינון: מארקדאון כבוי — אין הזחה', () => {
  // כיבוי מציג את התוכן הגולמי כפי שהוקלד, וההזחה היא עיצוב מארקדאון.
  const off = new StickyNotesManager({ board: 'b-nest-off', markdown: false });
  const parts = makeNote('- [ ] א\n  - [ ] ב');
  off._syncTaskView(parts.el);
  eq(depths(parts.view).join(','), '0,0');
  eq(parts.view.querySelectorAll('.sticky-task-box').length, 2, 'הצ\'קבוקסים עדיין עובדים');
});

check('קינון: ה-CSS מזיח בפועל, ובכיוון הלוגי', () => {
  // **שומר טקסטואלי, לא מדידה.** ההזחה נמדדה בכרומיום ב-RTL — התבליט
  // זז מ-393.2 ל-379.2 ל-365.1 פיקסלים לאורך שלוש הרמות, ועל הקוד
  // שלפני התיקון כל השורות ישבו על 393.2. Playwright אינו בתלויות
  // הפרויקט ולכן ההארנס לא נשאר כאן; מה שנשאר הוא הבדיקה שההחלטה לא
  // בוטלה בשקט.
  const css = fs.readFileSync(
    path.join(__dirname, '..', 'webapp', 'static', 'css', 'sticky-notes.css'), 'utf8');
  eq(/--sticky-li-indent\s*:/.test(css), true, 'הטוקן מוגדר');
  for (let d = 1; d <= 5; d += 1) {
    eq(css.includes('.sticky-task-line.is-depth-' + d), true, 'כלל לרמה ' + d);
  }
  // המחלקה על ``.sticky-task-line`` ולא על ``.sticky-md-li``: זה האלמנט
  // המשותף לשורת רשימה ולשורת צ'קבוקס, ובלעדיו צ'קבוקס מוזח לא מוזח.
  eq(/\.sticky-md-li\.is-depth-/.test(css), false, 'המחלקה על שורת המקור, לא על פריט הרשימה');
  // ``padding-inline-start`` ולא ``padding-left`` — הפתקים בעברית, וכלל
  // פיזי היה מזיח מהצד הלא נכון. נמדד: ``padding-right`` הוא שקיבל ערך.
  const depthRules = css.split('\n').filter((l) => l.includes('.sticky-task-line.is-depth-'));
  eq(depthRules.length, 5, 'חמישה כללים');
  eq(depthRules.every((l) => l.includes('padding-inline-start')), true, 'תכונה לוגית בכל הכללים');
  eq(depthRules.some((l) => /padding-(left|right)\s*:/.test(l)), false, 'ואין תכונה פיזית');
  // כל כלל **מפנה** לטוקן. בלי זה שינוי שם של הטוקן משאיר את ההגדרה
  // ואת הכללים במקומם, ה-``calc`` נשבר, וההזחה יורדת ל-0 בשקט.
  eq(depthRules.every((l) => l.includes('var(--sticky-li-indent)')), true, 'כל כלל מפנה לטוקן');
});

check('רינדור: מארקדאון כבוי מציג טקסט גולמי', () => {
  const off = new StickyNotesManager({ board: 'b-off', markdown: false });
  const parts = makeNote('# כותרת\n**מודגש**');
  off._syncTaskView(parts.el);
  eq(!!parts.view.querySelector('.sticky-md-h1'), false, 'אין רינדור כותרת');
  // בלי צ'קבוקס ובלי מארקדאון — נשאר textarea
  eq(parts.view.hidden, true, 'התצוגה מוסתרת');
  eq(parts.ta.hidden, false, 'ה-textarea גלוי');
});

check('רינדור: setMarkdown מכבה ומנקה', () => {
  const parts = makeNote('# כותרת');
  mdMgr.notes.set('md-toggle', { el: parts.el, data: { id: 'md-toggle' } });
  parts.el.dataset.noteId = 'md-toggle';
  mdMgr._syncTaskView(parts.el);
  eq(!!parts.view.querySelector('.sticky-md-h1'), true, 'דלוק — מרונדר');

  mdMgr.setMarkdown(false);
  // **הניקוי ביציאה.** בלי ``view.textContent=''`` הצומת שרד ב-DOM המוסתר.
  eq(!!parts.view.querySelector('.sticky-md-h1'), false, 'כבוי — נוקה');
  mdMgr.setMarkdown(true);
  mdMgr.notes.delete('md-toggle');
});

// ---------- נתיב המקלדת של התצוגה ----------
//
// אירוע מדומה עם ``preventDefault`` שסופר את עצמו, ו-``target`` שהוא
// FakeEl. המתודות חולצו מהסגורים בדיוק כדי שאפשר יהיה לבדוק אותן כאן.

function keyEvent(key, target){
  return { key, target, _prevented: false, preventDefault(){ this._prevented = true; } };
}
function linkTarget(){
  const a = new FakeEl('a');
  a.className = 'sticky-md-link';
  const row = new FakeEl('div'); row.className = 'sticky-task-line';
  row.dataset = { charOffset: '0' };
  row.appendChild(a);   // מגדיר parentNode, כך ש-closest מטפס אמיתית
  return a;
}

check('מקלדת: Enter על קישור אינו מבטל ואינו נכנס לעריכה', () => {
  const { el } = registerNote(fileMgr, 'kbd-enter', 'ראה קישור');
  FakeEl.focused = null;
  const ev = keyEvent('Enter', linkTarget());
  fileMgr._viewKeydown(el, ev);
  eq(ev._prevented, false, 'לא בוטל — הדפדפן מפעיל את הקישור');
  eq(FakeEl.focused, null, 'ולא נכנס לעריכה (אין focus)');
});

check('מקלדת: Space על קישור מבטל (בולם גלילה) ולא נכנס לעריכה', () => {
  const { el } = registerNote(fileMgr, 'kbd-space', 'ראה קישור');
  FakeEl.focused = null;
  const ev = keyEvent(' ', linkTarget());
  fileMgr._viewKeydown(el, ev);
  eq(ev._prevented, true, 'בוטל — Space לא גולל את הדף');
  eq(FakeEl.focused, null, 'אבל גם לא נכנס לעריכה על קישור');
});

check('מקלדת: Enter על טקסט רגיל נכנס לעריכה', () => {
  const { el, ta } = registerNote(fileMgr, 'kbd-text', 'שורת טקסט');
  const row = new FakeEl('div'); row.className = 'sticky-task-line'; row.dataset = { charOffset: '0' };
  const span = new FakeEl('span'); row.appendChild(span);
  const ev = keyEvent('Enter', span);
  fileMgr._viewKeydown(el, ev);
  eq(ev._prevented, true, 'בוטל — נכנסים לעריכה');
  eq(FakeEl.focused === ta, true, 'ה-textarea קיבל focus');
});

check('מקלדת: מקש אחר אינו עושה כלום', () => {
  const { el } = registerNote(fileMgr, 'kbd-other', 'טקסט');
  const ev = keyEvent('a', linkTarget());
  fileMgr._viewKeydown(el, ev);
  eq(ev._prevented, false, 'לא בוטל');
});

// -- היעד השלישי: קובץ בריפו ממורר --

check('repo+path נקראים כיעד ריפו', () => {
  const m = new StickyNotesManager({ repo: 'CodeBot', path: 'webapp/app.py' });
  eq(m.repoTarget.repo, 'CodeBot', 'repo');
  eq(m.repoTarget.path, 'webapp/app.py', 'path');
  eq(m.boardId, null, 'boardId');
  eq(m.fileId, null, 'fileId');
});

check('כתובת ה-API של יעד ריפו שומרת על הלוכסנים במבנה', () => {
  // ``<path:repo_path>`` מצפה למבנה, לא למחרוזת מקודדת: encodeURIComponent
  // על הנתיב כולו היה הופך ``/`` ל-``%2F`` והראוט לא היה מותאם כלל.
  const m = new StickyNotesManager({ repo: 'CodeBot', path: 'webapp/app.py' });
  eq(m._scopeUrl, '/api/sticky-notes/repo/CodeBot/webapp/app.py');
});

check('רכיב נתיב עם תו מיוחד מקודד לחוד', () => {
  const m = new StickyNotesManager({ repo: 'My Repo', path: 'a b/c#d.py' });
  eq(m._scopeUrl, '/api/sticky-notes/repo/My%20Repo/a%20b/c%23d.py');
});

check('מפתח הקאש של ריפו נפרד מקובץ ומלוח', () => {
  // בלי ההפרדה, ריפו וקובץ עם אותה מחרוזת היו חולקים קאש ומרנדרים זה את
  // הפתקים של זה — בדיוק הבאג שכבר נתפס בין לוח לקובץ.
  const repo = new StickyNotesManager({ repo: 'same', path: 'a.py' });
  const file = new StickyNotesManager('same');
  const board = new StickyNotesManager({ board: 'same' });
  eq(repo._cacheKey, 'sticky-notes:repo:same:a.py');
  if (repo._cacheKey === file._cacheKey) throw new Error('התנגשות עם מפתח הקובץ');
  if (repo._cacheKey === board._cacheKey) throw new Error('התנגשות עם מפתח הלוח');
});

check('חצי יעד ריפו אינו יעד', () => {
  // repo בלי path (או להפך) אינו מזהה קובץ — ובלי הבדיקה הוא היה נופל
  // בשקט למסלול הקובץ עם fileId ריק.
  let threwRepoOnly = false, threwPathOnly = false;
  try { new StickyNotesManager({ repo: 'CodeBot' }); } catch (_) { threwRepoOnly = true; }
  try { new StickyNotesManager({ path: 'a.py' }); } catch (_) { threwPathOnly = true; }
  if (!threwRepoOnly) throw new Error('repo בלי path התקבל');
  if (!threwPathOnly) throw new Error('path בלי repo התקבל');
});

check('לפתק ריפו אין מקור עוגנים', () => {
  // התצוגה היא CodeMirror, שאינו מרנדר שורות מחוץ למסך — אין DOM להיצמד
  // אליו, ולכן העיגון הוא ברמת קובץ בלבד.
  const m = new StickyNotesManager({ repo: 'CodeBot', path: 'a.py' });
  eq(m._hasAnchorHost, false);
});

check('יעד ריפו הוא יעד עם משטח תחום', () => {
  const repo = new StickyNotesManager({ repo: 'CodeBot', path: 'a.py' });
  const board = new StickyNotesManager({ board: 'b1' });
  const file = new StickyNotesManager('f1');
  eq(repo._surfaceTarget, true, 'repo');
  eq(board._surfaceTarget, true, 'board');
  eq(file._surfaceTarget, false, 'file — חייב להישאר כבוי');
});

check('פתק ריפו לעולם אינו anchored', () => {
  // גם כשהמסמך נושא שרידי עיגון — למשל פתק שנוצר לפני שהיעד הופרד.
  const m = new StickyNotesManager({ repo: 'CodeBot', path: 'a.py' });
  eq(m._resolveMode({ anchor_id: 'h-intro', line_start: 42 }), 'screen');
  eq(m._resolveMode({ mode: 'anchored' }), 'surface');
});

check('מארקדאון דלוק כברירת מחדל גם בפתקי ריפו', () => {
  // שלושת היעדים מתנהגים אותו דבר. מתג הכיבוי קיים בלוח בלבד, וזה
  // מתועד ב-``docs/user/sticky_notes.rst``.
  const m = new StickyNotesManager({ repo: 'CodeBot', path: 'a.py' });
  eq(m.markdown, true);
});

check('markdown מפורש ב-opts גובר על ברירת המחדל', () => {
  // הדלת שדרכה קורא יכול לבטל — ``('markdown' in opts)`` נבדק לפני
  // ברירת המחדל. בלי הבדיקה הזו, הדלקה גורפת הייתה יכולה להתעלם ממנה
  // בשקט.
  const off = new StickyNotesManager({ repo: 'CodeBot', path: 'a.py', markdown: false });
  eq(off.markdown, false, 'false מפורש מכבה');
  const on = new StickyNotesManager({ repo: 'CodeBot', path: 'a.py', markdown: true });
  eq(on.markdown, true, 'true מפורש מדליק');
});

// -- טבלאות מארקדאון --

const TBL = '| # | שאלה |\n|---|---|\n| 1 | ראשונה |\n| 2 | שנייה |';

check('טבלה: שורת מפריד תקפה בונה <table> עם thead ו-tbody', () => {
  const { view } = renderMd(mdMgr, TBL);
  const table = view.querySelector('table.sticky-md-table');
  eq(!!table, true, 'נבנתה טבלה');
  eq(table.querySelectorAll('th').length, 2, 'שני תאי כותרת');
  // ``FakeEl`` אינו תומך בסלקטור צאצא (``'tbody tr'``), ולכן שואלים את
  // ה-``tbody`` עצמו — וזה גם מדויק יותר: מוודא שהשורות באמת בתוכו.
  const tbody = table.querySelector('tbody');
  eq(!!tbody, true, 'יש tbody');
  eq(tbody.querySelectorAll('tr').length, 2, 'שתי שורות גוף');
  eq(tbody.querySelectorAll('td').length, 4, 'ארבעה תאי גוף');
});

check('טבלה: שורה עם | בלי מפריד נשארת טקסט', () => {
  // בלי התנאי הזה כל שורה שמכילה מקף אנכי — נתיב, פקודה, ביטוי לוגי —
  // הייתה נבלעת לטבלה.
  const { view } = renderMd(mdMgr, '| זה לא | טבלה |\nעוד שורה');
  eq(!!view.querySelector('table'), false, 'לא נבנתה טבלה');
});

check('טבלה: יישור מ-: נכתב כ-text-align', () => {
  const { view } = renderMd(mdMgr, '| א | ב | ג |\n|:---|---:|:---:|\n| 1 | 2 | 3 |');
  const th = view.querySelectorAll('th');
  eq(th[0].style.textAlign, 'left', 'יישור שמאלה');
  eq(th[1].style.textAlign, 'right', 'יישור ימינה');
  eq(th[2].style.textAlign, 'center', 'מרכוז');
});

check('טבלה: scope=col על תאי הכותרת', () => {
  const { view } = renderMd(mdMgr, TBL);
  eq(view.querySelector('th').getAttribute('scope'), 'col');
});

check('טבלה: תוכן תא עובר את אותו מסלול בטוח', () => {
  // אותו חוזה textContent כמו בכל שאר הבלוקים: תגית בתא נשארת טקסט,
  // ומודגש בתא כן מרונדר.
  const { view } = renderMd(mdMgr, '| א | ב |\n|---|---|\n| <script>x</script> | **מודגש** |');
  eq(!!view.querySelector('script'), false, 'אין תגית script');
  eq(!!view.querySelector('.sticky-md-bold'), true, 'המודגש כן רונדר');
});

check('טבלה: כל שורת מקור נושאת את ה-charOffset שלה', () => {
  // **הבאג שאינו נראה בעין.** אם כל ה-<tr> יקבלו את אותו היסט, הטבלה
  // תיראה מושלמת ולחיצה על השורה השלישית תחזיר לעריכה בראשונה.
  const { view } = renderMd(mdMgr, TBL);
  const rows = view.querySelectorAll('.sticky-task-line');
  const offsets = rows.map((r) => Number(r.dataset.charOffset));
  const lines = TBL.split('\n');
  // שורת הכותרת בהיסט 0; שורת המפריד נצרכת ואינה מייצרת שורה; שתי שורות
  // הגוף מתחילות אחרי הכותרת והמפריד.
  eq(offsets[0], 0, 'שורת הכותרת');
  eq(offsets[1], lines[0].length + 1 + lines[1].length + 1, 'שורת הגוף הראשונה');
  eq(offsets[2], lines[0].length + 1 + lines[1].length + 1 + lines[2].length + 1, 'שורת הגוף השנייה');
  eq(new Set(offsets).size, offsets.length, 'כל ההיסטים שונים זה מזה');
});

check('טבלה: השורה שאחרי הטבלה ממשיכה מההיסט הנכון', () => {
  // המקרה המשלים: כאן נתפס חשבון מצטבר שגוי, גם אם המיפוי בתוך הבלוק תקין.
  const content = TBL + '\nאחרי הטבלה';
  const { view } = renderMd(mdMgr, content);
  const rows = view.querySelectorAll('.sticky-task-line');
  const last = rows[rows.length - 1];
  eq(last.textContent, 'אחרי הטבלה', 'זו אכן השורה שאחרי');
  eq(Number(last.dataset.charOffset), content.indexOf('אחרי הטבלה'), 'ההיסט מצביע לתחילתה');
});

check('טבלה לבדה פותחת את התצוגה', () => {
  // בלי זיהוי טבלה ב-``_hasRenderableMarkdown``, פתק שכולו טבלה לא היה
  // עובר את השער והתצוגה כלל לא נפתחת — כשל שקט במקרה הנפוץ ביותר.
  eq(mdMgr._hasRenderableMarkdown(TBL.split('\n')), true);
});

check('טבלה: מספר תאים שאינו תואם בין כותרת למפריד אינו טבלה', () => {
  // **הבדיקה שהגנה על עצמה ולא נבדקה.** הטסט השלילי הקודם נפל כבר על
  // ``MD_TABLE_SEP_RE`` ולא הגיע להשוואת הספירה, ולכן מחיקת ההשוואה
  // הייתה משאירה את כל הטסטים ירוקים. כאן שורת המפריד תקפה לגמרי,
  // והדחייה יכולה לנבוע רק מהספירה.
  const { view } = renderMd(mdMgr, '| א | ב | ג |\n|---|---|\n| 1 | 2 | 3 |');
  eq(!!view.querySelector('table'), false, 'שלוש עמודות מול שתיים — לא טבלה');
});

check('טבלה: פייפ בורח אינו מפריד תאים', () => {
  // ``MD_TABLE_ROW_RE`` ספר פייפים גולמיים בעוד ``_splitTableRow`` מודע
  // ל-escape — שני חלקים שחלוקים על מהו מפריד.
  const { view } = renderMd(mdMgr, 'a \\| b\n---\nעוד');
  eq(!!view.querySelector('table'), false, 'פייפ בורח בלבד — לא טבלה');
});

check('טבלה: פייפ סוגר בלבד אינו טבלה', () => {
  // ``grep foo |`` ואחריו קו מפריד — בדיוק המקרה שההערה בקוד הבטיחה
  // שיישאר טקסט ורגל, ובפועל הפך לטבלה של עמודה אחת.
  const { view } = renderMd(mdMgr, 'grep foo |\n---\nעוד');
  eq(!!view.querySelector('table'), false, 'אין פייפ פנימי — לא טבלה');
  eq(!!view.querySelector('.sticky-md-hr'), true, 'והקו המפריד נשאר קו');
});

check('טבלה: פייפ סוגר בורח נשאר בתוכן התא', () => {
  const cells = mdMgr._splitTableRow('| a | b\\|');
  eq(cells.length, 2, 'שני תאים');
  eq(cells[1], 'b|', 'הפייפ הבורח נשאר בתוכן, בלי לוכסן מיותר');
});

check('טבלה: פותחת גדר עם פייפ נשארת גדר', () => {
  const { view } = renderMd(mdMgr, '```sh | x\n---|---\nקוד\n```');
  eq(!!view.querySelector('table'), false, 'לא נבנתה טבלה');
  // ``FakeEl._matches`` תומך ב-``.class`` ובּ-``tag.class``, לא בשתי
  // מחלקות. שתי שאילתות נפרדות, ולכן גם מדויקות יותר.
  eq(!!view.querySelector('.sticky-md-code-block'), true, 'נפתח בלוק קוד');
  // ``sh`` היא המילה הראשונה שאחרי הגדר, ולכן היא שם השפה — והפייפ
  // שאחריה אינו הופך את השורה לטבלה.
  eq(view.querySelector('.sticky-md-code-lang').textContent, 'sh', 'ושם השפה נגזר ממנה');
});

check('טבלה: שורת משימה שנצרכת לטבלה עדיין מקדמת את האינדקס', () => {
  // **החמור מכולם.** הפייפ הסוגר אופציונלי, ולכן ``- [ ] משימה | עמודה``
  // הוא גם שורת משימה וגם כותרת טבלה תקפה. אם הצריכה אינה מקדמת את
  // הסידור, כל צ'קבוקס אחריה נשלח לשרת עם אינדקס של משימה אחרת.
  const { view } = renderMd(mdMgr, '- [ ] בטבלה | עמודה\n---|---\n| 1 | 2 |\n- [ ] אחרי');
  const boxes = view.querySelectorAll('.sticky-task-box');
  eq(boxes.length, 1, 'צ׳קבוקס אינטראקטיבי אחד — זה שמחוץ לטבלה');
  eq(boxes[0].dataset.taskIndex, '1', 'והאינדקס שלו 1, כי המשימה שבטבלה נספרה');
});

check('טבלה: לחיצה על שורה בתוך הטבלה מחזירה לעריכה באותה שורה', () => {
  // ההיסט הנכון על ה-``<tr>`` אינו מספיק: ``_enterEditFromView`` חייב
  // באמת למצוא אותו דרך ``closest('.sticky-task-line')``. בלי הבדיקה הזו
  // ההיסט יכול להיות מדויק והלחיצה עדיין תיפול לראש הפתק.
  const content = '| # | ש |\n|---|---|\n| 1 | א |\n| 2 | ב |';
  const { el, ta, view } = renderMd(mdMgr, content);
  const rows = view.querySelectorAll('tr');
  const target = rows[rows.length - 1];       // שורת הגוף השנייה
  const cell = target.querySelectorAll('td')[1];
  cell.parentNode = target;
  mdMgr._enterEditFromView(el, { target: cell });
  eq(ta.selectionStart, content.indexOf('| 2 | ב |'), 'הסמן בתחילת השורה שנלחצה');
});

check('טבלה: שורת גוף עם תא יחיד נשארת בטבלה', () => {
  // ב-GFM שורת גוף רשאית להכיל פחות תאים מהכותרת, והחסרים ריקים.
  // ``addRow`` כבר מרפד לפי ``spec.align``; מה שהפסיק את הטבלה היה תנאי
  // הסיום, שדרש שני תאים גם משורות הגוף.
  const { view } = renderMd(mdMgr, '| א | ב |\n|---|---|\n| רק אחד |\n| 1 | 2 |');
  const tbody = view.querySelector('tbody');
  eq(tbody.querySelectorAll('tr').length, 2, 'שתי שורות גוף');
  eq(tbody.querySelectorAll('td').length, 4, 'וארבעה תאים — החסר רופד');
});

check('טבלה: שורת גוף עם פייפ מוברח נשארת בטבלה', () => {
  // תא שמכיל ``\\|`` מתפצל לתא אחד, ולכן התנאי הישן היה מסיים עליו את
  // הטבלה — למרות שהשורה בבירור שורת טבלה.
  const { view } = renderMd(mdMgr, '| א | ב |\n|---|---|\n| a\\|b |\n| 1 | 2 |');
  const tbody = view.querySelector('tbody');
  eq(tbody.querySelectorAll('tr').length, 2, 'שתי שורות גוף');
  eq(tbody.querySelectorAll('td')[0].textContent, 'a|b', 'והפייפ נשאר בתוכן התא');
});

check('טבלה: שורה בלי מפריד כלל מסיימת את הטבלה', () => {
  // הצד השני של אותו תנאי — בלי זה הטבלה הייתה בולעת את כל מה שאחריה.
  const { view } = renderMd(mdMgr, '| א | ב |\n|---|---|\n| 1 | 2 |\nטקסט רגיל');
  eq(view.querySelector('tbody').querySelectorAll('tr').length, 1, 'שורת גוף אחת');
  const rows = view.querySelectorAll('.sticky-task-line');
  eq(rows[rows.length - 1].textContent, 'טקסט רגיל', 'והשורה האחרונה היא טקסט');
});

// ---------- בלוק קוד: כותרת, שפה והעתקה ----------

check('בלוק קוד: שורות הגדר נצרכות ואינן מוצגות', () => {
  const { view } = renderMd(mdMgr, '```python\nx = 1\n```');
  eq(view.textContent.includes('```'), false, 'אין תווי גדר בתצוגה כלל');
  eq(view.querySelectorAll('.sticky-md-pre').length, 1, 'שורת תוכן אחת');
});

check('בלוק קוד: שם השפה מוצג, וריק כשאין', () => {
  eq(renderMd(mdMgr, '```python\nx\n```').view.querySelector('.sticky-md-code-lang').textContent,
     'python', 'שם השפה');
  eq(renderMd(mdMgr, '```\nx\n```').view.querySelector('.sticky-md-code-lang').textContent,
     '', 'גדר בלי שפה — תווית ריקה');
  // רק המילה הראשונה, כמו ש-``markdown-it`` גוזר את שם השפה מה-``info``.
  eq(renderMd(mdMgr, '```js title="a b"\nx\n```').view.querySelector('.sticky-md-code-lang').textContent,
     'js', 'המילה הראשונה בלבד');
});

check('בלוק קוד: שם השפה הוא טקסט, לעולם לא תגית', () => {
  // הטקסט שאחרי הגדר הוא קלט משתמש לכל דבר.
  const { view } = renderMd(mdMgr, '```<script>alert(1)</script>\nx\n```');
  const lang = view.querySelector('.sticky-md-code-lang');
  eq(lang.textContent, '<script>alert(1)</script>', 'הוצג כטקסט');
  eq(lang.innerHTML, '', 'ולא נכתב כ-HTML');
});

check('בלוק קוד: כפתור העתקה עם אייקון', () => {
  const { view } = renderMd(mdMgr, '```\nx\n```');
  const btn = view.querySelector('.sticky-md-code-copy');
  eq(!!btn, true, 'הכפתור קיים');
  eq(btn.getAttribute('type'), 'button', 'type=button — אחרת הוא שולח טפסים');
  eq(!!btn.getAttribute('aria-label'), true, 'ויש לו שם נגיש');
  // **``createElementNS`` ולא ``innerHTML``.** בדיקה על ``innerHTML``
  // ריק היא מה שמונע חזרה בשקט לבניית האייקון ממחרוזת.
  eq(btn.children.length, 1, 'ילד אחד — האייקון');
  eq(btn.children[0].tagName, 'svg', 'והוא נבנה כצומת SVG');
  eq(btn.innerHTML, '', 'ולא הוזרק כ-HTML');
});

check('בלוק קוד: ההעתקה לוקחת את הגוף מהמקור, בלי הגדרות', async () => {
  // **המקור ולא ה-DOM.** שורה ריקה מרונדרת כרווח כדי לא לקרוס לגובה
  // אפס, ולכן קריאה מה-DOM הייתה מחזירה ``" "`` במקום ``""`` — נמדד.
  const captured = [];
  const real = mdMgr._copyText;
  mdMgr._copyText = async (t) => { captured.push(t); return true; };
  try {
    const { view } = renderMd(mdMgr, '```python\ndef f():\n\n    return 1\n```');
    const btn = view.querySelector('.sticky-md-code-copy');
    await btn._listeners.click({ stopPropagation(){} });
  } finally {
    mdMgr._copyText = real;
  }
  eq(captured.length, 1, 'נשלחה העתקה אחת');
  eq(captured[0], 'def f():\n\n    return 1', 'הגוף בדיוק, עם השורה הריקה ובלי הגדרות');
});

check('בלוק קוד: לחיצה על הכותרת מחזירה לעריכה בשורת הגדר', () => {
  // **זה מה שמונע מבוי סתום.** בלי הכותרת כשורת מקור, בלוק ריק
  // (גדר ומיד גדר) היה יוצא בלי שום שורה לחיצה, ואי אפשר היה לחזור
  // ממנו לעריכה בכלל.
  const content = 'לפני\n```py\nx\n```';
  const { el, ta, view } = renderMd(mdMgr, content);
  const head = view.querySelector('.sticky-md-code-head');
  eq(Number(head.dataset.charOffset), content.indexOf('```py'), 'ההיסט של שורת הפתיחה');
  mdMgr._enterEditFromView(el, { target: head.querySelector('.sticky-md-code-lang') });
  eq(ta.selectionStart, content.indexOf('```py'), 'והלחיצה נוחתת שם');
});

check('בלוק קוד: לחיצה על כפתור ההעתקה אינה נכנסת לעריכה', () => {
  // הכפתור יושב **בתוך** שורת המקור, ולכן בלי ההחרגה הוא היה מעתיק
  // ובאותה לחיצה מפיל את התצוגה לעריכה.
  const { el, view } = renderMd(mdMgr, '```\nx\n```');
  const btn = view.querySelector('.sticky-md-code-copy');
  eq(mdMgr._enterEditFromView(el, { target: btn }), false, 'לא נכנסנו לעריכה');
});

check('בלוק קוד: charOffset של השורה שאחרי הבלוק', () => {
  // שורת הסגירה נצרכת בלי אלמנט, אבל ההיסט מקודם עליה — אחרת כל מה
  // שאחרי הבלוק מוסט באורך שורה שלמה.
  const content = '```py\nx = 1\ny = 2\n```\nאחרי הבלוק';
  const { el, ta, view } = renderMd(mdMgr, content);
  const rows = view.querySelectorAll('.sticky-task-line');
  const last = rows[rows.length - 1];
  eq(last.textContent, 'אחרי הבלוק', 'זו השורה שאחרי');
  eq(Number(last.dataset.charOffset), content.indexOf('אחרי הבלוק'), 'וההיסט מצביע לתחילתה');
  mdMgr._enterEditFromView(el, { target: last });
  eq(ta.selectionStart, content.indexOf('אחרי הבלוק'), 'והלחיצה נוחתת שם');
});

check('בלוק קוד: אינדקס המשימות אינו זז', () => {
  // **החוזה מול השרת.** ``sticky_notes_tasks`` סופר כל שורת ``- [ ]``
  // כולל בתוך גדר, ולכן ``tasksConsumed`` חייב להתקדם על שורות הגדר
  // שנצרכו. בלעדיו כל צ'קבוקס שאחרי בלוק קוד מסמן משימה אחרת.
  const { view } = renderMd(mdMgr, '- [ ] לפני\n```\n- [ ] בקוד\n- [x] גם בקוד\n```\n- [ ] אחרי');
  const boxes = view.querySelectorAll('.sticky-task-box');
  eq(boxes.length, 2, 'שתי תיבות אינטראקטיביות — אלה שמחוץ לגדר');
  eq(boxes.map((b) => b.dataset.taskIndex).join(','), '0,3', 'והשנייה היא 3, כי שתיים נספרו בגדר');
});

check('בלוק קוד: גדר שלא נסגרה נמשכת עד סוף הפתק', () => {
  const { view } = renderMd(mdMgr, '```py\nא\nב');
  eq(!!view.querySelector('.sticky-md-code-block'), true, 'נבנה בלוק');
  eq(view.querySelectorAll('.sticky-md-pre').length, 2, 'שתי שורות תוכן');
  eq(view.querySelector('.sticky-md-code-lang').textContent, 'py', 'והשפה נקראה');
});

check('בלוק קוד: בלוק ריק עדיין ניתן לחזרה לעריכה', () => {
  // גדר ומיד גדר. אין שורת תוכן, ולכן הכותרת היא **היחידה** שאפשר
  // ללחוץ עליה — וזה בדיוק מה שהיא שם בשבילו.
  const content = '```\n```';
  const { el, ta, view } = renderMd(mdMgr, content);
  eq(view.querySelectorAll('.sticky-md-pre').length, 0, 'אין שורות תוכן');
  const head = view.querySelector('.sticky-md-code-head');
  mdMgr._enterEditFromView(el, { target: head });
  eq(ta.selectionStart, 0, 'הלחיצה על הכותרת מחזירה לעריכה');
});

check('בלוק קוד: בתוך אלרט נבנה בתוכו ולא לצידו', () => {
  const { view } = renderMd(mdMgr, '::: note\n```py\nx\n```\n:::');
  const body = view.querySelector('.admonition-content');
  eq(!!body.querySelector('.sticky-md-code-block'), true, 'הבלוק בתוך גוף האלרט');
  eq(view.children.length, 1, 'ואין שום דבר לצד האלרט');
});

check('בלוק קוד: מארקדאון כבוי — הגדרות מוצגות כטקסט גולמי', () => {
  const off = new StickyNotesManager({ board: 'code-off', markdown: false });
  const parts = makeNote('```py\n- [ ] משימה\n```');
  off._syncTaskView(parts.el);
  eq(!!parts.view.querySelector('.sticky-md-code-block'), false, 'אין בלוק');
  eq(parts.view.textContent.includes('```py'), true, 'הגדר מוצגת כפי שהוקלדה');
});

check('בלוק קוד: ה-CSS מעצב את העוטפת ואין יותר is-fence', () => {
  const css = fs.readFileSync(
    path.join(__dirname, '..', 'webapp', 'static', 'css', 'sticky-notes.css'), 'utf8');
  const decls = css.replace(/\/\*[\s\S]*?\*\//g, '');
  ['.sticky-md-code-block', '.sticky-md-code-head', '.sticky-md-code-lang',
   '.sticky-md-code-copy'].forEach((sel) => {
    eq(decls.includes(sel + ' {') || decls.includes(sel + '.'), true, 'כלל ל-' + sel);
  });
  // הפינות העגולות עברו לעוטפת. הכלל הישן ניסה לזהות "תחילת רצף" לפי
  // השכן, וכבר נדרש שם תיקון פעם אחת.
  eq(/\.is-fence/.test(decls), false, 'אין שאריות של המחלקה שבוטלה');
  // חיווי **כשל** ולא רק הצלחה — אותה דרישה כמו בכפתור של הפתק.
  eq(decls.includes('.sticky-md-code-copy.is-copy-fail'), true, 'יש חיווי כשל');
});

// ---------- בלוקי אלרט (``::: note``) ----------
//
// התחביר אינו שלנו: הוא של ``markdown-it-container@4.0.0``, שמרנדר את אותם
// בלוקים בתצוגת המסמך. **כל הציפיות כאן נמדדו מולו בפועל** ולא נזכרו —
// הורצה השוואה של מבנה הקינון על 31 קלטים, וכולם תאמו.

/** האלרטים בתצוגה, כרשימה שטוחה של ``{ type, title }`` לפי סדר הופעה. */
function alerts(view){
  return view.querySelectorAll('.admonition').map((box) => {
    const type = [...box._classes].find((c) => c.startsWith('admonition-')).slice('admonition-'.length);
    const label = box.querySelector('.sticky-md-alert-label');
    return { type, title: label ? label.textContent : null };
  });
}

check('אלרט: ::: note בונה מעטפת עם הכותרת בעברית ועם אייקון', () => {
  const { view } = renderMd(mdMgr, '::: note\nגוף\n:::');
  const found = alerts(view);
  eq(found.length, 1, 'אלרט אחד');
  eq(found[0].type, 'note', 'הסוג על המחלקה');
  eq(found[0].title, 'הערה', 'התווית מ-ADMONITION_TITLES');
  const icon = view.querySelector('.sticky-md-alert-icon');
  eq(!!icon, true, 'יש חריץ אייקון');
  eq(icon.innerHTML.startsWith('<svg'), true, 'והוא מכיל את ה-SVG המשותף');
});

check('אלרט: כל הסוגים שבמפה המשותפת מזוהים', () => {
  // **הרשימה נגזרת מהמפה ולא מוקלדת כאן.** רשימה מוקלדת הייתה נשארת
  // מאחור בדיוק כשמישהו מוסיף סוג חדש — כלומר בדיוק כשהיא נחוצה.
  const types = Object.keys(sandbox.window.ADMONITION_TITLES);
  eq(types.length > 0, true, 'המפה נטענה לסנדבוקס');
  types.forEach((type) => {
    const { view } = renderMd(mdMgr, '::: ' + type + '\nגוף\n:::');
    const found = alerts(view);
    eq(found.length, 1, 'הסוג ' + type + ' מזוהה');
    eq(found[0].title, sandbox.window.ADMONITION_TITLES[type], 'התווית של ' + type);
  });
});

check('אלרט: סוג לא מוכר נשאר טקסט', () => {
  // נמדד מול markdown-it-container: סוג שלא נרשם אינו מכולה, והשורה
  // מרונדרת כפסקה רגילה.
  // ``**גוף**`` כאן אינו קישוט: ``::: foo`` לבדו הוא פתק בלי שום מבנה
  // מארקדאון, ולכן התצוגה כלל אינה נפתחת — נכון, אבל אז הבדיקה הייתה
  // עוברת בלי לבדוק כלום. המבנה פותח את התצוגה, וכך נראה מה קרה לשורה.
  const { view } = renderMd(mdMgr, '::: foo\n**גוף**\n:::');
  eq(alerts(view).length, 0, 'לא נבנה אלרט');
  eq(view.textContent.includes('::: foo'), true, 'והשורה נשארה גלויה כטקסט');
  eq(view.textContent.includes(':::'), true, 'וגם שורת הסגירה, שאינה סוגרת דבר');
});

check('אלרט: גבול מילה — ספרה וקו תחתון פוסלים, נקודה לא', () => {
  // שלושתם נמדדו: ``::: note2`` ו-``::: note_x`` אינם מכולה כי ה-``\b``
  // בוולידציה של התוסף נכשל בין שני תווי-מילה; ``::: note.x`` כן מכולה,
  // והשארית הופכת לכותרת.
  eq(alerts(renderMd(mdMgr, '::: note2\nא\n:::').view).length, 0, 'note2');
  eq(alerts(renderMd(mdMgr, '::: note_x\nא\n:::').view).length, 0, 'note_x');
  eq(alerts(renderMd(mdMgr, '::: noteX\nא\n:::').view).length, 0, 'noteX');
  const dotted = alerts(renderMd(mdMgr, '::: note.x\nא\n:::').view);
  eq(dotted.length, 1, 'note.x כן');
  eq(dotted[0].title, '.x', 'והשארית היא הכותרת');
});

check('אלרט: :::note בלי רווח, ורישיות אינה משנה', () => {
  eq(alerts(renderMd(mdMgr, ':::note\nא\n:::').view).length, 1, 'בלי רווח');
  eq(alerts(renderMd(mdMgr, '::: NOTE\nא\n:::').view)[0].type, 'note', 'אותיות גדולות');
});

check('אלרט: כותרת מותאמת גוברת על תווית ברירת המחדל', () => {
  const found = alerts(renderMd(mdMgr, '::: warning שים לב!\nא\n:::').view);
  eq(found[0].type, 'warning');
  eq(found[0].title, 'שים לב!', 'הטקסט שאחרי הסוג');
});

check('אלרט: רק מחרוזת נכנסת ל-innerHTML של האייקון', () => {
  // ``_appendAlertIcon`` הוא **המקום היחיד בקובץ שנוגע ב-``innerHTML``**,
  // ולכן החוזה שלו הוא היחיד שצריך שמירה מפורשת: נכנסת לשם מחרוזת
  // סטטית מהמפה המשותפת, ושום דבר אחר. בלי בדיקת הטיפוס, ערך שאינו
  // מחרוזת היה נכתב כ-``[object Object]`` בתוך הכותרת.
  const icons = sandbox.window.ADMONITION_ICONS;
  const saved = icons.note;
  try {
    icons.note = { evil: true };
    const { view } = renderMd(mdMgr, '::: note\nגוף\n:::');
    eq(alerts(view).length, 1, 'האלרט עדיין נבנה');
    eq(!!view.querySelector('.sticky-md-alert-icon'), false, 'ובלי חריץ אייקון כלל');
    eq(view.textContent.includes('[object Object]'), false, 'ושום דבר לא דלף לתצוגה');
  } finally {
    icons.note = saved;
  }
});

check('אלרט: הכותרת המותאמת היא טקסט, לעולם לא תגית', () => {
  // **החוק שמעל כל השאר בפתקים.** הכותרת היא טקסט שהמשתמש הקליד, ולכן
  // היא נכתבת ל-``textContent`` על צומת נפרד מהאייקון. ``innerHTML`` על
  // אותו צומת היה הופך את הזריקה לתגית.
  const { view } = renderMd(mdMgr, '::: note <script>alert(1)</script>\nא\n:::');
  const label = view.querySelector('.sticky-md-alert-label');
  eq(label.textContent, '<script>alert(1)</script>', 'הוצג כטקסט');
  eq(label.innerHTML, '', 'ולא נכתב כ-HTML');
});

check('אלרט: מפתח מהפרוטוטיפ אינו סוג', () => {
  // ``titles[type]`` לבדו היה מחזיר פונקציה עבור ``constructor`` ומקבל
  // אותה כסוג תקף. שם הסוג מגיע מטקסט שהמשתמש הקליד — קלט חיצוני לכל דבר.
  eq(alerts(renderMd(mdMgr, '::: constructor\nא\n:::').view).length, 0, 'constructor');
  eq(alerts(renderMd(mdMgr, '::: toString\nא\n:::').view).length, 0, 'toString');
});

check('אלרט: בלי שורת סגירה — נמשך עד סוף הפתק', () => {
  // נמדד: ``markdown-it-container`` סוגר מכולה פתוחה בסוף המסמך.
  const { view } = renderMd(mdMgr, '::: tip\nא\nב');
  const box = view.querySelector('.admonition');
  eq(!!box, true, 'נבנה אלרט');
  const inner = box.querySelector('.admonition-content');
  eq(inner.querySelectorAll('.sticky-task-line').length, 2, 'שתי שורות התוכן בפנים');
});

check('אלרט: שורת סגירה קצרה מהפתיחה אינה סוגרת', () => {
  // נמדד: ``:::: note`` שנסגר ב-``:::`` — ה-``:::`` נשאר תוכן, והמכולה
  // נסגרת רק בסוף. הכלל בתוסף: ``marker_count`` של הסגירה ≥ של הפתיחה.
  const { view } = renderMd(mdMgr, ':::: note\nא\n:::\nב');
  eq(alerts(view).length, 1, 'אלרט אחד');
  const inner = view.querySelector('.admonition-content');
  eq(inner.textContent.includes(':::'), true, 'ה-::: הקצר נשאר תוכן');
  eq(inner.textContent.includes('ב'), true, 'וגם מה שאחריו נשאר בפנים');
});

check('אלרט: ::: x אינו סוגר — אחרי הנקודתיים מותרים רווחים בלבד', () => {
  const { view } = renderMd(mdMgr, '::: note\nא\n::: x\nב');
  eq(alerts(view).length, 1);
  eq(view.querySelector('.admonition-content').textContent.includes('::: x'), true, 'נשאר תוכן');
});

check('אלרט: קינון — הסגירה סוגרת את החיצוני ביותר שאורכו מתאים', () => {
  // **זו ההתנהגות שהכי קל לטעות בה.** האינטואיציה אומרת "סוגר את
  // הפנימי"; בפועל ב-markdown-it כל מכולה סורקת קדימה אחר סגירה משלה,
  // והפנימיות נסגרות בסוף ההורה. נמדד על שלוש רמות, בשני סדרי סגירה.
  const { view } = renderMd(mdMgr, '::::: note\nא\n:::: tip\nב\n::: info\nג\n::::\nד\n:::::\nה');
  const found = alerts(view);
  eq(found.map((a) => a.type).join(','), 'note,tip,info', 'שלוש רמות, מבחוץ פנימה');
  // ``::::`` סוגר את info ואת tip ומשאיר את note פתוח, ולכן ``ד`` בתוך note
  const note = view.querySelector('.admonition');
  const noteBody = note.querySelector('.admonition-content');
  eq(noteBody.textContent.includes('ד'), true, 'ד נשאר בתוך note');
  // ``:::::`` סוגר את note, ולכן ``ה`` כבר מחוץ לכל אלרט
  const top = view.children[view.children.length - 1];
  eq(top.textContent, 'ה', 'ה הוא שורה עליונה, מחוץ לאלרט');
});

check('אלרט: התוכן עובר את מנוע המארקדאון המלא', () => {
  const { view } = renderMd(mdMgr, '::: info\n**מודגש** `קוד`\n# כותרת\n| א | ב |\n|---|---|\n| 1 | 2 |\n:::');
  const body = view.querySelector('.admonition-content');
  eq(!!body.querySelector('strong.sticky-md-bold'), true, 'מודגש');
  eq(!!body.querySelector('code.sticky-md-code'), true, 'קוד בשורה');
  eq(!!body.querySelector('.sticky-md-h1'), true, 'כותרת');
  eq(!!body.querySelector('table'), true, 'טבלה — ונבנתה בתוך האלרט ולא לצידו');
});

check('אלרט: charOffset — הכותרת יושבת על שורת הפתיחה', () => {
  const content = '::: note\nגוף\n:::';
  const { el, ta, view } = renderMd(mdMgr, content);
  const title = view.querySelector('.admonition-title');
  eq(title.dataset.charOffset, '0', 'ההיסט של ``::: note``');
  // ההיסט לבדו אינו מספיק — ``_enterEditFromView`` חייב באמת למצוא אותו
  // דרך ``closest('.sticky-task-line')``, ולכן הכותרת נושאת את המחלקה.
  const label = title.querySelector('.sticky-md-alert-label');
  mdMgr._enterEditFromView(el, { target: label });
  eq(ta.selectionStart, 0, 'לחיצה על הכותרת מחזירה לעריכה בשורת הפתיחה');
});

check('אלרט: charOffset — שורת הסגירה נצרכת אבל מקדמת את ההיסט', () => {
  // **הבדיקה שמגינה על החשבון המצטבר.** שורת ``:::`` אינה מייצרת אלמנט
  // (אין לה מה להציג), בדיוק כמו שורת המפריד של טבלה — אבל בלי קידום
  // ההיסט עליה, כל מה שאחרי האלרט מוסט באורך שורה שלמה ולחיצה נוחתת
  // בשורה הלא נכונה.
  const content = '::: note\nגוף\n:::\nאחרי האלרט';
  const { el, ta, view } = renderMd(mdMgr, content);
  const rows = view.querySelectorAll('.sticky-task-line');
  const last = rows[rows.length - 1];
  eq(last.textContent, 'אחרי האלרט', 'זו אכן השורה שאחרי');
  eq(Number(last.dataset.charOffset), content.indexOf('אחרי האלרט'), 'ההיסט מצביע לתחילתה');
  mdMgr._enterEditFromView(el, { target: last });
  eq(ta.selectionStart, content.indexOf('אחרי האלרט'), 'והלחיצה נוחתת שם');
});

check('אלרט: אינדקס המשימות אינו זז בגלל האלרט', () => {
  // **החמור מכולם, כי הוא נשלח לשרת.** ``sticky_notes_tasks`` בשרת סופר
  // כל שורת ``- [ ]`` בתוכן — הוא אינו מפרש אלרטים כלל — ולכן הסידור
  // בלקוח חייב להתקדם בדיוק כמוהו. אינדקס שזז מסמן משימה אחרת מזו
  // שנלחצה. שורות המרקר עצמן לעולם אינן שורות משימה: הן מתחילות
  // בנקודתיים, ו-``TASK_LINE_RE`` דורש ``-`` או ``*``.
  const { view } = renderMd(mdMgr, '- [ ] לפני\n::: todo\n- [ ] בתוך\n:::\n- [x] אחרי');
  const boxes = view.querySelectorAll('.sticky-task-box');
  eq(boxes.length, 3, 'שלוש תיבות');
  eq(boxes.map((b) => b.dataset.taskIndex).join(','), '0,1,2', 'סידור רציף');
  eq(boxes[2].checked, true, 'והמצב נקרא נכון');
});

check('אלרט: לחיצה על שורה בתוך אלרט מחזירה לעריכה באותה שורה', () => {
  const content = '::: note\nשורה ראשונה\nשורה שנייה\n:::';
  const { el, ta, view } = renderMd(mdMgr, content);
  const rows = view.querySelector('.admonition-content').querySelectorAll('.sticky-task-line');
  mdMgr._enterEditFromView(el, { target: rows[1] });
  eq(ta.selectionStart, content.indexOf('שורה שנייה'), 'הסמן בתחילת השורה שנלחצה');
});

check('אלרט: ::: בתוך גדר קוד נשאר ליטרלי — סטייה מתועדת', () => {
  // **סטייה מכוונת מ-markdown-it, ונמדדה שם.** הסורק של המכולה קורא
  // שורות גולמיות ואינו מודע לגדרות, ולכן אצלו ה-``:::`` שבתוך הגדר סוגר
  // את הבלוק ושובר את הגדר לשניים. בפתק זו תוצאה גרועה למשתמש, וזו גם
  // אותה עמדה שהפתק כבר נוקט בטבלה שבתוך גדר.
  const { view } = renderMd(mdMgr, '::: note\n```\n:::\n```\nאחרי\n:::');
  const found = alerts(view);
  eq(found.length, 1, 'אלרט אחד');
  const body = view.querySelector('.admonition-content');
  // הגדר נצרכת שלמה ונסגרת בגדר השנייה, ולכן יש בה **שורת תוכן אחת**
  // — ה-``:::`` — ושתי שורות הגדר עצמן אינן מוצגות. ``אחרי`` כבר מחוץ
  // לגדר ובתוך האלרט, כשורת טקסט רגילה.
  eq(body.querySelectorAll('.sticky-md-pre').length, 1, 'שורת תוכן אחת בגדר');
  eq(body.querySelector('.sticky-md-pre').textContent, ':::', 'וה-::: נשאר קוד ליטרלי ולא סגר את האלרט');
  eq(body.textContent.includes('אחרי'), true, 'ומה שאחרי הגדר עדיין בתוך האלרט');
});

check('אלרט: פתיחה בתוך גדר אינה פותחת אלרט', () => {
  const { view } = renderMd(mdMgr, '```\n::: note\n```');
  eq(alerts(view).length, 0, 'אין אלרט');
  eq(view.querySelectorAll('.sticky-md-pre').length, 1, 'שורת תוכן אחת');
  eq(view.querySelector('.sticky-md-pre').textContent, '::: note', 'והיא ליטרלית');
});

check('אלרט לבדו פותח את התצוגה', () => {
  // בלי זיהוי אלרט ב-``_hasRenderableMarkdown``, פתק שכולו ``::: note``
  // לא היה עובר את השער והתצוגה כלל לא הייתה נפתחת — כשל שקט, בדיוק
  // כמו שקרה פעם עם טבלה.
  eq(mdMgr._hasRenderableMarkdown('::: note\nגוף\n:::'.split('\n')), true);
  eq(mdMgr._hasRenderableMarkdown('::: foo\nגוף\n:::'.split('\n')), false, 'וסוג לא מוכר אינו פותח');
});

check('אלרט: מארקדאון כבוי מציג טקסט גולמי', () => {
  const off = new StickyNotesManager({ board: 'b-alert-off', markdown: false });
  const parts = makeNote('::: note\n- [ ] משימה\n:::');
  off._syncTaskView(parts.el);
  eq(alerts(parts.view).length, 0, 'אין אלרט');
  eq(parts.view.textContent.includes('::: note'), true, 'המרקר מוצג כפי שהוקלד');
  // צ'קבוקסים עובדים תמיד, בלי תלות בהגדרת המארקדאון
  eq(parts.view.querySelectorAll('.sticky-task-box').length, 1, 'והצ׳קבוקס עדיין אינטראקטיבי');
});

check('אלרט: בעמודה 0 סוגר רשימה, ומוזח לתוך פריט נשאר בתוכו', () => {
  // האלרט הוא בלוק ככל בלוק אחר, ולכן הוא עובר דרך ``_closeListsAbove``
  // עם ההזחה של עצמו — אותו כלל אחיד שכבר חל על כותרת, ציטוט וטבלה.
  //
  // **הפריט המוזח שאחרי האלרט הוא מה שמוכיח את זה, ולא הפריט שבעמודה 0.**
  // פריט בעמודה 0 סוגר את הרשימה בעצמו לפי הכלל האחיד, ולכן הוא היה יוצא
  // בעומק 0 גם אם שורת האלרט לא הייתה נוגעת במחסנית — בדיקה שעוברת בלי
  // הקוד שהיא אמורה לכסות. נתפס במוטציה.
  const closes = renderMd(mdMgr, '- פריט\n::: note\n  - בן\n:::');
  const inner = closes.view.querySelector('.admonition-content')
    .querySelectorAll('.sticky-task-line');
  eq(inner.length, 1, 'שורה אחת בתוך האלרט');
  eq(inner[0].classList.contains('is-depth-1'), false,
     'האלרט בעמודה 0 סגר את הפריט שמעליו, ולכן הפריט שבתוכו מתחיל מרמה 0');
  const stays = renderMd(mdMgr, '- פריט\n  ::: note\n  א\n  :::\n  - בן');
  const rows = stays.view.querySelectorAll('.sticky-task-line');
  const last = rows[rows.length - 1];
  // ``textContent`` של שורת רשימה כולל את התבליט, ולכן ``includes``
  // ולא שוויון — אותה סיבה שבגללה שאר בדיקות הקינון משתמשות ב-``depths``.
  eq(last.textContent.includes('בן'), true, 'השורה האחרונה');
  eq(last.classList.contains('is-depth-1'), true, 'ונשארה בתוך הפריט');
});

check('אלרט: רשימה שנפתחה בפנים אינה דולפת החוצה', () => {
  // **הבאג שהריוויו תפס, ושכל 176 הבדיקות שלפניו לא ראו.** ``- ב`` נפתח
  // בתוך האלרט, ו-``- ג`` שאחריו מוזח מספיק כדי "להגיע" לעמודת התוכן
  // שלו — ולכן בלי סגירת המחסנית בגבול הוא יצא בעומק 1, כבן של פריט
  // שכבר אינו קיים. נמדד מול ``markdown-it``: שם התשובה היא 0.
  const { view } = renderMd(mdMgr, '::: note\n- א\n  - ב\n:::\n  - ג');
  const rows = view.querySelectorAll('.sticky-task-line');
  const last = rows[rows.length - 1];
  eq(last.textContent.includes('ג'), true, 'זו אכן השורה האחרונה');
  eq(last.classList.contains('is-depth-1'), false, 'ולא ירשה את העומק מתוך האלרט');
});

check('אלרט: הדליפה נחסמת גם בשורת צ׳קבוקס', () => {
  // אותו שורש, ומסלול תצוגה אחר: המחלקה יושבת על ``.sticky-task-line``,
  // המשותף לשורת רשימה ולשורת משימה. בלי בדיקה נפרדת, ענף שיטפל רק
  // באחת מהן היה עובר.
  const { view } = renderMd(mdMgr, '::: todo\n- [ ] א\n  - [ ] ב\n:::\n  - [ ] ג');
  const rows = view.querySelectorAll('.sticky-task-line');
  const last = rows[rows.length - 1];
  eq(last.classList.contains('sticky-task'), true, 'השורה האחרונה היא משימה');
  eq(last.classList.contains('is-depth-1'), false, 'ובעומק 0');
});

check('אלרט: הסגירה סוגרת לפי ההזחה של עצמה, ומשמרת רשימה חיצונית', () => {
  // **הצד השני של אותו כלל, והוא מה שמבדיל אותו מ"אפס את המחסנית".**
  // האלרט מוזח לתוך ``- חיצוני``, ולכן שורת הסגירה המוזחת סוגרת את מה
  // שנפתח בפנים אבל **אינה** נוגעת בפריט שמעליה — ו-``- אחרי`` נשאר בנו.
  const { view } = renderMd(mdMgr, '- חיצוני\n  ::: note\n  - פנימי\n  :::\n  - אחרי');
  const rows = view.querySelectorAll('.sticky-task-line');
  const last = rows[rows.length - 1];
  eq(last.textContent.includes('אחרי'), true, 'זו השורה האחרונה');
  eq(last.classList.contains('is-depth-1'), true, 'והיא עדיין בתוך הפריט החיצוני');
});

check('אלרט: סגירה מוזחת החוצה סוגרת גם את הפריט שהאלרט ישב בו', () => {
  // ההזחה של שורת הסגירה היא הקובעת, ולא עומק שנשמר בשורת הפתיחה.
  // זה בדיוק המקרה שבו שמירה-ושחזור נותנת תשובה אחרת — ושגויה: נמדד
  // מול ``markdown-it``, ושם ``- אחרי`` יוצא בעומק 0.
  const { view } = renderMd(mdMgr, '- חיצוני\n  ::: note\n  - פנימי\n:::\n  - אחרי');
  const rows = view.querySelectorAll('.sticky-task-line');
  const last = rows[rows.length - 1];
  eq(last.textContent.includes('אחרי'), true, 'זו השורה האחרונה');
  eq(last.classList.contains('is-depth-1'), false, 'והרשימה החיצונית נסגרה איתה');
});

check('אלרט: ה-CSS מכייל לפתק ואינו מגדיר פלטה שנייה', () => {
  // **שומר טקסטואלי.** הצבעים מגיעים מ-``markdown-enhanced.css`` שנטען
  // ב-``base.html``, ולכן אלרט בפתק נראה בדיוק כמו אלרט בתצוגת המסמך —
  // אותו קוד, לא העתק. ההגדרה של ``--admonition``/``border-color`` בקובץ
  // הפתקים הייתה פלטה שנייה שנסחפת מהראשונה.
  const css = fs.readFileSync(
    path.join(__dirname, '..', 'webapp', 'static', 'css', 'sticky-notes.css'), 'utf8');
  eq(/\.sticky-note \.admonition\s*\{/.test(css), true, 'יש כלל כיול לפתק');
  // ``markdown-enhanced.css`` מותח את האלרט אל מחוץ לשוליים במסכים צרים
  // (``margin: 0.75rem -0.5rem``). בעמוד זה נכון; בפתק זה מוציא אותו אל
  // מחוץ לגבול. הביטול חייב להיות בכלל שגובר בספציפיות, בלי ``!important``.
  //
  // **שתי תכונות לוגיות ולא קיצור, וזו לא קוסמטיקה.** מדידה בכרומיום
  // הראתה שקיצור ``margin: .35em 0`` הופך את ``margin-inline`` לשורה
  // מתה — כלומר לשורה שאף מוטציה אינה יכולה להפיל. בפיצול היא נושאת
  // משקל: בלעדיה הצדדים נופלים ל-``-8px`` והאלרט חוצה את גבול הפתק.
  // **ההערות מוסרות לפני הבדיקה.** בלי זה השומר קורא את הפרוזה שבתוך
  // הכלל — שמזכירה את שמות התכונות כדי להסביר אותן — ועובר גם כשההצהרה
  // עצמה נמחקה. נתפס במוטציה: הסרת ``margin-inline: 0`` לא הפילה כלום,
  // כי המילים ``margin-inline: 0`` הופיעו בהערה שמעליה.
  const decls = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const calib = decls.slice(decls.indexOf('.sticky-note .admonition {'));
  const body = calib.slice(0, calib.indexOf('}'));
  eq(/margin-inline\s*:\s*0/.test(body), true, 'כלל המובייל מבוטל בציר האופקי');
  eq(/margin-block\s*:/.test(body), true, 'והציר האנכי נקבע בנפרד');
  eq(/^\s*margin\s*:/m.test(body), false, 'בלי קיצור margin — הוא היה מייתר את margin-inline');
  // אין הגדרות צבע משלנו לסוגים — אלה חיים במקום אחד בלבד
  eq(/\.admonition-(note|tip|danger|warning|success)\s*\{/.test(decls), false, 'אין פלטת סוגים שנייה');
});

// ---------- ``::: details`` — הבלוק המתקפל ----------
//
// גם כאן התחביר אינו שלנו, ו**כל הציפיות למטה נמדדו מול
// ``markdown-it-container@4.0.0``** עם אותה רישום מכולות שתצוגת המסמך
// מריצה — לא נזכרו. ההבדל היחיד מסוגי המכולה האחרים הוא האלמנט: ``details``
// ו-``summary`` נייטיביים במקום ``div`` עם מחלקה.

/** הבלוקים המתקפלים בתצוגה, לפי סדר הופעה. */
function detailsBoxes(view){
  return view.querySelectorAll('details.sticky-md-details');
}
/** ה-``summary`` של בלוק מתקפל. */
function summaryOf(box){
  return box.querySelector('summary.sticky-md-details-summary');
}

check('details: ``::: details`` בונה <details>/<summary> נייטיביים', () => {
  const { view } = renderMd(mdMgr, '::: details\nגוף\n:::');
  const boxes = detailsBoxes(view);
  eq(boxes.length, 1, 'בלוק מתקפל אחד');
  // **האלמנט הוא כל העניין.** ``div`` עם JS שמראה ומסתיר היה מכונת מצב
  // שנייה לצד הקיפול של הפתק עצמו, ובלי מקלדת, נגישות והדפסה.
  eq(String(boxes[0].tagName).toLowerCase(), 'details', 'אלמנט details ולא div');
  const summary = summaryOf(boxes[0]);
  eq(!!summary, true, 'יש summary');
  eq(String(summary.tagName).toLowerCase(), 'summary', 'והוא summary אמיתי');
  eq(boxes[0].open, undefined, 'ומתחיל סגור, כמו בתצוגת המסמך');
  // אינו אלרט: אין מחלקת ``admonition``, ולכן גם אין אייקון ואין צבע סוג.
  eq(alerts(view).length, 0, 'אינו נספר כאלרט');
  eq(!!view.querySelector('.sticky-md-alert-icon'), false, 'ואין לו אייקון');
});

check('details: תווית ברירת המחדל מגיעה מהמקור המשותף', () => {
  // **לא מחרוזת חדשה.** אותה תווית שתצוגת המסמך והתצוגה החיה כבר
  // משתמשות בה, ומאותו קובץ — ``admonition-icons.js``. הבדיקה קוראת את
  // הגלובל ולא מקלידה את הטקסט, אחרת היא הייתה עותק רביעי.
  const shared = sandbox.window.DETAILS_DEFAULT_TITLE;
  eq(typeof shared === 'string' && shared.length > 0, true, 'הקבוע המשותף קיים');
  const { view } = renderMd(mdMgr, '::: details\nגוף\n:::');
  eq(summaryOf(detailsBoxes(view)[0]).textContent, shared, 'והוא מה שמוצג');
  const custom = renderMd(mdMgr, '::: details מה יש בפנים\nגוף\n:::');
  eq(summaryOf(detailsBoxes(custom.view)[0]).textContent, 'מה יש בפנים', 'כותרת מותאמת גוברת');
});

check('details: אינו אלרט ולכן אינו במפת הסוגים', () => {
  // **ההפרדה הזו היא מה ששומר על שתי הבדיקות שמעל.** ``ADMONITION_TITLES``
  // היא ההגדרה של "מהו סוג אלרט", ורשימת הסוגים בעמוד המשתמש נגזרת ממנה.
  // הכנסת ``details`` לשם הייתה נותנת לו אייקון (או משאירה אותו בלי, ומפילה
  // את בדיקת ההצלבה מול ``ADMONITION_ICONS``) ומוסיפה אותו לרשימה שהמשתמש
  // קורא כרשימת הכרטיסיות הצבעוניות.
  eq(Object.prototype.hasOwnProperty.call(sandbox.window.ADMONITION_TITLES, 'details'), false);
  eq(Object.prototype.hasOwnProperty.call(sandbox.window.ADMONITION_ICONS, 'details'), false);
});

check('details: לבדו פותח את התצוגה, וסוג לא מוכר לא', () => {
  eq(mdMgr._hasRenderableMarkdown('::: details\nגוף\n:::'.split('\n')), true);
  // גבול המילה — אותו כלל בדיוק שכבר חל על ``::: note2``. נמדד מול התוסף:
  // שניהם מרונדרים שם כפסקה.
  eq(mdMgr._hasRenderableMarkdown('::: detailsX\nגוף\n:::'.split('\n')), false, 'detailsX אינו מכולה');
  eq(mdMgr._hasRenderableMarkdown('::: details2\nגוף\n:::'.split('\n')), false, 'details2 אינו מכולה');
});

check('details: ההיסטים נכונים לפני, בתוך ואחרי — גם סגור וגם פתוח', () => {
  // **הבדיקה שמסוגלת ליפול אם ההיסט יוסר יחד עם מאזין העריכה.** הקליק על
  // ה-``summary`` מקפל ואינו נכנס לעריכה, ולכן קל לחשוב שההיסט מיותר שם.
  // הוא אינו: בלעדיו כל שורה שאחרי הבלוק מוסטת באורך שורה שלמה.
  const content = 'לפני\n::: details כותרת\nבפנים\n:::\nאחרי';
  const run = (openIt) => {
    const parts = renderMd(mdMgr, content);
    if (openIt) {
      detailsBoxes(parts.view)[0].open = true;
      mdMgr._syncTaskView(parts.el);   // רינדור מחדש עם הבלוק פתוח
    }
    const box = detailsBoxes(parts.view)[0];
    eq(!!box, true, 'הבלוק קיים');
    if (openIt) eq(box.open, true, 'ונשאר פתוח');
    const at = (node) => Number(node.dataset.charOffset);
    const rows = parts.view.querySelectorAll('.sticky-task-line');
    const before = rows.find((r) => r.textContent === 'לפני');
    const inside = box.querySelector('.details-content').querySelectorAll('.sticky-task-line')[0];
    const after = rows.find((r) => r.textContent === 'אחרי');
    eq(at(before), 0, 'לפני');
    eq(at(summaryOf(box)), content.indexOf('::: details'), 'שורת הפתיחה');
    eq(inside.textContent, 'בפנים', 'השורה שבפנים');
    eq(at(inside), content.indexOf('בפנים'), 'ההיסט שלה');
    // שורת הסגירה נצרכת בלי אלמנט, וההיסט מקודם עליה — בלי זה ``אחרי``
    // היה מצביע ארבעה תווים אחורה.
    eq(at(after), content.indexOf('אחרי'), 'ואחרי הבלוק');
    mdMgr._enterEditFromView(parts.el, { target: after });
    eq(parts.ta.selectionStart, content.indexOf('אחרי'), 'והלחיצה נוחתת שם');
  };
  run(false);
  run(true);
});

check('details: אינדקס המשימות אינו זז בגלל הבלוק', () => {
  const { view } = renderMd(mdMgr, '- [ ] לפני\n::: details כותרת\n- [ ] בתוך\n:::\n- [x] אחרי');
  const boxes = view.querySelectorAll('.sticky-task-box');
  eq(boxes.length, 3, 'שלוש תיבות');
  eq(boxes.map((b) => b.dataset.taskIndex).join(','), '0,1,2', 'סידור רציף');
  eq(boxes[2].checked, true, 'והמצב נקרא נכון');
});

check('details: לחיצה על ה-summary מקפלת בלבד ואינה נכנסת לעריכה', () => {
  // **ההכרעה.** האנלוגיה היא אייקון ההעתקה בבלוק קוד — עם ההבדל שכאן
  // מוותרים על השורה כולה ולא על אזור קטן בתוכה.
  const { el, ta, view } = renderMd(mdMgr, '::: details כותרת\nבפנים\n:::');
  ta.selectionStart = -1;
  FakeEl.focused = null;
  const summary = summaryOf(detailsBoxes(view)[0]);
  eq(mdMgr._enterEditFromView(el, { target: summary }), false, 'לא נכנס לעריכה');
  eq(FakeEl.focused, null, 'וה-textarea לא קיבל focus');
  // ומה שבפנים כן מוביל לעריכה, אחרת הבלוק היה קריאה-בלבד.
  const inside = detailsBoxes(view)[0].querySelector('.details-content')
    .querySelectorAll('.sticky-task-line')[0];
  eq(mdMgr._enterEditFromView(el, { target: inside }), true, 'שורה בפנים כן');
});

check('details: Enter ו-Space על ה-summary אינם מבטלים את הקיפול הנייטיבי', () => {
  // ``preventDefault`` על ``<summary>`` **מבטל את הקיפול עצמו** — כלומר
  // משתמש מקלדת נשאר בלי שום דרך לפתוח את הבלוק. בשונה מהקישור, שם רק
  // Enter פטור ו-Space עדיין נבלם כדי לא לגלול.
  const { el, view } = renderMd(mdMgr, '::: details כותרת\nבפנים\n:::');
  const summary = summaryOf(detailsBoxes(view)[0]);
  ['Enter', ' '].forEach((key) => {
    FakeEl.focused = null;
    const ev = keyEvent(key, summary);
    mdMgr._viewKeydown(el, ev);
    eq(ev._prevented, false, key + ': לא בוטל — הדפדפן מקפל');
    eq(FakeEl.focused, null, key + ': וגם לא נכנס לעריכה');
  });
});

check('details: מצב הפתיחה שורד רינדור מחדש', () => {
  // **בלי זה סימון צ׳קבוקס שבתוך הבלוק היה סוגר אותו תחת האצבע.**
  // ``_applyServerContent`` קורא ל-``_syncTaskView`` אחרי כל toggle,
  // והתצוגה נבנית מאפס.
  const { el, view } = renderMd(mdMgr, 'לפני\n::: details כותרת\n- [ ] משימה\n:::');
  detailsBoxes(view)[0].open = true;
  mdMgr._syncTaskView(el);
  eq(detailsBoxes(view)[0].open, true, 'נשאר פתוח');
  // ובלוק שלא נפתח נשאר סגור — אחרת השחזור היה פותח הכול.
  const other = renderMd(mdMgr, '::: details כותרת\nגוף\n:::');
  mdMgr._syncTaskView(other.el);
  eq(detailsBoxes(other.view)[0].open, undefined, 'ובלוק שלא נפתח נשאר סגור');
});

// ---------- מצב הפתיחה סביב מעבר לעריכה ----------
//
// **הפתקים כאן רשומים במנהל**, ולא נבנים ב-``makeNote`` בלבד, כי הזיכרון
// חי על רשומת הפתק — אותו מקום שבו כבר חי מצב הביטול. פתק שאינו רשום
// עובד בתוך קריאה אחת אבל אינו זוכר בין קריאות, וזו בדיוק היכולת שנבדקת
// כאן. ``_renderNote`` רושם את הפתק לפני הסנכרון הראשון, ולכן זו גם
// הצורה שרצה בפרודקשן.

function renderRegistered(mgr, id, content){
  const parts = registerNote(mgr, id, content);
  mgr._syncTaskView(parts.el);
  return parts;
}
/** מצב הפתיחה של כל הבלוקים, לפי סדר הופעה. */
function openFlags(view){
  return detailsBoxes(view).map((box) => !!box.open).join(',');
}

check('details: מצב הפתיחה שורד מעבר לעריכה וחזרה', () => {
  // **הבאג שהריוויו תפס.** הלכידה ישבה **מתחת** ליציאה המוקדמת, והיציאה
  // הזו מוחקת את התצוגה בעצמה — כלומר כניסה לעריכה מחקה את המצב לפני
  // שמישהו קרא אותו, וכל בלוק חזר סגור אחרי כל עריכה.
  const parts = renderRegistered(mdMgr, 'det-edit-1', 'לפני\n::: details בלוק\nבפנים\n:::');
  detailsBoxes(parts.view)[0].open = true;
  mdMgr._syncTaskView(parts.el, { editing: true });   // מוחק את התצוגה
  mdMgr._syncTaskView(parts.el);                      // ובונה אותה מחדש
  eq(openFlags(parts.view), 'true', 'הבלוק חזר פתוח');
});

check('details: המצב שורד גם כשהעריכה הזיזה את הטקסט', () => {
  // **זו הבדיקה שמכריעה את בחירת המפתח, והיא נמדדה בכרומיום לפני שנכתבה.**
  // ההיסט של שורת הפתיחה הוא הזהות שהמנוע כבר מתחזק, והוא מדויק כל עוד
  // הטקסט לא זז — אבל עריכה **כן** מזיזה אותו. תו אחד בתחילת הפתק מזיז
  // את כל ההיסטים באחד, המטמון מחטיא, ומסלול העריכה — שהוא כל הסיבה
  // למטמון — נשאר לא מכוסה. הסידור שורד את זה.
  const parts = renderRegistered(mdMgr, 'det-edit-2', 'לפני\n::: details בלוק\nבפנים\n:::');
  detailsBoxes(parts.view)[0].open = true;
  mdMgr._syncTaskView(parts.el, { editing: true });
  parts.ta.value = 'X' + parts.ta.value;              // כל ההיסטים זזים באחד
  mdMgr._syncTaskView(parts.el);
  eq(openFlags(parts.view), 'true', 'הזהות היא הסידור ולא ההיסט');
});

check('details: רק הבלוק שנפתח נפתח, גם אחרי שהטקסט זז', () => {
  const parts = renderRegistered(mdMgr, 'det-edit-3',
    'לפני\n::: details ראשון\nא\n:::\n::: details שני\nב\n:::');
  const boxes = detailsBoxes(parts.view);
  eq(boxes.length, 2, 'שני בלוקים');
  boxes[1].open = true;
  mdMgr._syncTaskView(parts.el, { editing: true });
  parts.ta.value = 'X' + parts.ta.value;
  mdMgr._syncTaskView(parts.el);
  eq(openFlags(parts.view), 'false,true', 'השני, ורק הוא');
});

check('details: הסידור נשמר גם בקינון', () => {
  // ``querySelectorAll`` מחזיר סדר מסמך, והבנייה מוסיפה בלוק מקונן לתוך
  // גוף ההורה שכבר נוסף — ולכן שני הצדדים סופרים באותו סדר. בלי זה
  // הבלוק הפנימי היה מקבל מספר אחד בלכידה ומספר אחר בבנייה.
  const parts = renderRegistered(mdMgr, 'det-edit-5',
    'לפני\n:::: details חיצוני\n::: details פנימי\nב\n:::\n::::');
  const boxes = detailsBoxes(parts.view);
  eq(boxes.length, 2, 'חיצוני ואז פנימי');
  eq(summaryOf(boxes[0]).textContent, 'חיצוני', 'וזה אכן הסדר');
  boxes[1].open = true;
  mdMgr._syncTaskView(parts.el, { editing: true });
  parts.ta.value = 'X' + parts.ta.value;
  mdMgr._syncTaskView(parts.el);
  eq(openFlags(parts.view), 'false,true', 'רק הפנימי');
});

check('details: פתק שאיבד את כל המבנה מנקה את הזיכרון', () => {
  // **מצב רפאים שנתפס במדידה, לא בקריאה.** היציאה המוקדמת משרתת שני
  // מצבים שנראים זהים: "המשתמש עורך עכשיו" — ושם הזיכרון הוא כל העניין —
  // ו"לפתק אין מבנה בכלל", שבו אין בלוקים ולכן אין מה לזכור. בלי ההבחנה,
  // בלוק חדש לגמרי נולד פתוח כי ירש את המספר של בלוק שנמחק.
  const parts = renderRegistered(mdMgr, 'det-edit-4', '::: details ישן\nגוף\n:::');
  detailsBoxes(parts.view)[0].open = true;
  parts.ta.value = 'רק טקסט, בלי מבנה';
  mdMgr._syncTaskView(parts.el);                      // יציאה מוקדמת, לא עריכה
  eq(detailsBoxes(parts.view).length, 0, 'אין בלוקים');
  parts.ta.value = '::: details חדש\nגוף\n:::';
  mdMgr._syncTaskView(parts.el);
  eq(openFlags(parts.view), 'false', 'הבלוק החדש נולד סגור');
});

check('details: המצב אינו זולג בין פתקים', () => {
  // הזיכרון חי על רשומת הפתק, ולכן פתק שני על אותו מנהל אינו יורש אותו.
  const a = renderRegistered(mdMgr, 'det-edit-6a', '::: details א\nגוף\n:::');
  detailsBoxes(a.view)[0].open = true;
  mdMgr._syncTaskView(a.el, { editing: true });
  mdMgr._syncTaskView(a.el);
  const bNote = renderRegistered(mdMgr, 'det-edit-6b', '::: details ב\nגוף\n:::');
  eq(openFlags(a.view), 'true', 'הראשון פתוח');
  eq(openFlags(bNote.view), 'false', 'והשני סגור');
});

check('details: מארקדאון כבוי מציג טקסט גולמי', () => {
  const off = new StickyNotesManager({ board: 'b-details-off', markdown: false });
  const parts = makeNote('::: details כותרת\n- [ ] משימה\n:::');
  off._syncTaskView(parts.el);
  eq(detailsBoxes(parts.view).length, 0, 'אין בלוק מתקפל');
  eq(parts.view.textContent.includes('::: details כותרת'), true, 'המרקר מוצג כפי שהוקלד');
  eq(parts.view.querySelectorAll('.sticky-task-box').length, 1, 'והצ׳קבוקס עדיין אינטראקטיבי');
});

// ---------- קינון: ``details`` והאלרט באותה מחסנית ----------
//
// ``_closeContainersAt`` אינה יודעת דבר על הסוג, והציפיות כאן נמדדו מול
// ``markdown-it-container`` על ארבעת הצירופים.

check('קינון: details בתוך אלרט', () => {
  const { view } = renderMd(mdMgr, ':::: note\n::: details כותרת\nפנים\n:::\nאחרי\n::::');
  const alertBody = view.querySelector('.admonition-content');
  eq(!!alertBody, true, 'יש אלרט');
  eq(detailsBoxes(alertBody).length, 1, 'והבלוק המתקפל בתוכו');
  const rows = alertBody.querySelectorAll('.sticky-task-line');
  const after = rows.find((r) => r.textContent === 'אחרי');
  eq(!!after, true, '``אחרי`` נשאר בתוך האלרט');
  eq(!!detailsBoxes(view)[0].querySelector('.details-content')
      .querySelectorAll('.sticky-task-line').find((r) => r.textContent === 'אחרי'), false,
     'ולא נשאר בתוך הבלוק המתקפל');
});

check('קינון: אלרט בתוך details', () => {
  const { view } = renderMd(mdMgr, ':::: details חיצוני\n::: note\nפנים\n:::\nאחרי\n::::');
  const boxes = detailsBoxes(view);
  eq(boxes.length, 1, 'בלוק מתקפל אחד');
  const body = boxes[0].querySelector('.details-content');
  eq(alerts(body).length, 1, 'והאלרט בתוכו');
  eq(!!body.querySelectorAll('.sticky-task-line').find((r) => r.textContent === 'אחרי'), true,
     '``אחרי`` נשאר בתוך הבלוק המתקפל');
});

check('קינון: שורת סגירה סוגרת את החיצוני ביותר, גם כששני הסוגים מעורבים', () => {
  // **הכלל שהכי קל לטעות בו.** האינטואיציה אומרת "סוגר את הפנימי"; נמדד
  // מול התוסף — ``:::`` סוגר גם את ``note`` וגם את ``details`` שבתוכו,
  // ו-``אחרי`` יוצא מחוץ לשניהם.
  const { view } = renderMd(mdMgr, '::: note\n::: details\nפנים\n:::\nאחרי');
  const after = view.querySelectorAll('.sticky-task-line').find((r) => r.textContent === 'אחרי');
  eq(!!after, true, 'השורה קיימת');
  eq(after.closest('.admonition-content'), null, 'ואינה בתוך האלרט');
  eq(after.closest('.details-content'), null, 'ואינה בתוך הבלוק המתקפל');
});

check('קינון: שני בלוקים מתקפלים, סגירה אחת ארוכה סוגרת את שניהם', () => {
  const { view } = renderMd(mdMgr, ':::: details א\n::: details ב\nפנים\n::::\nאחרי');
  eq(detailsBoxes(view).length, 2, 'שני בלוקים');
  const after = view.querySelectorAll('.sticky-task-line').find((r) => r.textContent === 'אחרי');
  eq(after.closest('.details-content'), null, '``אחרי`` מחוץ לשניהם');
});

check('details: רשימה שנפתחה בפנים אינה דולפת החוצה', () => {
  // אותו גבול בדיוק שכבר נבדק לאלרט — וכאן הוא מוודא שהסוג החדש עובר
  // באותו מסלול ולא בענף משלו.
  const { view } = renderMd(mdMgr, '::: details כותרת\n- א\n  - ב\n:::\n  - ג');
  const rows = view.querySelectorAll('.sticky-task-line');
  const last = rows[rows.length - 1];
  eq(last.textContent.includes('ג'), true, 'זו אכן השורה האחרונה');
  eq(last.classList.contains('is-depth-1'), false, 'ולא ירשה את העומק מתוך הבלוק');
});

check('details: ``:::`` בתוך גדר קוד נשאר ליטרלי', () => {
  const { view } = renderMd(mdMgr, '::: details כותרת\n```\n:::\n```\nאחרי\n:::');
  const boxes = detailsBoxes(view);
  eq(boxes.length, 1, 'בלוק אחד');
  const body = boxes[0].querySelector('.details-content');
  eq(body.querySelectorAll('.sticky-md-pre').length, 1, 'שורת תוכן אחת בגדר');
  eq(body.querySelector('.sticky-md-pre').textContent, ':::', 'וה-::: נשאר קוד ליטרלי');
  eq(body.textContent.includes('אחרי'), true, 'ומה שאחרי הגדר עדיין בתוך הבלוק');
});

check('details: ה-CSS מכייל את המידות לפתק', () => {
  // **אותה מלכודת בדיוק של האלרט, ואותו כלל מובייל תופס את שתי המחלקות
  // יחד:** ``.markdown-details, .admonition { margin: 0.75rem -0.5rem; }``.
  // הפיצול ל-``margin-block``/``margin-inline`` הוא מה שהופך את הביטול
  // לשורה שאפשר להפיל — נמדד בכרומיום, פתק ברוחב 260 באזור תצוגה 390.
  const css = fs.readFileSync(
    path.join(__dirname, '..', 'webapp', 'static', 'css', 'sticky-notes.css'), 'utf8');
  const decls = css.replace(/\/\*[\s\S]*?\*\//g, '');   // בלי הערות — הן מזכירות את שמות התכונות
  eq(/\.sticky-note \.markdown-details\s*\{/.test(decls), true, 'יש כלל כיול לפתק');
  const calib = decls.slice(decls.indexOf('.sticky-note .markdown-details {'));
  const body = calib.slice(0, calib.indexOf('}'));
  eq(/margin-inline\s*:\s*0/.test(body), true, 'כלל המובייל מבוטל בציר האופקי');
  eq(/margin-block\s*:/.test(body), true, 'והציר האנכי נקבע בנפרד');
  eq(/^\s*margin\s*:/m.test(body), false, 'בלי קיצור margin — הוא היה מייתר את margin-inline');
  // **ואין כאן שומר על שבירת כותרת ארוכה, בכוונה.** ההיקש מהאלרט אמר
  // להצהיר ``overflow-wrap`` על ה-``summary``; מדידה בכרומיום הראתה
  // שההצהרה חסרת השפעה, כי ``.sticky-note-tasks`` כבר מצהיר אותה
  // וההצהרה יורשת — 140 תווים רצופים יצאו באותו גובה בדיוק עם השורה
  // ובלעדיה. שומר על שורה מתה שומר על כלום, ולכן השורה ירדה ואיתה
  // הטענה. הנימוק המלא בהערה שב-CSS.
  const sumCalib = decls.slice(decls.indexOf('.sticky-note .markdown-summary {'));
  const sumBody = sumCalib.slice(0, sumCalib.indexOf('}'));
  eq(/overflow-wrap|min-width/.test(sumBody), false, 'בלי הצהרות שהמדידה הראתה שאין להן השפעה');
});

check('details: הפתק מספק ערך לכל טוקן שהרכיב המשותף קורא', () => {
  // **הבדיקה הזו החליפה בדיקה שאכפה את ההפך.** הגרסה הקודמת דרשה
  // ש-``--details-bg``/``--details-border`` **לא** יופיעו ב-``sticky-notes.css``,
  // בנימוק "הצבעים חיים ב-markdown-enhanced.css בלבד". הנימוק נכון לתצוגת
  // המסמך ושגוי לפתק: הפתק הוא נייר בהיר קשיח שאינו עוקב אחרי הערכה, ולכן
  // רכיב שמוצג בתוכו וקורא טוקן ערכה מקבל ערך שנבחר לרקע אחר לגמרי —
  // בערכה כהה, קופסה שחורה על צהוב. הבדיקה הישנה הפכה את הטעות לאכיפה.
  //
  // **הצורה החדשה נגזרת מהרכיב ולא מרשימה מוקלדת.** היא סורקת את הכללים
  // ב-``markdown-enhanced.css`` ומחלצת מהם את הטוקנים בפועל, ולכן טוקן
  // שביעי שיתווסף שם — ע"י מי שאינו חושב על הפתקים בכלל — מפיל אותה
  // ומכריח החלטה, במקום להגיע לפרודקשן בשקט.
  const root = path.join(__dirname, '..');
  const strip = (t) => t.replace(/\/\*[\s\S]*?\*\//g, '');
  const shared = strip(fs.readFileSync(
    path.join(root, 'webapp', 'static', 'css', 'markdown-enhanced.css'), 'utf8'));
  const sticky = strip(fs.readFileSync(
    path.join(root, 'webapp', 'static', 'css', 'sticky-notes.css'), 'utf8'));

  // הכללים של הבלוק המתקפל, לפי הבורר המדויק שלהם. ``::-webkit-details-marker``
  // מוחרג כי הוא ``display`` בלבד ואינו נושא צבע.
  const SELECTORS = [
    '.markdown-details',
    '.markdown-details[open]',
    '.markdown-summary',
    '.markdown-summary:hover',
    '.markdown-summary::before',
    '.markdown-details[open] .markdown-summary::before',
    '.details-content',
  ];
  // טוקנים שאינם צבע ולכן אינם צריכים ערך מהפתק. **רשימה מפורשת ולא
  // היוריסטיקה**, כדי שהוספת טוקן חדש תיפול כברירת מחדל ותדרוש הכרעה.
  const NOT_A_COLOUR = new Set(['--animation-speed']);

  const used = new Set();
  SELECTORS.forEach((sel) => {
    // הבורר המדויק, בתחילת כלל: או בתחילת הקובץ או אחרי ``}``/``{``/שורה.
    const rx = new RegExp('(^|[}\\n])\\s*' + sel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\s*\\{([^}]*)\\}');
    const m = rx.exec(shared);
    eq(!!m, true, 'נמצא הכלל ' + sel + ' ב-markdown-enhanced.css');
    (m[2].match(/var\(\s*(--[a-z0-9-]+)/gi) || [])
      .forEach((hit) => used.add(hit.replace(/^var\(\s*/i, '')));
  });
  // בקרת שפיות: אם החילוץ מחזיר קבוצה ריקה, כל הבדיקה עוברת מהסיבה הלא
  // נכונה. נמדד שהרכיב קורא שישה טוקני צבע ואחד שאינו צבע.
  eq(used.size >= 7, true, 'חולצו הטוקנים בפועל (' + [...used].sort().join(', ') + ')');

  const supplied = new Set(
    (sticky.match(/--[a-z0-9-]+\s*:/gi) || []).map((d) => d.replace(/\s*:$/, '')));
  const missing = [...used].filter((t) => !NOT_A_COLOUR.has(t) && !supplied.has(t));
  eq(missing.join(','), '', 'הפתק מספק ערך לכל טוקן צבע שהרכיב קורא');

  // וההצהרות יושבות על ``.sticky-note`` עצמו — לא על צאצא — אחרת הן אינן
  // נורשות לכל תת-העץ, והבלוק המקונן שבתוך אלרט היה נשאר בצבע ערכה.
  //
  // **בלי מפצל כללים מתוצרת בית.** הגרסה הראשונה פיצלה את הקובץ
  // ב-``/(?=[.#:@][^{]*\{)/`` כדי לתפוס תחילות כללים — וה-``:`` שבמחלקת
  // התווים תפס גם את הנקודתיים של ההצהרה עצמה, כך שכל כלל נחתך בדיוק
  // לפני הערך. הבדיקה נפלה עם קבוצה ריקה, כלומר מהסיבה הלא נכונה.
  // הצורה כאן מחפשת את הבורר המדויק ולוקחת עד ה-``}`` הבא, כמו שאר
  // השומרים בקובץ. היא אינה תופסת ``.sticky-note .markdown-details`` כי
  // שם אחרי השם בא רווח ומחלקה ולא ``{``.
  const onNote = new Set();
  const noteRuleRe = /\.sticky-note\s*\{/g;
  let hit;
  while ((hit = noteRuleRe.exec(sticky)) !== null) {
    const body = sticky.slice(hit.index + hit[0].length);
    (body.slice(0, body.indexOf('}')).match(/--[a-z0-9-]+\s*:/gi) || [])
      .forEach((d) => onNote.add(d.replace(/\s*:$/, '')));
  }
  eq(onNote.size >= 6, true, 'בקרה: נקראו הצהרות מכללי .sticky-note (' + onNote.size + ')');
  const notOnNote = [...used].filter((t) => !NOT_A_COLOUR.has(t) && !onNote.has(t));
  eq(notOnNote.join(','), '', 'וכולן מוצהרות על .sticky-note עצמו');

  // **``--summary-bg`` שטוח ולא גרדיאנט — החלטה עיצובית שנאכפת.** בכל
  // שמונת בלוקי הערכה הוא ``linear-gradient``; בפתק הצר דהייה אופקית
  // נקראת כמריחה ולא כרצועת כותרת. מי שירצה להחזיר אותה עובר דרך כאן.
  const bgDecl = /--summary-bg\s*:\s*([^;]+);/.exec(sticky);
  eq(!!bgDecl, true, 'יש הצהרה ל---summary-bg');
  eq(/gradient/i.test(bgDecl[1]), false, 'הרקע בפתק שטוח, לא גרדיאנט');
});

check('תיעוד: עמוד המשתמש מונה בדיוק את הסוגים שקיימים במפה', () => {
  // **הרשימה בעמוד המשתמש היא היחידה שאינה נגזרת מהמפה בזמן ריצה**, כי
  // משתמש צריך לדעת מה זמין בלי לקרוא קוד. לכן היא היחידה שיכולה
  // להסתייף — סוג שנוסף למפה ולא לעמוד, או שם שנכתב שם בטעות. הבדיקה
  // הזו היא מה שהופך את הסיכון הזה לכשל רועש.
  const doc = fs.readFileSync(
    path.join(__dirname, '..', 'docs', 'user', 'sticky_notes.rst'), 'utf8');
  const line = doc.split('\n').find((l) => l.startsWith('הסוגים הזמינים הם'));
  eq(!!line, true, 'נמצאה שורת הסוגים בעמוד המשתמש');
  const listed = (line.match(/``([a-z]+)``/g) || []).map((m) => m.slice(2, -2));
  eq(listed.sort().join(','), Object.keys(sandbox.window.ADMONITION_TITLES).sort().join(','),
     'הרשימה בתיעוד זהה למפה');
  // אותה סיבה בדיוק לתווית של ``::: details``: המשתמש צריך לדעת מה יוצג
  // כשלא כתב כותרת, והמחרוזת בעמוד אינה נגזרת מהקוד בזמן ריצה.
  eq(doc.includes(sandbox.window.DETAILS_DEFAULT_TITLE), true,
     'תווית ברירת המחדל של details מופיעה בעמוד המשתמש כפי שהיא בקוד');
});

/**
 * האם הנכס נטען עם ``?v={{ static_version }}``.
 *
 * **זה לא ניקיון — זה ההבדל בין פיצ'ר שעובד לפיצ'ר שלא.** הבלוק המתקפל
 * קורא את ``window.DETAILS_DEFAULT_TITLE`` מ-``admonition-icons.js``;
 * בלעדיו ``_containerSpec`` מחזיר ``null`` ו-``::: details`` נשאר טקסט
 * רגיל, בלי שגיאה ובלי סימן. שני משטחים טענו את הקובץ **בלי** מחרוזת
 * המטמון, כלומר משתמש עם עותק שמור מלפני הפיצ'ר לא היה רואה אותו כלל.
 */
function cacheBusted(src, asset){
  const tag = new RegExp("filename='" + asset.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    + "'\\s*\\)\\s*\\}\\}\\?v=\\{\\{\\s*static_version\\s*\\}\\}");
  return tag.test(src);
}

check('חיווט: כל תבנית שטוענת live-preview.js טוענת גם את מפת האלרטים, ולפניה', () => {
  // **המשטח השני שקורא מהמפה, ואותה מלכודת בדיוק.** ``live-preview.js``
  // קורא את התוויות ואת תווית ברירת המחדל של ``details`` מ-``window``;
  // בעמוד שאינו טוען את הקובץ, ה-``summary`` היה נבנה **ריק** — בלי
  // שגיאה ובלי לוג. עד היום נבדק רק המשטח של הפתקים.
  const dir = path.join(__dirname, '..', 'webapp', 'templates');
  const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]);
  const loaders = walk(dir).filter((f) => f.endsWith('.html'))
    .filter((f) => fs.readFileSync(f, 'utf8').includes("filename='js/live-preview.js'"));
  eq(loaders.length >= 3, true, 'נמצאו התבניות שטוענות את התצוגה החיה (' + loaders.length + ')');
  loaders.forEach((f) => {
    const src = fs.readFileSync(f, 'utf8');
    const icons = src.indexOf("filename='js/admonition-icons.js'");
    const live = src.indexOf("filename='js/live-preview.js'");
    eq(icons !== -1, true, path.basename(f) + ' טוען את מפת האלרטים');
    eq(icons < live, true, path.basename(f) + ' טוען אותה לפני live-preview.js');
    eq(cacheBusted(src, 'js/admonition-icons.js'), true,
       path.basename(f) + ' טוען אותה עם ?v=static_version');
  });
});

check('חיווט: כל תבנית שטוענת sticky-notes.js טוענת גם את מפת האלרטים, ולפניה', () => {
  // **זה מה שמונע מהמשטח הרביעי לשכוח.** ``_containerSpec`` קורא את
  // ``window.ADMONITION_TITLES``; בעמוד שלא טוען את הקובץ, כל אלרט היה
  // מוצג כטקסט רגיל — בלי שגיאה ובלי סימן. זה כבר היה המצב בפועל
  // ב-note_board.html לפני השינוי הזה.
  const dir = path.join(__dirname, '..', 'webapp', 'templates');
  const walk = (d) => fs.readdirSync(d, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(path.join(d, e.name)) : [path.join(d, e.name)]);
  const loaders = walk(dir).filter((f) => f.endsWith('.html'))
    .filter((f) => fs.readFileSync(f, 'utf8').includes("filename='js/sticky-notes.js'"));
  eq(loaders.length >= 3, true, 'נמצאו התבניות שטוענות את המודול (' + loaders.length + ')');
  loaders.forEach((f) => {
    const src = fs.readFileSync(f, 'utf8');
    const icons = src.indexOf("filename='js/admonition-icons.js'");
    const sticky = src.indexOf("filename='js/sticky-notes.js'");
    eq(icons !== -1, true, path.basename(f) + ' טוען את מפת האלרטים');
    eq(icons < sticky, true, path.basename(f) + ' טוען אותה לפני sticky-notes.js');
    eq(cacheBusted(src, 'js/admonition-icons.js'), true,
       path.basename(f) + ' טוען אותה עם ?v=static_version');
    eq(cacheBusted(src, 'css/sticky-notes.css'), true,
       path.basename(f) + ' טוען את ה-CSS של הפתקים עם ?v=static_version');
  });
});

check('מטא-דאטה: מקור אחד לאייקון ולתווית, ואין עותקים נוספים', () => {
  const titles = sandbox.window.ADMONITION_TITLES;
  const icons = sandbox.window.ADMONITION_ICONS;
  eq(Object.keys(titles).sort().join(','), Object.keys(icons).sort().join(','),
     'לכל סוג יש גם אייקון וגם תווית');
  // **הכפילות שצומצמה.** שני הצרכנים האחרים החזיקו מפת תוויות משלהם;
  // עותק שחוזר משאיר סוג חדש בלי תווית באחד המקומות, בשקט.
  const root = path.join(__dirname, '..');
  const consumers = [
    'webapp/static/js/live-preview.js',
    'webapp/templates/md_preview.html',
    'webapp/static/js/sticky-notes.js',
  ];
  // **השומר הקודם חיפש שם משתנה, ולכן פספס.** ב-``md_preview.html`` שרד
  // עותק שלישי של התוויות בתוך ``function defaultTitle(type){ const m={...} }``
  // — מפה מוטמעת בשורה אחת, עם שם משתנה אחר לגמרי. מה שקבוע בכל עותק אינו
  // שם המשתנה אלא **הזוג** ``note`` ← ``'הערה'``, ולכן זה מה שנבדק.
  const PAIR_RE = /note\s*:\s*['"]הערה['"]/;
  consumers.forEach((rel) => {
    eq(PAIR_RE.test(fs.readFileSync(path.join(root, rel), 'utf8')), false,
       rel + ' אינו מחזיק עותק של מפת התוויות');
  });
  // ואותו כלל לתווית של ``::: details``, שאינה במפה אבל כן במקור המשותף.
  const shared = sandbox.window.DETAILS_DEFAULT_TITLE;
  eq(typeof shared, 'string', 'התווית המשותפת קיימת');
  consumers.forEach((rel) => {
    eq(fs.readFileSync(path.join(root, rel), 'utf8').includes(shared), false,
       rel + ' אינו מחזיק עותק של תווית ברירת המחדל של details');
  });
});

// -- destroy: flush לפני פירוק --

check('destroy מרוקן את התור לפני שהוא מפרק', async () => {
  // **תקלת סדר אמיתית.** תור השמירה עובד עם debounce, ולכן עריכה שנעשתה
  // רגע לפני החלפת קובץ עדיין ממתינה. פירוק לפני ריקון היה מוחק אותה עם
  // המנהל, והמשתמש היה מגלה שהעריכה נעלמה — בלי שום סימן.
  //
  // נופל אם ``destroy`` יקרא ל-``_clearAllNotes`` לפני ``_flushAll``.
  const m = new StickyNotesManager({ repo: 'CodeBot', path: 'a.py' });
  const order = [];
  m._flushAll = async () => { order.push('flush'); };
  const realClear = m._clearAllNotes.bind(m);
  m._clearAllNotes = () => { order.push('clear'); realClear(); };

  await m.destroy();

  eq(order.join(','), 'flush,clear', 'סדר הפעולות');
});

check('destroy ממתין לכתיבה שעוד לא נחתה', async () => {
  // לא מספיק שהריקון ייקרא — צריך גם להמתין לו. בלי ``await`` הפירוק היה
  // ממשיך בזמן שהכתיבה באוויר.
  const m = new StickyNotesManager({ repo: 'CodeBot', path: 'a.py' });
  let landed = false;
  m._flushAll = async () => {
    await new Promise((r) => setTimeout(r, 5));
    landed = true;
  };
  await m.destroy();
  eq(landed, true, 'הכתיבה נחתה לפני שהפירוק הסתיים');
});


// -- destroy: ניקוי מאזינים, ביטול init, וניקוז חוזר --

const delay = (ms) => new Promise((r) => setTimeout(r, ms));

check('destroy מסיר כל מאזין שהמנהל רשם', async () => {
  // מנהל שנוצר ומפורק בכל החלפת קובץ חייב להסיר את מאזיני ה-window
  // שלו, אחרת כל ניווט מצבר עוד עותק. נופל אם destroy לא עובר על
  // _boundHandlers.
  const m = new StickyNotesManager({ repo: 'CodeBot', path: 'a.py' });
  await delay(10);
  // צילום המאזינים של **המנהל הזה** לפני הפירוק — ``_boundHandlers``
  // מתרוקן בפירוק, ואחריו אין מה להשוות מולו.
  const mine = m._boundHandlers.map((h) => h.fn);
  if (mine.length === 0) throw new Error('לא נרשמו מאזינים ב-_init');
  await m.destroy();
  eq(m._boundHandlers.length, 0, '_boundHandlers רוקן');
  eq(m._destroyed, true, '_destroyed');
  const missed = mine.filter((fn) => !sandbox.__listeners.removedFns.has(fn));
  eq(missed.length, 0, `כל מאזין הוסר (נותרו ${missed.length} מתוך ${mine.length})`);
});

check('מנהל שבוטל תוך כדי טעינה אינו רושם מאזינים', async () => {
  // _init הוא async (await loadNotes). אם המשתמש החליף קובץ בזמן שהבקשה
  // באוויר, destroy כבר סימן _destroyed, ו-_init חייב לבטל את עצמו לפני
  // רישום ה-FAB והמאזינים. נופל בלי הבדיקה if (this._destroyed) return.
  const m = new StickyNotesManager({ repo: 'CodeBot', path: 'a.py' });
  m._destroyed = true;         // בוטל לפני ש-loadNotes נחת
  await delay(10);
  eq(m._boundHandlers.length, 0, 'לא נרשמו מאזינים אחרי ביטול');
});

check('גרירה ושינוי גודל רושמים את מאזיני ה-window דרך _on', async () => {
  // כל פתק רושם ארבעה מאזיני ``window`` בגרירה וארבעה בשינוי גודל. כשהם
  // נרשמו ישירות דרך ``window.addEventListener``, ``destroy`` לא הכיר
  // אותם: כל החלפת קובץ בדפדפן הריפו הותירה שמונה סגירות חיות לכל פתק,
  // שמחזיקות את האלמנט ואת המנהל המת בזיכרון.
  //
  // נופל אם מחזירים את הרישום הישיר.
  const m = new StickyNotesManager({ repo: 'CodeBot', path: 'a.py' });
  await delay(10);
  const before = m._boundHandlers.length;
  m._enableDrag(sandbox.document.createElement('div'), sandbox.document.createElement('div'));
  m._enableResize(sandbox.document.createElement('div'), sandbox.document.createElement('div'));

  const added = m._boundHandlers.slice(before);
  eq(added.length, 8, 'שמונה מאזינים לפתק');
  eq(added.every((h) => h.target === sandbox.window), true, 'כולם על window');

  const mine = added.map((h) => h.fn);
  await m.destroy();
  const missed = mine.filter((fn) => !sandbox.__listeners.removedFns.has(fn));
  eq(missed.length, 0, `כולם הוסרו בפירוק (נותרו ${missed.length})`);
});

check('loadNotes שנחת אחרי destroy אינו נוגע בקונטיינר המשותף', async () => {
  // **ה-P1.** ``loadNotes`` הוא async, והבדיקה שהייתה קיימת ישבה רק
  // *אחריו* ב-``_init``. בדפדפן הריפו הקונטיינר משותף למנהל הבא, ולכן
  // מנהל שפורק בזמן שהבקשה באוויר היה מוחק את הפתקים שהמנהל החדש כבר
  // הרכיב, ומרנדר במקומם את התשובה של הקובץ הקודם. גם הקאש היה נדרס.
  //
  // סנדבוקס נפרד בכוונה: הבדיקה עוצרת את ``fetch``, וסנדבוקס משותף היה
  // עוצר גם בדיקות אחרות שרצות במקביל.
  //
  // נופל בלי ``if (this._destroyed) return`` בתוך ``loadNotes``.
  const sb = makeSandbox();
  let release;
  const gate = new Promise((r) => { release = r; });
  sb.fetch = async () => {
    await gate;
    return { json: async () => ({ ok: true, notes: [{ _id: '1', content: 'של הקובץ הישן' }] }) };
  };

  const m = new sb.window.StickyNotesManager({ repo: 'CodeBot', path: 'a.py' });
  await m.destroy();                  // המשתמש החליף קובץ בזמן שהבקשה באוויר

  // הריגול מותקן **אחרי** הפירוק — ל-``destroy`` עצמו מותר לנקות.
  let cleared = 0, rendered = 0, cached = 0;
  m._clearAllNotes = () => { cleared += 1; };
  m._renderNote = () => { rendered += 1; };
  m._saveCache = () => { cached += 1; };

  release();
  await delay(10);

  eq(cleared, 0, 'לא ניקה את הקונטיינר');
  eq(rendered, 0, 'ולא רינדר פתקים של הקובץ הקודם');
  eq(cached, 0, 'ולא כתב תשובה ישנה לקאש');
});

check('_flushAll מנקז עריכה שהוחזרה לתור בכשל חולף', async () => {
  // _sendUpdate מחזיר עריכה ל-_pending בכשל חולף. סבב יחיד לא מנקז אותה,
  // ו-destroy היה מוחק אותה. נופל אם _flushAll עושה סבב אחד בלבד.
  const m = new StickyNotesManager({ repo: 'CodeBot', path: 'a.py' });
  await delay(5);
  const el = { dataset: { noteId: 'n1' } };
  m.notes.set('n1', { el });
  m._pending.set('n1', { content: 'x' });
  let calls = 0;
  m._flushFor = async (e) => {
    calls += 1;
    if (calls >= 2) m._pending.delete(e.dataset.noteId); // סבב 2: הצלחה
    // סבב 1: "כשל" — התוכן נשאר בתור
  };
  await m._flushAll();
  eq(m._pending.size, 0, 'התור נוקה');
  if (calls < 2) throw new Error('לא היה סבב שני של ניקוז');
});

// **הסיכום ממתין ל-``pending``.** הוא נאסף מאז ומעולם לא הומתן: טסט
// אסינכרוני שנכשל היה מגדיל את ``failed`` **אחרי** שהסיכום כבר הודפס
// וה-process יצא — כלומר נכשל בשקט ועם קוד יציאה 0. התיקון נדרש כאן כי
// אלה הטסטים האסינכרוניים הראשונים בקובץ.
// -- נעיצה בדפדפן הריפו: המרה בין מרחב התוכן למרחב הקונטיינר --

/** קונטיינר שאינו נגלל, ובתוכו גולל פנימי — מבנה דפדפן הריפו. */
function makeRepoContainer(scrollTop) {
  const scroller = {
    className: 'CodeMirror-scroll',
    scrollTop, scrollLeft: 0,
    offsetParent: null,
    getBoundingClientRect: () => ({ left: 0, top: 40, width: 900, height: 600, bottom: 640 }),
  };
  return {
    style: {}, dataset: {}, clientLeft: 0, clientTop: 0, scrollLeft: 0, scrollTop: 0,
    clientWidth: 900, clientHeight: 640,
    classList: { add() {}, remove() {}, contains: () => false },
    appendChild() {}, addEventListener() {}, removeEventListener() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 900, height: 680, bottom: 680 }),
    querySelector: (sel) => (sel === '.CodeMirror-scroll' ? scroller : null),
    querySelectorAll: () => [],
    __scroller: scroller,
  };
}

check('פתק ריפו נעוץ מרונדר לפי מיקום הגלילה הפנימית', () => {
  // זה הלב: המיקום נשמר במרחב **התוכן** ומרונדר במרחב **הקונטיינר**.
  // בלי ההיסט, ``absolute`` בקונטיינר שאינו נגלל מרנדר תמיד באותו מקום —
  // ואז "נעוץ" ו"צף" נראים זהים והכפתור מרגיש שבור.
  //
  // נופל אם ההיסט יוסר מ-``_applyPositionMode``.
  const sb = makeSandbox();
  const Manager = sb.window.StickyNotesManager;
  const container = makeRepoContainer(300);
  // הפותר מוזרק, בדיוק כפי ש-``repo-notes.js`` מזריק אותו. המנהל הגנרי
  // אינו מכיר את מחלקות הרנדרר.
  const m = new Manager({ repo: 'CodeBot', path: 'a.py', container,
                          scroller: () => container.__scroller });

  const el = { style: {}, dataset: {}, classList: { add() {}, remove() {}, contains: () => false },
               querySelector: () => null, querySelectorAll: () => [],
               getBoundingClientRect: () => ({ left: 0, top: 0, width: 260, height: 200, bottom: 200 }) };
  m._applyPositionMode(el, { mode: 'surface', position: { x: 10, y: 500 }, size: { width: 260, height: 200 } });

  // הגולל מתחיל 40px מתחת לקונטיינר, ונגלל 300 ⇒ ההיסט הוא 40-300 = -260
  eq(el.style.top, '240px', 'התוכן בגובה 500 מרונדר ב-240');
});

check('אותו פתק בגלילה אחרת מרונדר במקום אחר', () => {
  // אותה בדיקה מהצד השני: שינוי ה-scrollTop **חייב** לשנות את הרינדור.
  const sb = makeSandbox();
  const Manager = sb.window.StickyNotesManager;
  const container0 = makeRepoContainer(0);
  const m = new Manager({ repo: 'CodeBot', path: 'a.py', container: container0,
                          scroller: () => container0.__scroller });

  const el = { style: {}, dataset: {}, classList: { add() {}, remove() {}, contains: () => false },
               querySelector: () => null, querySelectorAll: () => [],
               getBoundingClientRect: () => ({ left: 0, top: 0, width: 260, height: 200, bottom: 200 }) };
  m._applyPositionMode(el, { mode: 'surface', position: { x: 10, y: 500 }, size: { width: 260, height: 200 } });

  eq(el.style.top, '540px', 'בלי גלילה: 500 + היסט 40');
});

check('פתק לוח אינו מושפע מההיסט', () => {
  // רגרסיה: הלוח והקובץ אינם עוברים דרך גולל פנימי, וההיסט חייב להיות
  // אפס אצלם — אחרת התיקון לדפדפן הריפו היה מזיז להם את הפתקים.
  const sb = makeSandbox();
  const Manager = sb.window.StickyNotesManager;
  const boardContainer = makeRepoContainer(300);
  const m = new Manager({ board: 'b1', container: boardContainer,
                          scroller: () => boardContainer.__scroller });

  const el = { style: {}, dataset: {}, classList: { add() {}, remove() {}, contains: () => false },
               querySelector: () => null, querySelectorAll: () => [],
               getBoundingClientRect: () => ({ left: 0, top: 0, width: 260, height: 200, bottom: 200 }) };
  m._applyPositionMode(el, { mode: 'surface', position: { x: 10, y: 500 }, size: { width: 260, height: 200 } });

  eq(el.style.top, '500px', 'הלוח נשאר בדיוק על הערך השמור');
});

check('פתק שהוסתר בגלילה חוזר להיראות כשעובר למצב צף', () => {
  // ``_updatePinnedVisibility`` מסתיר פתק נעוץ שנגלל מחוץ לתחום. אם
  // המשתמש לחץ אז על הכפתור, הענף הצף כלל לא כתב ל-``visibility`` —
  // והפתק נשאר בלתי נראה לתמיד, בלי שום דרך להחזיר אותו.
  //
  // נופל בלי ניקוי ``visibility`` בענף הצף.
  const sb = makeSandbox();
  const Manager = sb.window.StickyNotesManager;
  const container = makeRepoContainer(0);
  const m = new Manager({ repo: 'CodeBot', path: 'a.py', container,
                          scroller: () => container.__scroller });

  const el = { style: { visibility: 'hidden' }, dataset: {},
               classList: { add() {}, remove() {}, contains: () => false },
               querySelector: () => null, querySelectorAll: () => [],
               getBoundingClientRect: () => ({ left: 0, top: 0, width: 260, height: 200, bottom: 200 }) };

  m._applyPositionMode(el, { mode: 'screen', position: { x: 10, y: 20 }, size: { width: 260, height: 200 } });

  eq(el.style.visibility, '', 'ההסתרה נוקתה');
});

check('רענון גלילה מחשב את ההיסט פעם אחת לכל הפתקים', () => {
  // כל קריאת ``getBoundingClientRect`` מכריחה חישוב פריסה. בגלילה רציפה
  // זה קורה בכל פריים, ולכן החישוב חייב להיות פעם אחת לאירוע ולא פעם
  // לכל פתק.
  //
  // נופל אם ``_updatePinnedForScroll`` מפסיק להעביר ``posCtx``.
  const sb = makeSandbox();
  const Manager = sb.window.StickyNotesManager;
  const container = makeRepoContainer(100);
  let rectReads = 0;
  const scroller = container.__scroller;
  const origRect = scroller.getBoundingClientRect;
  scroller.getBoundingClientRect = function () { rectReads += 1; return origRect(); };

  const m = new Manager({ repo: 'CodeBot', path: 'a.py', container,
                          scroller: () => scroller });

  const mkEl = () => ({ style: {}, dataset: {},
    classList: { add() {}, remove() {}, contains: (c) => c === 'is-pinned' },
    querySelector: () => null, querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 260, height: 200, bottom: 200 }) });
  for (const id of ['a', 'b', 'c']) {
    m.notes.set(id, { el: mkEl(), data: { mode: 'surface', position: { x: 0, y: 50 }, size: { width: 260, height: 200 } } });
  }

  rectReads = 0;
  m._updatePinnedForScroll();

  // אחת ל-``_surfaceScrollShift`` ואחת ל-``scrollerRect`` — ולא פי שלושה
  eq(rectReads, 2, 'שתי קריאות פריסה לשלושה פתקים');
});

check('refreshPinned ממקם מחדש את הפתקים הנעוצים', () => {
  // הקרס הציבורי שהצרכן קורא לו כשהתצוגה — ולכן הגולל — התחלפה.
  //
  // נופל אם ``refreshPinned`` יפסיק לקרוא ל-``_updatePinnedForScroll``.
  const sb = makeSandbox();
  const Manager = sb.window.StickyNotesManager;
  const container = makeRepoContainer(250);
  const m = new Manager({ repo: 'CodeBot', path: 'a.py', container,
                          scroller: () => container.__scroller });

  const el = { style: {}, dataset: {},
    classList: { add() {}, remove() {}, contains: (c) => c === 'is-pinned' },
    querySelector: () => null, querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 260, height: 200, bottom: 200 }) };
  m.notes.set('n', { el, data: { mode: 'surface', position: { x: 0, y: 400 }, size: { width: 260, height: 200 } } });

  m.refreshPinned();

  // הגולל מתחיל 40 מתחת לקונטיינר ונגלל 250 ⇒ 400 + (40-250) = 190
  eq(el.style.top, '190px', 'המיקום חושב מחדש לפי הגולל הנוכחי');
});

// -- פלטת הצבעים: הצלבה בין שלושת הצרכנים ------------------------------
//
// ``NOTE_COLORS`` חי פעמיים — ב-``sticky_notes_target.py`` וב-
// ``sticky-notes.js`` — ואי אפשר לגזור אחד מהשני בזמן ריצה בלי לטעון
// פייתון בדפדפן. זו בדיוק המצוקה שכבר תועדה על ``STICKY_NOTE_FONT_SIZES``,
// והתשובה שם היא התשובה כאן: **מקור שני מותר, בתנאי שבדיקה מצליבה
// ביניהם**. בלעדיה, צבע שנוסף בצד אחד היה יוצא עיגול שלא נשמר, או ערך
// שנשמר ואין לו עיגול.

/** רשימת גוונים מתוך מקור — ``'#a', '#b'`` בשתי השפות, בהשוואה חסרת-רישיות. */
function readHexList(raw) {
  return (String(raw).match(/#[0-9A-Fa-f]{3,8}/g) || []).map(h => h.toLowerCase());
}

/** חילוץ אובייקט ``NOTE_COLORS`` מקוד המקור, בלי להריץ את המודול כולו. */
function paletteFromJs() {
  const src = fs.readFileSync(MODULE_PATH, 'utf8');
  const m = src.match(/const NOTE_COLORS = \{([\s\S]*?)\n  \};/);
  if (!m) throw new Error('לא נמצא NOTE_COLORS ב-sticky-notes.js');
  const out = [];
  const re = /(\w+):\s*\{\s*hex:\s*'(#[0-9a-f]{6})',\s*label:\s*'([^']+)',\s*legacy:\s*\[([^\]]*)\]\s*\}/g;
  let hit;
  while ((hit = re.exec(m[1]))) {
    out.push({ id: hit[1], hex: hit[2], label: hit[3], legacy: readHexList(hit[4]) });
  }
  return out;
}

/** אותה פלטה כפי שהיא מוקלדת ב-``sticky_notes_target.py``. */
function paletteFromPython() {
  const src = fs.readFileSync(path.join(__dirname, '..', 'sticky_notes_target.py'), 'utf8');
  const m = src.match(/^NOTE_COLORS: Dict\[str, Dict\[str, Any\]\] = \{([\s\S]*?)^\}/m);
  if (!m) throw new Error('לא נמצא NOTE_COLORS ב-sticky_notes_target.py');
  const out = [];
  const re = /"(\w+)":\s*\{"hex":\s*"(#[0-9a-f]{6})",\s*"label":\s*"([^"]+)",\s*"legacy":\s*\(([^)]*)\)/g;
  let hit;
  while ((hit = re.exec(m[1]))) {
    out.push({ id: hit[1], hex: hit[2], label: hit[3], legacy: readHexList(hit[4]) });
  }
  return out;
}

check('הפלטה זהה ב-JS ובפייתון — מזהים, גוונים, תוויות וסדר', () => {
  // נופל כשצבע נוסף, מוסר, משנה גוון או משנה מקום בצד אחד בלבד.
  const js = paletteFromJs();
  const py = paletteFromPython();
  eq(js.length, 6, 'שישה צבעים ב-JS');
  eq(JSON.stringify(js), JSON.stringify(py), 'הפלטה ב-JS מול פייתון');
});

check('ברירת המחדל זהה בשני הצדדים, והיא צבע שקיים בפלטה', () => {
  // ברירת מחדל שאינה בפלטה היא פתק שנולד בצבע שאי אפשר לבחור בו חזרה.
  const jsSrc = fs.readFileSync(MODULE_PATH, 'utf8');
  const pySrc = fs.readFileSync(path.join(__dirname, '..', 'sticky_notes_target.py'), 'utf8');
  const jsDefault = (jsSrc.match(/const DEFAULT_NOTE_COLOR_ID = '([^']+)'/) || [])[1];
  const pyDefault = (pySrc.match(/^DEFAULT_NOTE_COLOR_ID = "([^"]+)"/m) || [])[1];
  eq(jsDefault, pyDefault, 'ברירת המחדל');
  eq(paletteFromJs().some(c => c.id === jsDefault), true, 'ברירת המחדל קיימת בפלטה');
});

check('הבורר לא יורש צבע מהערכה — אף var() בכללים שלו', () => {
  // הפתק הוא משטח קשיח, והבורר מציג את הצבעים **עצמם**: ערכה שתצבע את
  // הכרטיס מחדש תשנה בדיוק את מה שהמשתמש בא להשוות אליו. זו ההחלטה
  // ש-``docs/webapp/theming_and_css`` מגדיר לפתקים, והשומר הזה אוכף אותה.
  //
  // ההערות מוסרות לפני הבדיקה — אחרת הפרוזה שמסבירה את הכלל הייתה
  // מפילה אותו, וזו מלכודת שכבר נתפסה כאן פעם.
  const css = fs.readFileSync(
    path.join(__dirname, '..', 'webapp', 'static', 'css', 'sticky-notes.css'), 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, '');
  const rules = css.split('}').filter(r => /\.sticky-color-/.test(r));
  eq(rules.length > 0, true, 'נמצאו כללי הבורר ב-sticky-notes.css');
  const leaking = rules.filter(r => /var\(--/.test(r));
  eq(leaking.length, 0, 'אף כלל של הבורר אינו קורא טוקן ערכה: ' + leaking.join(' | '));
});

// **DOM מינימלי, אבל לא מקרטון.** הסנדבוקס המשותף מחזיר ``appendChild``
// ריק ו-``querySelector`` שהוא תמיד ``null`` — כלומר מודאל שנבנה חלקית,
// או עיגול בלי מאזין, היו עוברים בו בלי להיתפס. jsdom אינו בתלויות
// הפרויקט ואין סיבה להוסיף אותו בשביל בדיקה אחת, ולכן כאן יש עץ צמתים
// אמיתי: ``appendChild`` באמת מצרף, ``querySelector`` באמת סורק אותו לפי
// מחלקות, ולחיצה באמת מפעילה את המאזין שנרשם.
//
// זה גם מה שנפתח כשהמודאל הפסיק להשתמש ב-``innerHTML``: שלד שנבנה
// בצמתים אפשר לבדוק בלי פרסר HTML.
function makeDomSandbox() {
  const matches = (node, sel) =>
    sel.split('.').filter(Boolean).every(c => node.__classes.has(c));
  const collect = (node, sel, out) => {
    node.children.forEach(child => {
      if (matches(child, sel)) out.push(child);
      collect(child, sel, out);
    });
    return out;
  };

  function makeNode(tag) {
    const classes = new Set();
    const listeners = {};
    const node = {
      tagName: String(tag).toUpperCase(),
      style: {}, dataset: {}, children: [], parentNode: null,
      textContent: '', value: '', disabled: false,
      __classes: classes, __attrs: {},
      get className() { return [...classes].join(' '); },
      set className(v) { classes.clear(); String(v || '').split(/\s+/).filter(Boolean).forEach(c => classes.add(c)); },
      classList: {
        add: (c) => classes.add(c),
        remove: (c) => classes.delete(c),
        contains: (c) => classes.has(c),
        toggle: (c, on) => (on ? classes.add(c) : classes.delete(c)),
      },
      setAttribute(k, v) { this.__attrs[k] = String(v); if (k === 'class') this.className = v; },
      getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.__attrs, k) ? this.__attrs[k] : null; },
      appendChild(child) { child.parentNode = node; node.children.push(child); return child; },
      remove() {
        const p = node.parentNode;
        if (p) p.children = p.children.filter(c => c !== node);
        node.parentNode = null;
      },
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      removeEventListener(type, fn) {
        if (listeners[type]) listeners[type] = listeners[type].filter(f => f !== fn);
      },
      focus() {},
      querySelectorAll(sel) { return collect(node, sel, []); },
      querySelector(sel) { return collect(node, sel, [])[0] || null; },
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }),
      __fire(type, ev) { (listeners[type] || []).forEach(fn => fn(ev || { stopPropagation() {}, preventDefault() {} })); },
    };
    return node;
  }

  const body = makeNode('body');
  const sandbox = {
    console,
    document: {
      body,
      createElement: (t) => makeNode(t),
      createElementNS: (_ns, t) => makeNode(t),
      getElementById: () => null,
      querySelector: (sel) => body.querySelector(sel),
      querySelectorAll: (sel) => body.querySelectorAll(sel),
      addEventListener() {}, removeEventListener() {},
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
  vm.runInContext(fs.readFileSync(ADMONITION_PATH, 'utf8'), sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox;
}

check('הבורר מציג את כל הפלטה, מסמן את הנוכחי, ושומר את המזהה', () => {
  // הבדיקה עוברת דרך אותו ממשק כמו המשתמש — פותחת את המודאל ולוחצת על
  // עיגול — ולא קוראת ל-``_applyNoteColor`` ישירות. בדיקה שעוקפת את
  // המודאל עוברת גם כשהעיגול נבנה בלי מאזין.
  const sb = makeDomSandbox();
  const m = new sb.window.StickyNotesManager('abc123');

  const saved = [];
  m._queueSave = (el, fragment) => { saved.push(fragment); };
  m._flushFor = async () => {};

  const el = sb.document.createElement('div');
  el.dataset.noteId = 'n1';
  m.notes.set('n1', { el, data: { color: 'green_light' } });

  m._openColorModal(el);

  const modal = sb.document.body.querySelector('.sticky-color-modal');
  eq(!!modal, true, 'המודאל נוסף ל-body');
  eq(!!modal.querySelector('.sticky-color-backdrop'), true, 'יש רקע לסגירה');
  eq(!!modal.querySelector('.sticky-color-close'), true, 'יש כפתור סגירה');

  const swatches = modal.querySelectorAll('.sticky-color-swatch');
  eq(swatches.length, 6, 'עיגול לכל צבע בפלטה');
  eq(swatches.map(s => s.getAttribute('data-color-id')).join(','),
     'yellow_light,green_light,orange_light,blue_light,purple_light,pink_light',
     'בסדר של הפלטה');
  // הצבע יושב ב-style ולא במחלקה — כלל CSS לכל גוון היה מקור שני,
  // וצבע שביעי היה יוצא עיגול לבן.
  eq(swatches[0].style.backgroundColor, '#ffffba', 'העיגול נצבע בגוון עצמו');
  // התווית ב-textContent ולא כמחרוזת HTML.
  eq(swatches[0].querySelector('.sticky-color-label').textContent, 'צהוב בהיר');

  // **הצבע הנוכחי נקרא מהרשומה.** ``style.backgroundColor`` מוחזר
  // מדפדפן אמיתי כ-``rgb(...)``, ולכן השוואה מולו הייתה משאירה כל
  // עיגול לא מסומן — מצב שנראה תקין לגמרי עד שבודקים.
  const active = swatches.filter(s => s.getAttribute('aria-pressed') === 'true');
  eq(active.length, 1, 'בדיוק אחד מסומן');
  eq(active[0].getAttribute('data-color-id'), 'green_light', 'המסומן הוא הצבע השמור');

  swatches.find(s => s.getAttribute('data-color-id') === 'pink_light').__fire('click');
  eq(saved.length, 1, 'יצאה כתיבה אחת');
  eq(saved[0].color, 'pink_light', '**המזהה** נשמר, ולא ה-hex');
  eq(el.style.backgroundColor, '#ffdbdf', 'והפתק נצבע ב-hex שנגזר ממנו');
  eq(sb.document.body.querySelector('.sticky-color-modal'), null, 'המודאל נסגר אחרי הבחירה');
});

check('פתק בצבע legacy פותח בורר בלי שום עיגול מסומן', () => {
  // ``''`` אינו כשל — הוא התשובה הנכונה ל"הצבע הזה אינו בפלטה". עיגול
  // שהיה מסומן כאן היה אומר למשתמש שהפתק בצבע שהוא אינו בו.
  const sb = makeDomSandbox();
  const m = new sb.window.StickyNotesManager('abc123');
  m._queueSave = () => {}; m._flushFor = async () => {};

  const el = sb.document.createElement('div');
  el.dataset.noteId = 'n1';
  m.notes.set('n1', { el, data: { color: '#123456' } });
  m._openColorModal(el);

  const swatches = sb.document.body.querySelectorAll('.sticky-color-swatch');
  eq(swatches.length, 6, 'הפלטה עדיין מוצגת במלואה');
  eq(swatches.filter(s => s.getAttribute('aria-pressed') === 'true').length, 0,
     'אף עיגול אינו מסומן');
});

check('hex של הפלטה שמגיע מהשרת מסמן את העיגול הנכון', () => {
  // השרת מחזיר ``color`` כ-hex, ופתק שנוצר ברגע זה נושא עדיין מזהה.
  // פונקציה שידעה רק אחת מהצורות הייתה נכונה במחצית מהמקרים, והבורר
  // היה נראה ריק בדיוק אחרי רענון עמוד.
  const sb = makeDomSandbox();
  const m = new sb.window.StickyNotesManager('abc123');
  m._queueSave = () => {}; m._flushFor = async () => {};

  const el = sb.document.createElement('div');
  el.dataset.noteId = 'n1';
  // ``#FFFFCC`` — ברירת המחדל ההיסטורית, כפי שהיא יושבת אצל משתמש קיים.
  m.notes.set('n1', { el, data: { color: '#FFFFCC' } });
  m._openColorModal(el);

  const active = sb.document.body.querySelectorAll('.sticky-color-swatch')
    .filter(s => s.getAttribute('aria-pressed') === 'true');
  eq(active.length, 1, 'הגוון ההיסטורי מזוהה');
  eq(active[0].getAttribute('data-color-id'), 'yellow_light');
});

(async () => {
  await Promise.all(pending);
  console.log(`\n${passed} עברו, ${failed} נכשלו`);
  process.exit(failed === 0 ? 0 : 1);
})();
