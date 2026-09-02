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
  set textContent(v) { this.children = []; this._text = String(v); }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join('') : this._text; }
  setAttribute(k, v) { this._attrs[k] = String(v); }
  getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; }
  // ``removeAttribute``, ``select`` ו-``blur`` קיימים בכל דפדפן, והקוד
  // קורא להם מאחורי guard. בלי מימוש כאן ה-guard מדלג בשקט והבדיקה
  // עוברת סתם — בדיוק כמו שקרה עם ``remove`` בסבב קודם.
  removeAttribute(k) { delete this._attrs[k]; }
  hasAttribute(k) { return k in this._attrs; }
  addEventListener() {}
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

check('רינדור: בלוק קוד — הגדר גלויה, התוכן ליטרלי', () => {
  const { view } = renderMd(mdMgr, '```\na*b*\n```');
  const pre = view.querySelectorAll('.sticky-md-pre');
  eq(pre.length, 3, 'שלוש שורות: גדר, תוכן, גדר');
  // התוכן בקוד אינו מפורש לאינליין — אין ``em``, והטקסט **מלא**.
  eq(!!view.querySelector('.sticky-md-italic'), false, 'אין נטוי בתוך קוד');
  eq(pre[1].textContent, 'a*b*', 'שורת התוכן ליטרלית, כולל הכוכביות');
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
  eq(pre[1].textContent, '- [ ] בקוד', 'הדוגמה בגדר נשארה ליטרלית');
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
  eq(d[4], 1, 'הפריט שאחרי הגדר חוזר לעומק שלו');
  eq(view.querySelectorAll('.sticky-md-pre').length, 3, 'שלוש שורות ליטרליות');
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
  const { view } = renderMd(mdMgr, '- א\n```\n- לא רשימה\n```\n  - ב');
  eq(depths(view).join(','), '0,0,0,0,0');
  const rows = view.querySelectorAll('.sticky-task-line');
  eq(rows[4].classList.contains('is-depth-1'), false, 'ואין מחלקת עומק על השורה שאחריה');
  eq(rows[4].classList.contains('sticky-md-li'), true, 'והיא עדיין פריט רשימה');
});

check('גדר: פתיחה שאינה מגיעה לעמודת התוכן סוגרת גם היא', () => {
  // רווח אחד אינו מגיע לעמודה 2 שבה מתחיל הטקסט של ``- א``.
  const { view } = renderMd(mdMgr, '- א\n ```\n x\n ```\n  - ב');
  eq(depths(view).join(','), '0,0,0,0,0');
});

check('גדר: מקוננת סוגרת רק את מה שמעליה', () => {
  // הגדר בעמודה 2 סוגרת את ``  - ב`` (עמודת תוכן 4) ומשאירה את ``- א``
  // (עמודת תוכן 2) פתוח, ולכן ``    - ג`` יוצא רמה 1 ולא רמה 2.
  const { view } = renderMd(mdMgr, '- א\n  - ב\n  ```\n  x\n  ```\n    - ג');
  eq(depths(view).join(','), '0,1,0,0,0,1');
  const rows = view.querySelectorAll('.sticky-task-line');
  eq(rows[5].classList.contains('is-depth-1'), true, 'מחלקת רמה 1');
  eq(rows[5].classList.contains('is-depth-2'), false, 'ולא רמה 2');
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
  eq(depths(view).join(','), '0,0,0,0,1', 'הפריט שאחרי הסגירה נשאר בתוך הפריט שמעליו');
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
  eq(!!view.querySelector('.sticky-md-pre'), true, 'השורה מרונדרת כקוד');
  eq(!!view.querySelector('.is-fence'), true, 'והיא מסומנת כפותחת גדר');
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

(async () => {
  await Promise.all(pending);
  console.log(`\n${passed} עברו, ${failed} נכשלו`);
  process.exit(failed === 0 ? 0 : 1);
})();
