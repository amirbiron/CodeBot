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
// טעינת הגופן והחלת המחלקה עברו לתבנית משותפת, כי שלושת המשטחים
// שמארחים פתקים צורכים אותן. הבדיקה עוקבת אחרי הקוד: היא מריצה את
// שתי התבניות יחד, בדיוק כפי ש-``{% include %}`` מרכיב אותן בעמוד.
const SHARED = path.join(__dirname, '..', 'webapp', 'templates', '_note_fonts_head.html');
const SHARED_SRC = fs.readFileSync(SHARED, 'utf8');

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}

/** מחלץ את הסקריפט המוטבע מתוך תבנית כלשהי. */
function inlineScript(src, where) {
  const open = src.indexOf('<script>');
  const close = src.indexOf('</script>', open);
  if (open < 0 || close < 0) throw new Error(`לא נמצא סקריפט ב-${where}`);
  return src.slice(open + '<script>'.length, close);
}

/**
 * הסקריפטים שרצים בראש עמוד הלוח, **בסדר שבו הם רצים בדפדפן**:
 * קודם ההכללה המשותפת (שמגדירה את טעינת הגופן ואת החלת המחלקה), ואחריה
 * הבלוק המקומי של הלוח (שקורא את ההעדפה לכל לוח).
 *
 * ``fromSettings`` הוא מה שהשרת מזריק — ההגדרה הגלובלית של המשטח.
 */
function headScript(boardId, fromSettings = false) {
  const blockAt = SRC.indexOf('{% block extra_head %}');
  if (blockAt < 0) throw new Error('הבלוק extra_head לא נמצא בתבנית');
  const shared = inlineScript(SHARED_SRC, '_note_fonts_head.html')
    .replace(
      '{{ (note_fonts.get(note_font_surface) if note_fonts else False) | tojson }}',
      JSON.stringify(fromSettings),
    );
  const local = inlineScript(SRC.slice(blockAt), 'note_board.html extra_head')
    .replace('{{ board_id | tojson }}', JSON.stringify(boardId));
  return shared + '\n' + local;
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
function loadBoard(boardId, preset, fromSettings = false) {
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
      // המחלקה עברה מ-``<body>`` ל-``<html>``: הסקריפט רץ בפרסור ה-head,
      // ובשלב הזה ``document.body`` הוא ``null``.
      documentElement: { classList: {
        toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); },
      } },
    },
    __store: store,
    __classes: classes,
    __links: links,
  };
  vm.createContext(sandbox);
  sandbox.window = sandbox;               // בדפדפן ``window`` הוא הגלובל
  vm.runInContext(headScript(boardId, fromSettings), sandbox);
  return sandbox;
}

/**
 * מחלץ את חיווט המתג — הבלוק שמחליט אם המתג נעול.
 *
 * **למה בנפרד מ-``bodyScript``:** הוא יושב אחרי בלוק המארקדאון, ומריצים
 * אותו רק בבדיקות שבודקות את הנעילה עצמה.
 */
function toggleWiring() {
  const start = SRC.indexOf('const handwritingToggle');
  if (start < 0) throw new Error('חיווט המתג לא נמצא בתבנית');
  // העוגן הוא סוף ה-``else``, לא סוף ה-``if``: חיפוש התו הסוגר הראשון
  // היה חותך את הענף הלא-נעול ומייצר בדיקה שרצה על חצי מהקוד.
  const elseAt = SRC.indexOf('} else {', SRC.indexOf('if (handwritingLocked)', start));
  if (elseAt < 0) throw new Error('הענף הלא-נעול לא נמצא — העוגן השתנה');
  const end = SRC.indexOf('\n  }', elseAt);
  if (end < 0) throw new Error('סוף החיווט לא נמצא — העוגן השתנה');
  // ``readHandwriting`` ו-``applyHandwriting`` מוצהרות ב-``const`` בבלוק
  // הגוף, ולכן אינן נכנסות לאובייקט הגלובלי ואינן נראות להרצה נפרדת של
  // ``vm``. בדפדפן שני הבלוקים הם אותו סקריפט; כאן מחברים אותן מפורשות.
  // עטיפה ב-IIFE, ולא הצהרות ברמה העליונה: ``bodyScript`` כבר הצהיר את
  // אותם שמות ב-``const`` באותו הקשר, ו-``vm`` היה זורק על הכרזה כפולה.
  return '(function(){\n'
       + 'const readHandwriting = this.__api.readHandwriting,'
       + ' writeHandwriting = this.__api.writeHandwriting,'
       + ' applyHandwriting = this.__api.applyHandwriting;\n'
       + SRC.slice(start, end + 4)
       + '\n}).call(this);';
}

/** מריץ גם את בלוק הגוף וחושף את שלוש הפונקציות שלו. */
function loadHandwriting(boardId, preset, fromSettings = false) {
  const sandbox = loadBoard(boardId, preset, fromSettings);
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
  // ``sticky-handwriting`` ולא ``board-handwriting``: המראה זהה בשלושת
  // המשטחים, ושתי מחלקות עם אותם כללים היו נסחפות זו מזו.
  const s = loadHandwriting('b6');
  s.__api.applyHandwriting(true);
  eq(s.__classes.has('sticky-handwriting'), true, 'אחרי הדלקה');
  s.__api.applyHandwriting(false);
  eq(s.__classes.has('sticky-handwriting'), false, 'אחרי כיבוי');
});

// ─── ההגדרה הגלובלית ────────────────────────────────────────────────────

check('הגדרה גלובלית דלוקה מחילה את המחלקה בלי localStorage', () => {
  // המכשיר לא ביקר בלוח הזה מעולם, ואין לו ערך שמור. ההגדרה מהשרת
  // לבדה חייבת להספיק — אחרת "בכל המכשירים" לא היה עובד על מכשיר חדש.
  const s = loadBoard('b7', undefined, true);
  eq(s.__classes.has('sticky-handwriting'), true, 'המחלקה');
  eq(fontLinks(s).length, 1, 'הגופן נטען');
  eq(s.__store.size, 0, 'לא נכתב דבר ל-localStorage');
});

check('הגדרה גלובלית דלוקה אינה דורסת את ההעדפה המקומית', () => {
  // **הנקודה העדינה בנעילה.** ההעדפה של הלוח נשארת כפי שהיא, כדי
  // שכיבוי ההגדרה הגלובלית יחזיר בדיוק את מה שהיה — בכל הלוחות.
  const s = loadBoard('b8', '0', true);
  eq(s.__classes.has('sticky-handwriting'), true, 'המחלקה מוחלת למרות הכיבוי המקומי');
  eq(s.__store.get('board-handwriting:b8'), '0', 'הערך המקומי לא נגע');
});

check('הגדרה גלובלית כבויה — ההעדפה המקומית מכריעה', () => {
  const off = loadBoard('b9', '0', false);
  eq(off.__classes.has('sticky-handwriting'), false, 'מקומי כבוי');
  const on = loadBoard('b9', '1', false);
  eq(on.__classes.has('sticky-handwriting'), true, 'מקומי דלוק');
  eq(fontLinks(on).length, 1, 'הגופן נטען');
});

check('נעילה: הגדרה גלובלית דלוקה + מקומי כבוי — הגופן נשאר דלוק', () => {
  // **זה הצירוף המסוכן, והבדיקה שמצדיקה את ה-guard.** בלי הבדיקה על
  // ``handwritingLocked``, החיווט היה מריץ ``applyHandwriting(false)``
  // ו**מסיר** את המחלקה שההכללה כבר החילה — הגופן היה נכבה למרות
  // ההגדרה. אומת גם בדפדפן: המחלקה ירדה מ-``<html>``.
  const s = loadHandwriting('b10', '0', true);
  const el = { checked: false, disabled: false, addEventListener() {} };
  s.document.getElementById = (id) => (id === 'handwritingToggle' ? el : null);
  vm.runInContext(toggleWiring(), s);

  eq(s.__classes.has('sticky-handwriting'), true, 'המחלקה שרדה');
  eq(el.disabled, true, 'המתג נעול');
  eq(el.checked, true, 'המתג מסומן');
  eq(s.__store.get('board-handwriting:b10'), '0', 'הערך המקומי לא נדרס');
});

check('בלי נעילה — החיווט קורא את ההעדפה המקומית כרגיל', () => {
  const s = loadHandwriting('b11', '1', false);
  const el = { checked: false, disabled: false, addEventListener() {} };
  s.document.getElementById = (id) => (id === 'handwritingToggle' ? el : null);
  vm.runInContext(toggleWiring(), s);

  eq(el.disabled, false, 'המתג חופשי');
  eq(el.checked, true, 'נקרא מ-localStorage');
  eq(s.__classes.has('sticky-handwriting'), true, 'המחלקה');
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
