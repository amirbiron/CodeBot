'use strict';
/**
 * בדיקות לחלוקה של טוקן הערה או מחרוזת לגוף ולשלד — ``hebrewTokenRanges`` ב-
 * ``webapp/static/js/utils/rtl-code.js``. הגוף של שורה עברית נעטף ב-``<span dir="rtl">``
 * (``isolateHebrewTokens``), וההזחה, סימני ההערה והשלד של המחרוזת נשארים בחוץ.
 *
 * הרצה:  node tests/rtl-code-tokens.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * **מה הבדיקות האלה כן מוכיחות:** איזה קטע מכל שורה של טוקן נבחר, לפי הטקסט של
 * הטוקן — כפי ש-highlight.js מייצר אותו (התחילית של ``f"…"`` בתוך הטוקן, טוקן אחד
 * על כמה שורות, טוקן לכל מילה בערך YAML; נבדק מול highlight.js 11.9.0 ו-11.11.1);
 * שהגוף לעולם אינו כולל סימן הערה, גרש או רווח בקצה; ושמילה בודדת, או גוף שהעברית
 * בו מתחת לסף, לא נבחרים.
 *
 * **ומה לא:** שהעטיפה נבנית נכון ב-DOM, ושהשורה באמת נקראת מימין לשמאל. ``vm`` אינו
 * דפדפן, ואין בריפו DOM לבדיקות Node. את זה מוכיחה ``tests/test_rtl_code_tokens_browser.py``.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'utils', 'rtl-code.js');

// הקובץ הוא script קלאסי שמגדיר ``window.RtlCode`` — ``package.json`` מוגדר
// ``"type": "module"``, ולכן ``require()`` עליו לא היה עובד.
function loadRtlCode() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox.window.RtlCode;
}

const R = loadRtlCode();

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(actual, expected, what) {
  const a = JSON.stringify(actual), b = JSON.stringify(expected);
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${b}, קיבלתי ${a}`);
}

/** הגופים שנבחרו, כטקסט — קריא יותר מהיסטים. */
function bodies(text, isString) {
  return R.hebrewTokenRanges(text, isString).map((r) => text.slice(r.start, r.end));
}
const comment = (text) => bodies(text, false);
const string = (text) => bodies(text, true);

// ---------- הערות ----------

check('הערת שורה: הסימן והרווח בחוץ, הגוף כולו בפנים', () => {
  eq(comment('// הצורה המינימלית של צומת hast שהתוסף צריך'), ['הצורה המינימלית של צומת hast שהתוסף צריך']);
  eq(comment('# requests חוסם, ולכן רץ ב-thread נפרד'), ['requests חוסם, ולכן רץ ב-thread נפרד']);
  eq(comment('-- שאילתה שמחזירה users פעילים'), ['שאילתה שמחזירה users פעילים']);
});

check('הערה עם סימן סגירה: גם הסוגר בחוץ', () => {
  eq(comment('<!-- הערה עם div בעברית -->'), ['הערה עם div בעברית']);
  eq(comment('/* צבע הרקע של body בעברית */'), ['צבע הרקע של body בעברית']);
  eq(comment('/** @param {string} name שם המשתמש בעברית */'), ['@param {string} name שם המשתמש בעברית']);
});

check('הערה על כמה שורות: כל שורה לחוד, עם ההזחה וה-* של ההמשך בחוץ', () => {
  // כך highlight.js מייצר את ``/* … */``: טוקן אחד, וההזחה של השורות שאחרי
  // הראשונה בתוכו.
  eq(comment('/* הערה ארוכה על ה-parser\n   * שורה שנייה עם hast בעברית\n   */'),
    ['הערה ארוכה על ה-parser', 'שורה שנייה עם hast בעברית']);
});

check('TODO: הגוף מתחיל ב-TODO, כמו שהוא נקרא', () => {
  // ב-highlight.js ``hljs-doctag`` מכיל גם את הרווח שלפני TODO; ההחלטה כאן היא
  // על הטקסט בלבד, ו-``isolateHebrewTokens`` מפצל את האלמנט בגבול.
  eq(comment('// TODO: לתקן את זה כשיהיה API חדש'), ['TODO: לתקן את זה כשיהיה API חדש']);
});

check('הקצוות: הגוף אינו מתחיל ואינו נגמר ברווח או בסימן', () => {
  const samples = ['  //   הערה עם רווחים   ', '#    הערה מוזחת בעברית', '/*   הערה בעברית   */', '<!--  הערה בעברית  -->'];
  samples.forEach((s) => {
    const [body] = comment(s);
    eq(body.trim(), body, `רווח בקצה: ${JSON.stringify(s)}`);
    eq(/^[/#*<!-]/.test(body) || /[/*>-]$/.test(body), false, `סימן בקצה: ${JSON.stringify(s)}`);
  });
});

// ---------- מחרוזות ----------

check('מחרוזת: הגרשיים בחוץ', () => {
  eq(string('"שלום עם PATH מעודכן"'), ['שלום עם PATH מעודכן']);
  eq(string("'שם עם id בעברית'"), ['שם עם id בעברית']);
  eq(string('`שלום ${name} ברוך הבא ל-CodeBot`'), ['שלום ${name} ברוך הבא ל-CodeBot']);
});

check('תחילית של מחרוזת היא חלק מהשלד, לא מהגוף', () => {
  // ב-highlight.js 11.9.0 ו-11.11.1 התחילית בתוך הטוקן. בתוך העטיפה ה-f
  // היה מצויר בקצה הימני, אחרי הגרש הסוגר.
  eq(string('f"✅ הקובץ {name} נשמר בהצלחה ב-MongoDB"'), ['✅ הקובץ {name} נשמר בהצלחה ב-MongoDB']);
  eq(string("rb'שלום עולם בעברית'"), ['שלום עולם בעברית']);
  eq(string('$@"שלום {name} עולם"'), ['שלום {name} עולם']);
  eq(string('u8"שלום עולם"'), ['שלום עולם']);
  eq(string('r#"שלום עולם"#'), ['שלום עולם']);
});

check('docstring: """ בחוץ, ושורות ההמשך בלי ההזחה', () => {
  eq(string('"""True אם ההודעה נשלחה בהצלחה ל-user\n    שורה שנייה של הסבר עם API\n    """'),
    ['True אם ההודעה נשלחה בהצלחה ל-user', 'שורה שנייה של הסבר עם API']);
  eq(string('"""\n    שורה ראשונה בעברית\n    ושנייה עם סוף."""'), ['שורה ראשונה בעברית', 'ושנייה עם סוף.']);
});

check('גרש בתחילת שורה באמצע מחרוזת רב-שורתית הוא תוכן', () => {
  // רק השורה הראשונה פותחת ורק האחרונה סוגרת.
  eq(string('"""פתיחה בעברית\n"ציטוט" אמר הוא בעברית\nסוף בעברית"""'),
    ['פתיחה בעברית', '"ציטוט" אמר הוא בעברית', 'סוף בעברית']);
});

check('סימני הערה בתוך מחרוזת נשארים בגוף', () => {
  eq(string('"# כותרת בעברית"'), ['# כותרת בעברית']);
  eq(string('"// לא הערה, מחרוזת"'), ['// לא הערה, מחרוזת']);
});

// ---------- מה לא נעטף ----------

check('מילה בודדת לא נעטפת', () => {
  // highlight.js צובע ערך YAML בלי גרשיים כטוקן לכל מילה. עטיפה של כל אחת לבד
  // הופכת את הסדר של מילים עבריות צמודות — ראו ``hebrewTokenRanges``.
  eq(string('ערך'), []);
  eq(string('"שלום"'), []);
  eq(comment('# הערה'), []);
});

check('גוף שהעברית בו מתחת לסף לא נעטף', () => {
  // ``isHebrewMajority`` — אותו סף כמו לבלוק שלם.
  eq(R.isHebrewMajority('the user ה-id'), false, 'בקרה: הקלט באמת מתחת לסף');
  eq(comment('// the user ה-id'), []);
});

check('בלי עברית — אין טווחים', () => {
  eq(comment('// plain english comment'), []);
  eq(string('"hello world"'), []);
  eq(comment(''), []);
  eq(string(''), []);
  eq(comment('/*\n */'), []);
});

// ---------- סימני הערה של שפות נוספות ----------

check('סימני הערה של ini, vbnet, erlang/matlab/latex ו-fortran נשארים בחוץ', () => {
  // הטוקן של highlight.js 11.11.1 פותח בסימן (``ini.js``, ``vbnet.js``, ``erlang.js``, ``fortran.js``).
  // בתוך העטיפה הסימן היה מצויר בקצה הימני של העברית.
  eq(comment('; הערה ארוכה על key בעברית'), ['הערה ארוכה על key בעברית']);
  eq(comment(';; הערה של lisp בעברית'), ['הערה של lisp בעברית']);
  eq(comment('% הערה עם x בעברית'), ['הערה עם x בעברית']);
  eq(comment('! הערה עם do בעברית'), ['הערה עם do בעברית']);
  eq(comment("' הערה עם Dim בעברית"), ['הערה עם Dim בעברית']);
});

check('REM של vbnet הוא סימן רק כשאחריו רווח, בלי הבחנה בין אותיות גדולות לקטנות', () => {
  // ``([\t ]|^)REM(?=\s)`` עם ``case_insensitive`` ב-``vbnet.js``.
  eq(comment('REM הערה עם Sub בעברית'), ['הערה עם Sub בעברית']);
  eq(comment('rem הערה עם Sub בעברית'), ['הערה עם Sub בעברית']);
  eq(comment('REMARK הערה עם Sub בעברית'), ['REMARK הערה עם Sub בעברית']);
});

check('מחרוזת raw של C++: התחילית, ה-tag והסוגריים בחוץ', () => {
  // ``(?:u8?|U|L)?R"([^()\\ ]{0,16})\(`` ב-``cpp.js``, והסגירה באותו tag.
  eq(string('R"-=(שלום עם id בעברית)-="'), ['שלום עם id בעברית']);
  eq(string('u8R"(שלום עולם בעברית)"'), ['שלום עולם בעברית']);
  eq(string('LR"[x(שורה ראשונה בעברית\nשורה שנייה בעברית)[x"'), ['שורה ראשונה בעברית', 'שורה שנייה בעברית']);
  // סוגר שאינו של אותו tag הוא תוכן ולא שלד.
  eq(string('R"ab(שלום עם x בעברית)cd"'), ['שלום עם x בעברית)cd"']);
});

// ---------- השוואה לביטוי של הבלוג ----------
//
// **החלוקה הסורקת חייבת לענות בדיוק כמו הביטוי שהחליפה**, על כל קלט שאינו פותח
// באחד מהסימנים שנוספו (``;``, ``%``, ``!``, ``'``, ``REM``) ואינו מחרוזת raw.
// ההיסטים, לא רק הגופים: גוף זהה במקום אחר היה עוטף טקסט אחר.

const BLOG_SPLIT = /^(\s*(?:\/\/+|#+|--|\/\*+|\*|<!--|"""|''')?\s*)([\s\S]*?)(\s*(?:\*\/|-->|"""|''')?\s*)$/;
const BLOG_STRING = /^(\s*)([\s\S]*?)(\s*)$/;
const OPEN = /^[A-Za-z0-9@$#]*(?:"""|'''|"|'|`)/;
const CLOSE = /(?:"""|'''|"|'|`)#*$/;

/** ``hebrewTokenRanges`` כפי שהייתה, עם הביטויים — האורקל. */
function blogRanges(text, isString) {
  const lines = text.split('\n');
  const out = [];
  let offset = 0;
  lines.forEach((line, i) => {
    const lineStart = offset;
    offset += line.length + 1;
    let lead = 0;
    let rest = line;
    if (isString) {
      if (i === 0) { const o = OPEN.exec(rest); if (o) { lead = o[0].length; rest = rest.slice(lead); } }
      if (i === lines.length - 1) { const c = CLOSE.exec(rest); if (c) rest = rest.slice(0, c.index); }
    }
    const m = (isString ? BLOG_STRING : BLOG_SPLIT).exec(rest);
    const body = m ? m[2] : '';
    if (!body || !/\s/.test(body) || !R.isHebrewMajority(body)) return;
    const start = lineStart + lead + m[1].length;
    out.push({ start, end: start + body.length });
  });
  return out;
}

check('על 30,000 טוקנים אקראיים — אותם טווחים כמו הביטוי של הבלוג', () => {
  // מחולל דטרמיניסטי (LCG), כדי שכשל יחזור על עצמו.
  let seed = 7;
  const rand = (n) => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed % n; };
  const pieces = [' ', '  ', '\t', '/', '//', '*', '/*', '*/', '#', '-', '--', '<!--', '-->', '"', '"""', "'''",
    '`', 'f', '$', 'x', 'id', 'שלום', 'עולם', 'בעברית', '\n'];
  // פותח באחד מהסימנים שנוספו — שם התשובה השתנתה בכוונה.
  const newOpener = /^\s*(?:[;%!']|REM\s)/i;
  let compared = 0, wrapped = 0;
  for (let n = 0; n < 30000; n++) {
    let text = '';
    const len = 1 + rand(10);
    for (let k = 0; k < len; k++) text += pieces[rand(pieces.length)];
    const isString = rand(2) === 1;
    if (text.split('\n').some((line) => newOpener.test(line))) continue;
    const got = R.hebrewTokenRanges(text, isString);
    const want = blogRanges(text, isString);
    if (JSON.stringify(got) !== JSON.stringify(want)) {
      throw new Error(`${JSON.stringify(text)} (${isString ? 'מחרוזת' : 'הערה'}): ${JSON.stringify(got)} ≠ ${JSON.stringify(want)}`);
    }
    compared += 1;
    if (want.length) wrapped += 1;
  }
  // בקרה: אילו המחולל לא ייצר כמעט גופים עבריים, ההשוואה הייתה עוברת בלי לבדוק כלום.
  eq(compared > 25000, true, `הושוו רק ${compared}`);
  eq(wrapped > 3000, true, `רק ${wrapped} טוקנים קיבלו טווח`);
});

// ---------- לינאריות ----------
//
// **זמן מול זמן, ולא תקרה בשניות** — אותה צורה כמו ב-``tests/rtl-code-inner-fences.test.js``:
// אותה עבודה על רבע מהקלט ועל כולו, הזמן הקצר ביותר משלושה סבבים, וזמן המעבד של התהליך.
// לינארי נותן פי 4 בערך; הביטוי שהוחלף נתן בהערה גידול בחזקה שלישית.

const GROWTH_LIMIT = 8;

/**
 * **שומר מהיר לפני מדידת הגידול.** על הביטוי שהוחלף, הקלטים של מדידת הגידול לוקחים דקות ארוכות, ולכן
 * בלי השומר רגרסיה הייתה **תוקעת** את הג'וב במקום להפיל אותו. קריאה אחת על 2,000 רווחים: בקוד ליניארי
 * היא מאיות של מילישנייה, ותקרה של שנייה רחוקה ממנה בכמה סדרי גודל.
 */
function quickGuard(text, isString) {
  const started = process.hrtime.bigint();
  R.hebrewTokenRanges(text, isString);
  const ms = Number(process.hrtime.bigint() - started) / 1e6;
  if (ms > 1000) throw new Error(`שורה של 2,000 רווחים לקחה ${ms.toFixed(0)}ms — הזמן אינו ליניארי`);
}

function growth(build, isString) {
  const inputs = [build(1), build(4)];
  const fastest = [Infinity, Infinity];
  for (let round = 0; round < 3; round++) {
    inputs.forEach((text, slot) => {
      const started = process.cpuUsage();
      for (let rep = 0; rep < 5; rep++) R.hebrewTokenRanges(text, isString);
      const used = process.cpuUsage(started);
      fastest[slot] = Math.min(fastest[slot], used.user + used.system);
    });
  }
  return fastest[1] / Math.max(fastest[0], 1);
}

check('הערה עם 20,000 רווחים באמצע — זמן ליניארי באורך הרצף, והגוף הנכון', () => {
  const build = (n) => '// הערה' + ' '.repeat(n) + 'עם hast בעברית */';
  quickGuard(build(2000), false);
  const g = growth((k) => build(5000 * k), false);
  eq(g < GROWTH_LIMIT, true, `הזמן גדל פי ${g.toFixed(1)} על קלט גדול פי 4`);
  eq(comment(build(20000)), ['הערה' + ' '.repeat(20000) + 'עם hast בעברית']);
});

check('מחרוזת עם 20,000 רווחים באמצע — זמן ליניארי באורך הרצף, והגוף הנכון', () => {
  const build = (n) => '"שלום' + ' '.repeat(n) + 'עולם בעברית"';
  quickGuard(build(2000), true);
  const g = growth((k) => build(5000 * k), true);
  eq(g < GROWTH_LIMIT, true, `הזמן גדל פי ${g.toFixed(1)} על קלט גדול פי 4`);
  eq(string(build(20000)), ['שלום' + ' '.repeat(20000) + 'עולם בעברית']);
});

check('ההיסטים מכוונים לטקסט של הטוקן כולו, גם אחרי ירידות שורה', () => {
  const text = '/*\n * שורה עם hast בעברית\n * עוד שורה בעברית\n */';
  const ranges = R.hebrewTokenRanges(text, false);
  eq(ranges.length, 2);
  ranges.forEach((r) => eq(text.slice(r.start, r.end).includes('\n'), false, 'טווח לא חוצה שורה'));
  eq(ranges[0].start, text.indexOf('שורה עם'));
  eq(ranges[1].end, text.indexOf('\n */'));
});

console.log(`rtl-code tokens: ${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
