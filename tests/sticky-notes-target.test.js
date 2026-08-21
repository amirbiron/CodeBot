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
  const mdContent = el();
  const sandbox = {
    console,
    document: {
      body,
      // מחזיר אלמנט אמיתי, אחרת הבדיקה על _anchorHost לא יכולה להיכשל
      getElementById: (id) => (id === 'md-content' ? mdContent : null),
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
      add: (c) => this._classes.add(c),
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
  addEventListener() {}
  focus() { FakeEl.focused = this; }
  _matches(sel) { return sel.startsWith('.') ? this._classes.has(sel.slice(1)) : this.tagName === sel; }
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
  eq(view.textContent.includes('- פריט רגיל'), true, 'פריט רשימה שאינו משימה');
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

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
