'use strict';
// בדיקות על **הגדרות הגופן של הלוח**: מתג כתב-היד וטעינת הגופן שלו,
// ובורר גודל הטקסט. שניהם חיים באותם שני בלוקים בתבנית ומוחלים דרך
// אותה הכללה משותפת, ולכן הם חולקים כאן הארנס אחד ולא שניים. ובסוף —
// הגלילה האינסופית, ההעדפה השכנה באותו מודאל, שנשענת על אותו הארנס.
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

// **ברירת המחדל של הגודל, כפי שהשרת מרנדר אותה.** ``_note_fonts_head.html`` מקבל אותה מ-
// ``NOTE_FONT_SIZE_DEFAULT`` ב-``webapp/app.py`` (דרך ``inject_globals``), ולכן המנשא קורא אותה
// משם ולא מעתיק אותה לכאן: עותק כאן היה ממשיך לבדוק את ברירת המחדל הישנה אחרי שהשרת שינה אותה.
// בדיקות שצריכות ברירת מחדל אחרת — כדי להראות שהלוח נגזר ממנה — מעבירות אותה במפורש.
const APP_SRC = fs.readFileSync(path.join(__dirname, '..', 'webapp', 'app.py'), 'utf8');
const SERVER_DEFAULT_MATCH = APP_SRC.match(/^NOTE_FONT_SIZE_DEFAULT = "([a-z]+)"$/m);
if (!SERVER_DEFAULT_MATCH) throw new Error('NOTE_FONT_SIZE_DEFAULT לא נמצא ב-webapp/app.py בצורה הצפויה');
const SERVER_DEFAULT = SERVER_DEFAULT_MATCH[1];

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
 *
 * ``between`` רץ בין שני הסקריפטים, כלומר אחרי שההכללה הגדירה את המפה
 * ואת התפריטים ולפני שהלוח קורא אותם. הוא קיים בשביל בדיקה אחת: המסנן
 * של הלוח מול התפריט שלו נבדק רק כשהמפה מכילה גודל שהלוח אינו מציע,
 * והתבנית עצמה אינה מייצרת מצב כזה כששני התפריטים זהים.
 *
 * ``defaultSize`` הוא מה שהשרת מרנדר ל-``STICKY_NOTE_FONT_SIZE_DEFAULT`` — כברירת מחדל, הערך
 * שבשרת עצמו (``SERVER_DEFAULT``).
 */
function headScript(boardId, fromSettings = false, between = '', defaultSize = SERVER_DEFAULT) {
  const blockAt = SRC.indexOf('{% block extra_head %}');
  if (blockAt < 0) throw new Error('הבלוק extra_head לא נמצא בתבנית');
  //
  // **``replaceAll`` ולא ``replace``.** ``replace`` עם מחרוזת מחליף רק
  // את המופע הראשון, ולכן ביטוי Jinja שני היה נשאר בקוד כטקסט ומפיל
  // את ההרצה בשגיאת תחביר שאינה מרמזת על הסיבה. זו מגבלה של המנשא
  // הזה בלבד — התבנית אינה אמורה להיכתב סביבה.
  const shared = inlineScript(SHARED_SRC, '_note_fonts_head.html')
    .replaceAll(
      '{{ (note_fonts.get(_handwriting_surface) if note_fonts else False) | tojson }}',
      JSON.stringify(fromSettings),
    )
    // גודל הטקסט שמגיע מעמוד ההגדרות מרונדר **ריק בלוחות** — התבנית
    // בודקת את המשטח — ולכן זה מה שהמנשא מציב. לוח מקבל את הגודל שלו
    // מהסקריפט המקומי, לא מכאן.
    .replaceAll(
      "{{ (note_font_size if (note_font_size and note_font_surface != 'board') else '') | tojson }}",
      JSON.stringify(''),
    )
    .replaceAll('{{ note_font_size_default | tojson }}', JSON.stringify(defaultSize));
  // **אף ביטוי Jinja לא נשאר.** ביטוי חדש בתבנית שהמנשא אינו מכיר היה נשאר בקוד כטקסט, וכל
  // הבדיקות היו נופלות בשגיאת תחביר שאינה אומרת מה חסר — כך בדיוק נראתה ההוספה של ברירת המחדל.
  if (shared.includes('{{')) {
    throw new Error('ביטוי Jinja שהמנשא אינו מחליף נשאר ב-_note_fonts_head.html: '
      + shared.slice(shared.indexOf('{{'), shared.indexOf('}}', shared.indexOf('{{')) + 2));
  }
  const local = inlineScript(SRC.slice(blockAt), 'note_board.html extra_head')
    .replaceAll('{{ board_id | tojson }}', JSON.stringify(boardId));
  return shared + '\n' + between + '\n' + local;
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
 *
 * ``opts.defaultSize`` — ברירת המחדל שהשרת מרנדר (ראו ``headScript``). ``opts.storageBlocked`` —
 * ``getItem`` ו-``setItem`` זורקים כבר בטעינת העמוד, כמו בדפדפן שחוסם אחסון.
 */
function loadBoard(boardId, preset, fromSettings = false, fontPreset = undefined, between = '', opts = {}) {
  const store = new Map();
  if (preset !== undefined) store.set('board-handwriting:' + boardId, preset);
  if (fontPreset !== undefined) store.set('board-font-size:' + boardId, fontPreset);
  const blocked = () => { throw new Error('blocked'); };

  const classes = new Set();
  const links = [];
  const byId = new Map();

  const sandbox = {
    localStorage: opts.storageBlocked
      ? { getItem: blocked, setItem: blocked, removeItem: blocked }
      : {
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
      // ``add``/``remove`` נוספו עבור ``applyStickyNoteFontSize``, שמנקה
      // את כל מחלקות הגודל ואז מוסיפה אחת. דמה שמכירה רק ``toggle``
      // הייתה זורקת, החריגה נבלעת ב-try/catch שבפונקציה, והבדיקה
      // "המחלקה הוחלה" הייתה נופלת מסיבה שנראית לא קשורה.
      documentElement: { classList: {
        toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); },
        add: (c) => { classes.add(c); },
        remove: (c) => { classes.delete(c); },
      } },
    },
    __store: store,
    __classes: classes,
    __links: links,
  };
  vm.createContext(sandbox);
  sandbox.window = sandbox;               // בדפדפן ``window`` הוא הגלובל
  vm.runInContext(headScript(boardId, fromSettings, between, opts.defaultSize), sandbox);
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

// ---------- גודל הטקסט בפתקי הלוח ----------
//
// **הבדיקה עוברת דרך אותו ממשק כמו הצרכן:** הבלוקים מחולצים מהתבנית
// ורצים כפי שהדפדפן מריץ אותם, ולא מהעתק שלהם. הבורר עצמו נגזר
// מה-HTML — ראו הבדיקה על התאמת האפשרויות למפה.

/** מחלץ את בלוק גודל הטקסט מגוף העמוד, לפי עוגנים ולא לפי שורות. */
function fontSizeBlock() {
  const start = SRC.indexOf('const NOTE_FONT_SIZE_KEY');
  if (start < 0) throw new Error('בלוק גודל הטקסט לא נמצא בתבנית');
  const end = SRC.indexOf('window._boardNotes = new', start);
  if (end < 0) throw new Error('סוף הבלוק לא נמצא — העוגן השתנה');
  return SRC.slice(start, end);
}

/** טוען לוח ומריץ את בלוק גודל הטקסט, ומחזיר גם את שתי הפונקציות ואת ברירת המחדל שהבלוק קרא. */
function loadFontSize(boardId, fontPreset, opts = {}) {
  const sandbox = loadBoard(boardId, undefined, false, fontPreset, '', opts);
  vm.runInContext(
    fontSizeBlock()
      + '\nthis.__api = { readNoteFontSize, writeNoteFontSize, NOTE_FONT_SIZE_DEFAULT };',
    sandbox,
  );
  return sandbox;
}

/** מחלקות הגודל שהוחלו על ``<html>``, לפי המפה המשותפת. */
function sizeClasses(sandbox) {
  const map = sandbox.window.STICKY_NOTE_FONT_SIZES;
  return [...sandbox.__classes].filter((c) => Object.values(map).includes(c));
}

/**
 * מחלקות הגודל הצפויות על ``<html>`` כשמוחל ``size``, בצורה של ``sizeClasses(...).join(',')``:
 * המחלקה שלו, או ``''`` ל-``normal``, שאינו מחלקה.
 */
function expectedClasses(sandbox, size) {
  return sandbox.window.STICKY_NOTE_FONT_SIZES[size];
}

check('גודל: ברירת המחדל של השרת היא "גדול מאוד"', () => {
  // **החלטת מוצר, נובמבר 2026.** הבדיקות שאחריה נגזרות מהערך שבשרת ולא מהמילה הזו, ולכן זו
  // הבדיקה היחידה שתיפול כשברירת המחדל תשתנה שוב — במכוון: היא הצד שאומר מה הוחלט.
  eq(SERVER_DEFAULT, 'xlarge', 'NOTE_FONT_SIZE_DEFAULT');
});

check('גודל: ברירת המחדל של השרת קיימת במפה ובתפריט הלוח', () => {
  // ברירת מחדל שאינה בתפריט הייתה מרוקנת את הבורר (``selectedIndex`` ‏-1), ושאינה במפה — לא
  // הייתה מחילה דבר, כלומר הלוח היה נשאר ב"רגיל" בזמן שהבורר מציג אחרת.
  const s = loadFontSize('bf0');
  eq(Object.prototype.hasOwnProperty.call(s.window.STICKY_NOTE_FONT_SIZES, SERVER_DEFAULT), true, 'במפה');
  eq(s.window.STICKY_NOTE_FONT_MENUS.board.indexOf(SERVER_DEFAULT) >= 0, true, 'בתפריט הלוח');
  eq(s.window.STICKY_NOTE_FONT_MENUS.settings.indexOf(SERVER_DEFAULT) >= 0, true, 'ובתפריט ההגדרות');
});

check('גודל: לוח בלי בחירה מקבל את ברירת המחדל של השרת, ושום מפתח לא נכתב', () => {
  const s = loadFontSize('bf1');
  eq(s.window.STICKY_NOTE_FONT_SIZE_DEFAULT, SERVER_DEFAULT, 'הערך שהוזרק');
  eq(sizeClasses(s).join(','), expectedClasses(s, SERVER_DEFAULT), 'המחלקה של ברירת המחדל');
  eq(s.__api.readNoteFontSize(), SERVER_DEFAULT, 'הקריאה מחזירה את ברירת המחדל');
  eq(s.__store.size, 0, 'ולא נכתב שום מפתח');
});

check('גודל: ברירת המחדל נגזרת ממה שהשרת הזריק, ולא כתובה בעמוד הלוח', () => {
  // **שלוש ברירות מחדל שונות, ובכל אחת — התצוגה, הקריאה והבורר הולכים אחריה.** עד נובמבר 2026
  // "רגיל" היה כתוב ביד בארבעה מקומות בעמוד הלוח; מקום אחד שנשכח מאחור היה נופל כאן לפחות
  // באחת משלוש, כי אף אחת מהן אינה תלויה בסדר האפשרויות או בערך מסוים.
  ['normal', 'large', 'xlarge'].forEach((injected) => {
    const { s, value } = selectedOnLoad('bf-inj-' + injected, undefined, { defaultSize: injected });
    eq(sizeClasses(s).join(','), expectedClasses(s, injected), 'התצוגה עם ' + injected);
    eq(s.__api.readNoteFontSize(), injected, 'הקריאה עם ' + injected);
    eq(value, injected, 'הבורר עם ' + injected);
  });
});

check('גודל: אחסון חסום כבר בטעינה — ברירת המחדל מוחלת, ולא "רגיל"', () => {
  // ``getItem`` שזורק בסקריפט הראש. לפני נובמבר 2026 הענף הזה השאיר את הלוח בלי מחלקה, וזה היה
  // נכון רק כי "בלי מחלקה" ו"ברירת המחדל" היו אותו דבר.
  const s = loadBoard('bf-blocked', undefined, false, undefined, '', { storageBlocked: true });
  eq(sizeClasses(s).join(','), expectedClasses(s, SERVER_DEFAULT), 'ברירת המחדל הוחלה');

  const other = loadBoard('bf-blocked-l', undefined, false, undefined, '',
    { storageBlocked: true, defaultSize: 'large' });
  eq(sizeClasses(other).join(','), 'sticky-font-large', 'וגם כשהשרת הזריק ברירת מחדל אחרת');
});

check('גודל: ערך שמור מוחל כבר בטעינת העמוד', () => {
  // **לפני הציור, לא ב-DOMContentLoaded.** החלה מאוחרת הייתה מציירת
  // את הפתקים בגודל הבסיס ("רגיל", בלי מחלקה) ואז מקפיצה אותם.
  const s = loadFontSize('bf2', 'large');
  eq(sizeClasses(s).join(','), 'sticky-font-large', 'המחלקה הוחלה בסקריפט הראש');
});

check('גודל: מעבר בין גדלים מסיר את הקודם', () => {
  // בלי הניקוי שתי המחלקות היו יושבות יחד על ``<html>``, ואז מנצח
  // הכלל שמופיע אחרון בקובץ — ולא זה שנבחר.
  const s = loadFontSize('bf3', 'xlarge');
  eq(sizeClasses(s).join(','), 'sticky-font-xlarge', 'התחלנו ב-xlarge');
  s.window.applyStickyNoteFontSize('large');
  eq(sizeClasses(s).join(','), 'sticky-font-large', 'ונשארה רק large');
  s.window.applyStickyNoteFontSize('normal');
  eq(sizeClasses(s).length, 0, 'ו-normal מנקה הכל');
});

check('גודל: ערך פגום באחסון נופל לברירת מחדל ואינו נכנס ל-classList', () => {
  // **``localStorage`` הוא קלט חיצוני.** ערך שנערך ביד, נשאר מגרסה
  // אחרת, או הוזרק — לא משנה. הרכבה ישירה של שם מחלקה מהערך
  // (``'sticky-font-' + size``) הייתה מכניסה כל מחרוזת ל-``classList``.
  // **בכל ערך — המחלקה של ברירת המחדל, והיא בלבד.** ``sticky-font-large`` ברשימה מראה שגם
  // שם של מחלקה אמיתית אינו נכנס דרך האחסון.
  ['evil', 'sticky-font-large', '', 'large xlarge', '__proto__', 'constructor', '99'].forEach((bad) => {
    const s = loadFontSize('bf4', bad);
    const want = expectedClasses(s, SERVER_DEFAULT);
    eq([...s.__classes].join(','), want, 'הערך ' + JSON.stringify(bad) + ': רק ברירת המחדל הוחלה');
  });
});

check('גודל: כל בחירה נשמרת — גם "רגיל" וגם ברירת המחדל עצמה', () => {
  // **עד נובמבר 2026 בחירה בברירת המחדל מחקה את המפתח**, כמו מתג המארקדאון. כשברירת המחדל
  // עברה מ"רגיל" ל"גדול מאוד" כל לוח שבחרו בו "רגיל" עבר איתה, כי לא נשאר ממנו דבר באחסון.
  // עכשיו מה שנבחר נשמר כמו שהוא, ושינוי עתידי של ברירת המחדל מגיע רק ללוחות שלא בחרו.
  const key = 'board-font-size:bf5';
  const s = loadFontSize('bf5');
  eq(s.__store.size, 0, 'התחלנו בלי מפתח');
  s.__api.writeNoteFontSize('normal');
  eq(s.__store.get(key), 'normal', '"רגיל" נשמר');
  s.__api.writeNoteFontSize(SERVER_DEFAULT);
  eq(s.__store.get(key), SERVER_DEFAULT, 'ברירת המחדל נשמרת גם היא, ואינה מוחקת את המפתח');

  // ובטעינה הבאה, עם ברירת מחדל אחרת בשרת — הבחירה גוברת.
  const next = loadFontSize('bf5n', 'normal', { defaultSize: 'large' });
  eq(sizeClasses(next).length, 0, '"רגיל" ששמור נשאר "רגיל"');
  eq(next.__api.readNoteFontSize(), 'normal', 'והקריאה מחזירה אותו');
});

check('גודל: לוחות אינם דולפים זה לזה', () => {
  const a = loadFontSize('bf-a', 'large');
  const b = loadFontSize('bf-b', undefined, { defaultSize: 'normal' });
  eq(sizeClasses(a).join(','), 'sticky-font-large', 'ללוח א יש גודל');
  eq(sizeClasses(b).length, 0, 'וללוח ב — בלי בחירה, וברירת מחדל "רגיל" — אין');
});

check('גודל: אחסון חסום אינו מפיל את הלוח', () => {
  const s = loadFontSize('bf6');
  s.localStorage.setItem = () => { throw new Error('blocked'); };
  s.localStorage.getItem = () => { throw new Error('blocked'); };
  s.__api.writeNoteFontSize('large');         // לא זורק
  eq(s.__api.readNoteFontSize(), SERVER_DEFAULT, 'נופל לברירת המחדל');
});

check('גודל: אפשרויות הבורר בתבנית זהות לתפריט הלוח', () => {
  // **הרשימה היא המקור, וה-HTML הוא העתק שלה.** זו הכפילות היחידה
  // שנשארה — משתמש צריך לראות שמות בעברית — ולכן היא נשמרת בבדיקה
  // ולא בהבטחה. גודל שיתווסף לתפריט בלי אפשרות בבורר, או להפך, מפיל כאן.
  //
  // **מול ``STICKY_NOTE_FONT_MENUS.board`` ולא מול המפה.** המפה יכולה
  // להיות גדולה מתפריט (כך היה עד אוקטובר 2026, כשעמוד ההגדרות הציע
  // גדלים משלו); השוואה אליה הייתה דורשת מהלוח להציע גם את מה ששייך
  // לתפריט אחר.
  const selectAt = SRC.indexOf('id="noteFontSizeSelect"');
  eq(selectAt > 0, true, 'הבורר קיים בתבנית');
  const end = SRC.indexOf('</select>', selectAt);
  const options = [...SRC.slice(selectAt, end).matchAll(/<option value="([^"]+)"/g)].map((m) => m[1]);
  const s = loadFontSize('bf7');
  eq(options.join(','), s.window.STICKY_NOTE_FONT_MENUS.board.join(','),
     'אותם טוקנים, ובאותו סדר');
});

check('גודל: כל טוקן בשני התפריטים קיים במפה', () => {
  // החצי השני של החוזה. בלעדיו תפריט יכול להציע גודל שאין לו מחלקה,
  // והבחירה פשוט לא הייתה עושה כלום — כשל שנראה כמו "לא נשמר".
  const s = loadFontSize('bf8');
  const map = s.window.STICKY_NOTE_FONT_SIZES;
  const menus = s.window.STICKY_NOTE_FONT_MENUS;
  Object.keys(menus).forEach((name) => {
    menus[name].forEach((token) => {
      eq(Object.prototype.hasOwnProperty.call(map, token), true,
         'הטוקן ' + token + ' מהתפריט ' + name + ' קיים במפה');
    });
  });
});

/**
 * מחלץ את הצבת הבורר שבמודאל — הקוד שמחליט איזו אפשרות מסומנת כשהעמוד
 * נטען — ומריץ אותו בהקשר של לוח שכבר נטען.
 *
 * **למה בנפרד מ-``fontSizeBlock``:** הוא יושב אחרי חיווט המודאלים, הרחק
 * מהקריאה והכתיבה. ``readNoteFontSize`` ו-``writeNoteFontSize`` מוצהרות
 * ב-``const`` בבלוק הגוף, ולכן מחוברות כאן מפורשות — באותה צורה כמו
 * ``toggleWiring``, ומאותה סיבה.
 */
function fontSizeSelectWiring() {
  const start = SRC.indexOf('const fontSizeSelect');
  if (start < 0) throw new Error('הצבת הבורר לא נמצאה בתבנית');
  const end = SRC.indexOf('const handwritingToggle', start);
  if (end < 0) throw new Error('סוף הצבת הבורר לא נמצא — העוגן השתנה');
  return '(function(){\n'
       + 'const readNoteFontSize = this.__api.readNoteFontSize,'
       + ' writeNoteFontSize = this.__api.writeNoteFontSize,'
       + ' NOTE_FONT_SIZE_DEFAULT = this.__api.NOTE_FONT_SIZE_DEFAULT;\n'
       + SRC.slice(start, end)
       + '\n}).call(this);';
}

/** הערך שהבורר מקבל בטעינת העמוד, כשבאחסון שמור ``fontPreset``. ``opts`` — כמו ב-``loadBoard``. */
function selectedOnLoad(boardId, fontPreset, opts = {}) {
  const s = loadFontSize(boardId, fontPreset, opts);
  const el = { value: '', addEventListener() {} };
  s.document.getElementById = (id) => (id === 'noteFontSizeSelect' ? el : null);
  vm.runInContext(fontSizeSelectWiring(), s);
  return { s, value: el.value };
}

check('גודל: גודל שקיים במפה אבל הלוח אינו מציע — אינו מוחל על הלוח', () => {
  // **המסנן של הלוח מול התפריט שלו, ולא רק מול המפה.** הצבה של ערך שאין
  // לו ``<option>`` מרוקנת את הבורר במקום ליפול לברירת המחדל, ולכן תצוגה
  // שמחילה אותו מציגה דבר אחד בזמן שהבורר מציג אחר.
  //
  // עד אוקטובר 2026 המצב הזה נוצר מעצמו: ``mid`` היה במפה ורק בתפריט של
  // עמוד ההגדרות. היום שני התפריטים זהים, ולכן הבדיקה יוצרת אותו בעצמה —
  // מוציאה ``large`` מהתפריט של הלוח אחרי שההכללה בנתה אותו. ריצת הבקרה
  // באותה בדיקה מראה שבלי ההוצאה אותו ערך **כן** מוחל, כלומר שההבדל הוא
  // המסנן ולא משהו אחר. ``large`` ולא ברירת המחדל: הערך שהוצא נופל לברירת
  // המחדל, ולכן הוצאה של ברירת המחדל עצמה הייתה מחילה בדיוק אותה מחלקה.
  const control = loadBoard('bf9', undefined, false, 'large');
  eq(sizeClasses(control).join(','), 'sticky-font-large', 'בקרה: בלי ההוצאה הגודל מוחל');

  const s = loadBoard('bf9', undefined, false, 'large',
    "window.STICKY_NOTE_FONT_MENUS.board = window.STICKY_NOTE_FONT_MENUS.board"
    + ".filter(function (t) { return t !== 'large'; });");
  eq(Object.prototype.hasOwnProperty.call(s.window.STICKY_NOTE_FONT_SIZES, 'large'), true,
     'large קיים במפה');
  eq(s.window.STICKY_NOTE_FONT_MENUS.board.indexOf('large'), -1, 'אבל לא בתפריט הלוח');
  eq(SERVER_DEFAULT !== 'large', true, 'תנאי לבדיקה: ברירת המחדל אינה הגודל שהוצא');
  eq(sizeClasses(s).join(','), expectedClasses(s, SERVER_DEFAULT),
     'ולכן הוחלה ברירת המחדל, ולא large');
});

check('גודל: בחירה מהסולם הקודם נופלת לברירת המחדל — בתצוגה ובבורר', () => {
  // **``lg`` ו-``xl`` יצאו משימוש באוקטובר 2026, ונשארו ב-``localStorage``
  // של לוחות קיימים.** אילו השם הישן היה חוזר עם גודל חדש, בחירה שמורה
  // הייתה מקבלת בשקט גודל אחר. כאן הם אינם מוכרים, ולכן הם מקבלים את
  // ברירת המחדל — בתצוגה ובבורר יחד, כי תצוגה בגודל אחד עם בורר ריק או
  // אחר היא בדיוק הסתירה שהמסנן נועד למנוע. ``mid`` היה רק בעמוד
  // ההגדרות ולא נשמר בלוח; הוא כאן כדי שגם הוא לא יחזור עם משמעות חדשה.
  ['lg', 'xl', 'mid'].forEach((old) => {
    const { s, value } = selectedOnLoad('bf-old-' + old, old);
    eq(sizeClasses(s).join(','), expectedClasses(s, SERVER_DEFAULT),
       'הערך הישן ' + old + ' לא הוחל, וברירת המחדל כן');
    eq(value, SERVER_DEFAULT, 'והבורר מציג את ברירת המחדל עבור ' + old);
  });
  // ובקרה: ערך שהלוח כן מציע מגיע לבורר כמו שהוא.
  eq(selectedOnLoad('bf-new', 'large').value, 'large', 'ערך מוכר מוצב כמו שהוא');
  eq(selectedOnLoad('bf-new-n', 'normal').value, 'normal', 'גם "רגיל", שאינו ברירת המחדל');
});

check('גודל: לכל מחלקה שבמפה יש כלל ב-CSS', () => {
  // **החצי שסוגר את המעגל.** התפריטים מוצלבים למפה, והמפה מוצלבת כאן
  // ל-CSS. בלי זה אפשר להוסיף גודל, לראות אותו בבורר, ולגלות שבחירה בו
  // פשוט לא עושה כלום — כי אין מחלקה שמגדירה את הטוקן.
  const css = fs.readFileSync(
    path.join(__dirname, '..', 'webapp', 'static', 'css', 'sticky-notes.css'), 'utf8');
  const decls = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const map = loadFontSize('bfc').window.STICKY_NOTE_FONT_SIZES;

  Object.keys(map).forEach((token) => {
    if (!map[token]) return;   // ``normal`` הוא היעדר מחלקה, לא מחלקה
    const rule = new RegExp(':root\\.' + map[token] + '\\s*\\{[^}]*--sticky-note-font\\s*:');
    eq(rule.test(decls), true, 'יש כלל ל-' + map[token]);
  });
});

check('גודל: ה-CSS קורא מהטוקן בשני הצרכנים, ואין מספר קשיח שנשאר מאחור', () => {
  const css = fs.readFileSync(
    path.join(__dirname, '..', 'webapp', 'static', 'css', 'sticky-notes.css'), 'utf8');
  const decls = css.replace(/\/\*[\s\S]*?\*\//g, '');
  // שני הצרכנים — תיבת העריכה והתצוגה — קוראים מאותו טוקן.
  eq((decls.match(/font-size:\s*var\(--sticky-note-font/g) || []).length, 2,
     'שני צרכנים קוראים מהטוקן');
  // ואף אחד מהם לא נשאר עם מספר קשיח, שהיה הופך את הטוקן לחסר השפעה.
  // כל מספר בפיקסלים, ולא ערך אחד מסוים: ברירת המחדל עצמה משתנה.
  eq(/\.sticky-note-(content|tasks)[^{]*\{[^}]*font-size:\s*[\d.]+px/.test(decls), false,
     'אין font-size קשיח שנשאר על אחד הצרכנים');
  // המחלקות עצמן, ובערכים מוחלטים: ``em`` כאן נפתר מול ההורה ולא מול
  // הבסיס — זו בדיוק התקלה שכבר תועדה בקובץ.
  const map = loadFontSize('bfpx').window.STICKY_NOTE_FONT_SIZES;
  Object.keys(map).forEach((token) => {
    if (!map[token]) return;
    const px = new RegExp(':root\\.' + map[token] + '\\s*\\{[^}]*--sticky-note-font:\\s*\\d+px');
    eq(px.test(decls), true, token + ' בפיקסלים');
  });
  eq(/--sticky-note-font:\s*[\d.]+em/.test(decls), false, 'ואין em על הבסיס');
});

check('גודל: הבסיס ("רגיל") מוצהר פעם אחת, על :root, ואין לו עותק ב-var()', () => {
  // **"רגיל" אינו ברירת המחדל של המשתמש** — זו ``NOTE_FONT_SIZE_DEFAULT`` בשרת, ומוחלת
  // כמחלקה. כאן מדובר בערך של הטוקן בלי שום מחלקה.
  // **עד אוקטובר 2026 הבסיס ישב כ-fallback בשני הצרכנים** —
  // ``var(--sticky-note-font, 14px)`` פעמיים, כלומר אותו מספר בשני מקומות.
  // שינוי של "רגיל" היה צריך לזכור את שניהם, ושום דבר לא אכף שיישארו
  // שווים. עכשיו יש הצהרה אחת על ``:root`` בלי מחלקה, והצרכנים קוראים
  // ``var()`` בלי fallback: עותק שם היה נראה כמו הבסיס בלי להיות הוא.
  const css = fs.readFileSync(
    path.join(__dirname, '..', 'webapp', 'static', 'css', 'sticky-notes.css'), 'utf8');
  const decls = css.replace(/\/\*[\s\S]*?\*\//g, '');
  // ``:root`` ואחריו ``{`` — לא ``:root.sticky-font-*``, שהן ההגדלות.
  const defaults = decls.match(/:root\s*\{[^}]*--sticky-note-font\s*:\s*\d+px/g) || [];
  eq(defaults.length, 1, 'הצהרת בסיס אחת בדיוק, על :root ובפיקסלים');
  eq(/var\(--sticky-note-font\s*,/.test(decls), false, 'אין fallback בתוך var()');
});

// ---------- גלילה אינסופית ----------
//
// **דלוקה כברירת מחדל מנובמבר 2026; עד אז כבויה.** הבלוק מחולץ מגוף העמוד ורץ מול אחסון מדומה,
// כמו בלוקי כתב היד והגודל. מה שנבדק: לוח שלא בחרו בו מקבל את ברירת המחדל, בחירה מפורשת — גם
// כיבוי — גוברת עליה, וערך שאינו בחירה אינו נקרא כבחירה.

/** מחלץ את בלוק הגלילה האינסופית מגוף העמוד, לפי עוגנים ולא לפי שורות. */
function infiniteBlock() {
  const start = SRC.indexOf('const INFINITE_KEY');
  if (start < 0) throw new Error('בלוק הגלילה האינסופית לא נמצא בתבנית');
  const end = SRC.indexOf('// גופן כתב-יד ללוח', start);
  if (end < 0) throw new Error('סוף הבלוק לא נמצא — העוגן השתנה');
  return SRC.slice(start, end);
}

/**
 * מריץ את הבלוק מול אחסון שבו שמור ``preset`` (או כלום), ומחזיר את שתי הפונקציות ואת האחסון.
 * ``blocked`` — ``getItem`` ו-``setItem`` זורקים, כמו בדפדפן שחוסם אחסון.
 */
function loadInfinite(boardId, preset, blocked = false) {
  const store = new Map();
  if (preset !== undefined) store.set('board-infinite:' + boardId, preset);
  const fail = () => { throw new Error('blocked'); };
  const sandbox = {
    BOARD_ID: boardId,
    localStorage: blocked
      ? { getItem: fail, setItem: fail, removeItem: fail }
      : {
        getItem: (k) => (store.has(k) ? store.get(k) : null),
        setItem: (k, v) => { store.set(k, String(v)); },
        removeItem: (k) => { store.delete(k); },
      },
    __store: store,
  };
  vm.createContext(sandbox);
  vm.runInContext(infiniteBlock() + '\nthis.__api = { readInfinite, writeInfinite };', sandbox);
  return sandbox;
}

check('גלילה: לוח שלא בחרו בו — דלוקה, והקריאה אינה כותבת מפתח', () => {
  const s = loadInfinite('bi1');
  eq(s.__api.readInfinite(), true, 'ברירת המחדל דלוקה');
  eq(s.__store.size, 0, 'ולא נכתב שום מפתח');
});

check('גלילה: בחירה מפורשת גוברת על ברירת המחדל — גם כיבוי', () => {
  // **זה מה שמגן על מי שכיבה.** שני המצבים נשמרו תמיד במפורש, ולכן לוח שכיבו בו לפני השינוי
  // נשאר כבוי, ורק לוח שלא בחרו בו כלום עבר לדלוקה.
  eq(loadInfinite('bi2', '0').__api.readInfinite(), false, '"0" נשאר כבוי');
  eq(loadInfinite('bi3', '1').__api.readInfinite(), true, '"1" נשאר דלוק');
});

check('גלילה: ערך שאינו בחירה מקבל את ברירת המחדל', () => {
  // ``localStorage`` הוא קלט חיצוני. עד נובמבר 2026 כל מה שאינו ``'1'`` נקרא "כבוי", כלומר
  // ערך פגום היה נראה כמו בחירה; עכשיו רק ``'1'`` ו-``'0'`` הם בחירות.
  ['true', 'false', 'yes', '', '2', ' 1', '__proto__'].forEach((bad) => {
    eq(loadInfinite('bi4', bad).__api.readInfinite(), true, 'הערך ' + JSON.stringify(bad));
  });
});

check('גלילה: שני המצבים נכתבים במפורש', () => {
  // כיבוי שהיה נשמר כהיעדר מפתח היה נקרא עכשיו כ"לא בחרו", כלומר דלוק.
  const s = loadInfinite('bi5');
  s.__api.writeInfinite(false);
  eq(s.__store.get('board-infinite:bi5'), '0', 'כיבוי נשמר כ-"0"');
  eq(s.__api.readInfinite(), false, 'ונקרא בחזרה ככבוי');
  s.__api.writeInfinite(true);
  eq(s.__store.get('board-infinite:bi5'), '1', 'הדלקה נשמרת כ-"1"');
});

check('גלילה: אחסון חסום — ברירת המחדל, בלי לזרוק', () => {
  const s = loadInfinite('bi6', undefined, true);
  eq(s.__api.readInfinite(), true, 'דלוקה');
  s.__api.writeInfinite(false);                // לא זורק
});

check('גלילה: המנהל והמתג במודאל קוראים את אותה הכרעה', () => {
  // ``readInfinite`` היא המקום היחיד שמכריע; שני הצרכנים שלה בעמוד — האופציה שהמנהל נבנה איתה
  // והמצב ההתחלתי של המתג — קוראים לה, ולא בודקים את האחסון בעצמם. צרכן שהיה קורא
  // ``getItem(...) === '1'`` ישירות היה מחזיר את ברירת המחדל הישנה לאחד מהם בלבד.
  eq(/infiniteScroll:\s*readInfinite\(\)/.test(SRC), true, 'המנהל נבנה עם readInfinite()');
  eq(/infiniteToggle\.checked\s*=\s*readInfinite\(\)/.test(SRC), true, 'המתג מוצב לפי readInfinite()');
  eq((SRC.match(/INFINITE_KEY/g) || []).length, 3, 'המפתח נקרא רק בבלוק עצמו: הגדרה, קריאה וכתיבה');
});

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
