'use strict';
// בדיקות על מתג כתב-היד של הלוח, ועל טעינת הגופן שלו.
//
// **למה קובץ חדש:** הלוגיקה חיה בסקריפטים מוטבעים ב-``note_board.html``, ולא
// בקובץ ``.js``. הטסטים הקיימים על התבנית בודקים מחרוזות ב-HTML, וזה מאמת
// שהמתג *קיים* אבל לא שהוא *עושה* משהו. כאן מחלצים את שני הבלוקים —
// זה שבראש העמוד וזה שבגוף — ומריצים אותם יחד מול ``localStorage``
// ו-``document`` מדומים, כפי שהם רצים בדפדפן.
//
// החילוץ מעוגן בשמות בלוקים ופונקציות ולא במספרי שורות, כדי שעריכה
// בתבנית לא תשבור אותו בשקט.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TEMPLATE = path.join(__dirname, '..', 'webapp', 'templates', 'note_board.html');
const SRC = fs.readFileSync(TEMPLATE, 'utf8');

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}

/** מחלץ את הסקריפט המוטבע שבתוך ``{% block extra_head %}``. */
function headScript(boardId) {
  const blockAt = SRC.indexOf('{% block extra_head %}');
  if (blockAt < 0) throw new Error('הבלוק extra_head לא נמצא בתבנית');
  const open = SRC.indexOf('<script>', blockAt);
  const close = SRC.indexOf('</script>', open);
  if (open < 0 || close < 0) throw new Error('לא נמצא סקריפט בתוך extra_head');
  return SRC.slice(open + '<script>'.length, close)
            .replace('{{ board_id | tojson }}', JSON.stringify(boardId));
}

/** מחלץ את בלוק כתב-היד מגוף העמוד. */
function bodyScript() {
  const start = SRC.indexOf('const HANDWRITING_KEY');
  if (start < 0) throw new Error('בלוק כתב-היד לא נמצא בתבנית');
  const end = SRC.indexOf('// מארקדאון דלוק כברירת מחדל', start);
  if (end < 0) throw new Error('סוף הבלוק לא נמצא — העוגן השתנה');
  return SRC.slice(start, end);
}

/**
 * בונה הקשר עם ``document``/``localStorage`` מדומים ומריץ את סקריפט
 * הראש. ``preset`` הוא מצב ה-localStorage *לפני* טעינת העמוד — כך
 * מדמים משתמש שכבר הדליק את ההעדפה בביקור קודם.
 */
function loadBoard(boardId, preset) {
  const store = new Map();
  if (preset !== undefined) store.set('board-handwriting:' + boardId, preset);

  const classes = new Set();
  const links = [];
  const byId = new Map();

  const sandbox = {
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => { store.set(k, String(v)); },
      removeItem: (k) => { store.delete(k); },
    },
    document: {
      createElement: () => ({ rel: '', href: '', id: '' }),
      getElementById: (id) => (byId.has(id) ? byId.get(id) : null),
      head: { appendChild: (el) => { links.push(el); if (el.id) byId.set(el.id, el); } },
      body: { classList: {
        toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); },
      } },
    },
    __store: store,
    __classes: classes,
    __links: links,
  };
  vm.createContext(sandbox);
  sandbox.window = sandbox;               // בדפדפן ``window`` הוא הגלובל
  vm.runInContext(headScript(boardId), sandbox);
  return sandbox;
}

/** מריץ גם את בלוק הגוף וחושף את שלוש הפונקציות שלו. */
function loadHandwriting(boardId, preset) {
  const sandbox = loadBoard(boardId, preset);
  vm.runInContext(
    bodyScript() + '\nthis.__api = { readHandwriting, writeHandwriting, applyHandwriting };',
    sandbox,
  );
  return sandbox;
}

const FONT = 'Gveret+Levin';
const fontLinks = (s) => s.__links.filter((l) => String(l.href).includes(FONT));

// ─── טעינת הגופן ────────────────────────────────────────────────────────

check('כבוי בטעינה — הגופן אינו נטען כלל', () => {
  // זה הממצא של cubic: קישור סטטי היה נטען גם למי שלא הדליק מעולם.
  const s = loadBoard('b1');
  eq(fontLinks(s).length, 0, 'קישורי גופן');
});

check('דלוק בטעינה — הגופן נטען כבר בראש העמוד', () => {
  const s = loadBoard('b1', '1');
  eq(fontLinks(s).length, 1, 'קישורי גופן');
  eq(fontLinks(s)[0].rel, 'stylesheet', 'rel');
});

check('הדלקה באמצע הסשן טוענת את הגופן', () => {
  // **הכשל שהזרקה-בטעינה-בלבד הייתה מייצרת:** המחלקה מוחלת, הגופן
  // מעולם לא נטען, והטקסט נופל ל-``cursive`` הגנרי של הדפדפן.
  const s = loadHandwriting('b2');
  eq(fontLinks(s).length, 0, 'לפני ההדלקה');
  s.__api.applyHandwriting(true);
  eq(fontLinks(s).length, 1, 'אחרי ההדלקה');
});

check('טעינת הגופן אידמפוטנטית', () => {
  const s = loadHandwriting('b3', '1');
  s.__api.applyHandwriting(true);
  s.__api.applyHandwriting(false);
  s.__api.applyHandwriting(true);
  eq(fontLinks(s).length, 1, 'קישור אחד בלבד');
});

check('כיבוי אינו מוסיף קישור', () => {
  const s = loadHandwriting('b4');
  s.__api.applyHandwriting(false);
  eq(fontLinks(s).length, 0, 'קישורי גופן');
});

check('אחסון חסום בטעינה אינו מפיל את העמוד', () => {
  // מצב פרטי זורק מ-``localStorage``. העמוד חייב להיטען, בלי הגופן.
  const store = new Map();
  const sandbox = {
    localStorage: { getItem: () => { throw new Error('blocked'); } },
    document: {
      createElement: () => ({ rel: '', href: '', id: '' }),
      getElementById: () => null,
      head: { appendChild: () => { throw new Error('לא היה אמור להגיע לכאן'); } },
      body: { classList: { toggle: () => {} } },
    },
    __store: store,
  };
  vm.createContext(sandbox);
  sandbox.window = sandbox;
  vm.runInContext(headScript('b5'), sandbox);   // לא זורק
});

// ─── ההעדפה עצמה ────────────────────────────────────────────────────────

check('המפתח נושא את מזהה הלוח, ולא גלובלי', () => {
  // **זה הכשל שנראה זהה בבדיקה ידנית.** מפתח גלובלי עובד מושלם על לוח
  // אחד, ורק כשעוברים ללוח שני מגלים שההעדפה דלפה.
  const a = loadHandwriting('board-aaa');
  a.__api.writeHandwriting(true);
  eq([...a.__store.keys()][0], 'board-handwriting:board-aaa', 'המפתח');
});

check('סקריפט הראש והגוף חולקים מפתח אחד', () => {
  // אם המחרוזת תיכתב פעמיים היא תיסחף בשקט: הגוף ישמור תחת מפתח אחד
  // והראש יקרא מאחר, והגופן לא ייטען בטעינה הבאה.
  const s = loadHandwriting('board-shared');
  s.__api.writeHandwriting(true);
  eq([...s.__store.keys()][0], s.window.HANDWRITING_KEY, 'מפתח הכתיבה מול מפתח הראש');
});

check('הדלקה מוסיפה את המחלקה, כיבוי מסיר', () => {
  const s = loadHandwriting('b6');
  s.__api.applyHandwriting(true);
  eq(s.__classes.has('board-handwriting'), true, 'אחרי הדלקה');
  s.__api.applyHandwriting(false);
  eq(s.__classes.has('board-handwriting'), false, 'אחרי כיבוי');
});

check('ההעדפה נקראת חזרה — הלוך ושוב מלא', () => {
  // ``writeHandwriting`` מחזיר ``undefined``, ולכן הכתיבה מאומתת בקריאה
  // חוזרת ולא בערך ההחזרה.
  const s = loadHandwriting('b7');
  eq(s.__api.readHandwriting(), false, 'ברירת המחדל כבויה');
  s.__api.writeHandwriting(true);
  eq(s.__api.readHandwriting(), true, 'אחרי הדלקה');
  s.__api.writeHandwriting(false);
  eq(s.__api.readHandwriting(), false, 'אחרי כיבוי');
});

check('לוחות אינם דולפים זה לזה', () => {
  const a = loadHandwriting('board-a');
  const b = loadHandwriting('board-b');
  a.__api.writeHandwriting(true);
  b.__api.writeHandwriting(false);
  eq([...a.__store.keys()][0] === [...b.__store.keys()][0], false, 'המפתחות שונים');
});

check('אחסון חסום אינו מפיל את הלוח', () => {
  const s = loadHandwriting('b8');
  s.localStorage.setItem = () => { throw new Error('blocked'); };
  s.localStorage.getItem = () => { throw new Error('blocked'); };
  s.__api.writeHandwriting(true);          // לא זורק
  eq(s.__api.readHandwriting(), false, 'נופל לברירת המחדל');
});

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
