'use strict';
// בדיקות על מתג כתב-היד של הלוח.
//
// **למה קובץ חדש:** הלוגיקה חיה בסקריפט מוטבע ב-``note_board.html``, ולא
// בקובץ ``.js``. הטסטים הקיימים על התבנית בודקים מחרוזות ב-HTML, וזה מאמת
// שהמתג *קיים* אבל לא שהוא *עושה* משהו. כאן מחלצים את שלוש הפונקציות
// ומריצים אותן מול ``localStorage`` ו-``document`` מדומים.
//
// החילוץ מעוגן בשמות הפונקציות ולא במספרי שורות, כדי שעריכה בתבנית לא
// תשבור אותו בשקט.

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

/** מחלץ את בלוק כתב-היד מהתבנית ומריץ אותו עם BOARD_ID נתון. */
function loadHandwriting(boardId) {
  const start = SRC.indexOf('const HANDWRITING_KEY');
  if (start < 0) throw new Error('בלוק כתב-היד לא נמצא בתבנית');
  const endMarker = SRC.indexOf('// מארקדאון דלוק כברירת מחדל', start);
  if (endMarker < 0) throw new Error('סוף הבלוק לא נמצא — העוגן השתנה');
  const block = SRC.slice(start, endMarker);

  const store = new Map();
  const classes = new Set();
  const sandbox = {
    BOARD_ID: boardId,
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => { store.set(k, String(v)); },
      removeItem: (k) => { store.delete(k); },
    },
    document: { body: { classList: {
      toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); },
    } } },
    __store: store,
    __classes: classes,
  };
  vm.createContext(sandbox);
  vm.runInContext(block + '\nthis.__api = { readHandwriting, writeHandwriting, applyHandwriting };', sandbox);
  return sandbox;
}

check('המפתח נושא את מזהה הלוח, ולא גלובלי', () => {
  // **זה הכשל שנראה זהה בבדיקה ידנית.** מפתח גלובלי עובד מושלם על לוח
  // אחד, ורק כשעוברים ללוח שני מגלים שההעדפה דלפה.
  const a = loadHandwriting('board-aaa');
  a.__api.writeHandwriting(true);
  eq([...a.__store.keys()][0], 'board-handwriting:board-aaa', 'המפתח');
});

check('הדלקה מוסיפה את המחלקה, כיבוי מסיר', () => {
  const s = loadHandwriting('b1');
  s.__api.applyHandwriting(true);
  eq(s.__classes.has('board-handwriting'), true, 'אחרי הדלקה');
  s.__api.applyHandwriting(false);
  eq(s.__classes.has('board-handwriting'), false, 'אחרי כיבוי');
});

check('ההעדפה נקראת חזרה — הלוך ושוב מלא', () => {
  // ``writeHandwriting`` מחזיר ``undefined``, ולכן הכתיבה מאומתת בקריאה
  // חוזרת ולא בערך ההחזרה.
  const s = loadHandwriting('b2');
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
  // ``b`` הוא הקשר נפרד עם אחסון משלו; מה שנבדק הוא שהמפתחות שונים,
  // כלומר שני לוחות באותו דפדפן לא היו דורסים זה את זה.
  b.__api.writeHandwriting(false);
  eq([...a.__store.keys()][0] === [...b.__store.keys()][0], false, 'המפתחות שונים');
});

check('אחסון חסום אינו מפיל את הלוח', () => {
  // מצב פרטי או חסימת אחסון זורקים מ-``localStorage``. הלוח חייב להמשיך
  // לעבוד, בלי ההעדפה.
  const s = loadHandwriting('b3');
  s.localStorage.setItem = () => { throw new Error('blocked'); };
  s.localStorage.getItem = () => { throw new Error('blocked'); };
  s.__api.writeHandwriting(true);          // לא זורק
  eq(s.__api.readHandwriting(), false, 'נופל לברירת המחדל');
});

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
