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
