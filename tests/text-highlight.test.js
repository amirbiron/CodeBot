'use strict';
/**
 * בדיקות ל-``webapp/static/js/utils/text-highlight.js`` — הליבה המשותפת של
 * הדגשת התאמות חיפוש.
 *
 * הרצה:  node tests/text-highlight.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * הקובץ הנבדק נטען כמו בדפדפן — script קלאסי שמגדיר ``window.TextHighlight``.
 *
 * **מה הבדיקות האלה כן מוכיחות:** את כללי ההתאמה (ליטרלי, בלי רישיות, בלי
 * נרמול ניקוד), שהפיצול אינו מאבד ואינו ממציא תווים, ושהבנייה מטקסט יוצרת
 * רק צמתי טקסט ועטיפות.
 *
 * **ומה לא:** את המעבר על תצוגה קיימת (``highlightWithin``) ואת הניקוי
 * (``clearHighlights``). שם השאלות הן של הדפדפן — איך ``TreeWalker`` מדלג
 * על תת-עץ, מה ``matches('svg')`` מחזיר לאלמנט SVG, ומה ``normalize`` עושה —
 * ודמות שנכתבה ביד הייתה עונה עליהן לפי מה שכותב הדמות חושב. את זה מוכיחה
 * ``tests/test_text_highlight_browser.py`` בכרומיום אמיתי.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(
  __dirname, '..', 'webapp', 'static', 'js', 'utils', 'text-highlight.js');

// ---------------------------------------------------------------------------
// DOM זעיר — רק מה ש-``appendHighlighted`` נוגע בו: ``createElement``,
// ``createTextNode``, ``appendChild`` ו-``textContent``. אין כאן
// ``innerHTML`` בכלל, ולכן אילו הפונקציה הייתה משרשרת HTML, הבדיקה הייתה
// נופלת ולא עוברת בטעות.
// ---------------------------------------------------------------------------

class FakeNode {
  constructor(tag) { this.tagName = tag; this.children = []; this.className = ''; }
  appendChild(c) { this.children.push(c); return c; }
  set textContent(v) { this.children = [{ tagName: '#text', text: String(v) }]; }
  get textContent() {
    return this.children.map((c) => (c.tagName === '#text' ? c.text : c.textContent)).join('');
  }
}

const fakeDocument = {
  createElement: (tag) => new FakeNode(String(tag).toUpperCase()),
  createTextNode: (text) => ({ tagName: '#text', text: String(text) }),
};

function loadModule() {
  const sandbox = { window: {}, document: fakeDocument };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox.window.TextHighlight;
}

const TextHighlight = loadModule();
const { splitMatches, escapeRegExp, appendHighlighted, clearHighlights, highlightWithin } = TextHighlight;

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(actual, expected, what) {
  const a = JSON.stringify(actual), b = JSON.stringify(expected);
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${b}, קיבלתי ${a}`);
}
function throwsType(fn, what) {
  try { fn(); } catch (e) {
    if (e && e.name === 'TypeError') return;
    throw new Error(`${what || ''} — נזרקה ${e && e.name} ולא TypeError`);
  }
  throw new Error(`${what || ''} — לא נזרקה שגיאה`);
}

/** הקטעים בצורה קצרה: ``[טקסט, האם התאמה]``. */
function parts(text, term) {
  return splitMatches(text, term).map((p) => [p.text, p.hit]);
}
function hitCount(text, term) {
  return splitMatches(text, term).filter((p) => p.hit).length;
}

// ── הליבה: splitMatches ────────────────────────────────────────────────────

check('כל מופע מסומן, והטקסט שביניהם נשאר רגיל', () => {
  eq(parts('פתק ועוד פתק ושוב פתק', 'פתק'),
     [['פתק', true], [' ועוד ', false], ['פתק', true], [' ושוב ', false], ['פתק', true]],
     'שלושה מופעים ושני קטעי ביניים');
});

check('חיבור הקטעים מחזיר את הטקסט המקורי תו בתו', () => {
  // זו ההבטחה שכל צרכן נשען עליה: ההדגשה עוטפת, ואינה מוחקת או מוסיפה.
  [
    ['פתק ועוד פתק', 'פתק'],
    ['Config ו-CONFIG', 'config'],
    ['aaaa', 'aa'],
    ['אין כאן כלום', 'מיגרציה'],
    ['<b>&amp;</b>', '&'],
    ['שורה\nשנייה\tעם טאב', '\n'],
  ].forEach(([text, term]) => {
    eq(splitMatches(text, term).map((p) => p.text).join(''), text, `הטקסט ${JSON.stringify(text)}`);
  });
});

check('לא רגיש לרישיות, והתאמה שומרת את הרישיות שבטקסט', () => {
  // כמו ``$options: "i"`` של ``note_search_filter`` בשרת.
  const hits = splitMatches('Config ו-CONFIG ו-config', 'config').filter((p) => p.hit).map((p) => p.text);
  eq(hits, ['Config', 'CONFIG', 'config'], 'שלושתם, כל אחד כפי שנכתב');
});

check('תווי רג\'קס במחט הם ליטרליים', () => {
  // בלי בריחה, ``config.py`` היה מדגיש גם ``configXpy`` — הדגשה על טקסט
  // שהחיפוש בשרת לא התאים.
  eq(hitCount('ראו config.py', 'config.py'), 1, 'הליטרל נתפס');
  eq(hitCount('ראו configXpy', 'config.py'), 0, 'והנקודה אינה תו כללי');
  eq(hitCount('הביטוי a( נשבר', 'a('), 1, 'סוגר פתוח אינו מפיל');
  eq(hitCount('a+b', 'a+b'), 1, 'פלוס הוא פלוס');
  eq(hitCount('[x] ו-x', '[x]'), 1, 'סוגריים מרובעים הם תווים, לא קבוצה');
  eq(hitCount('\\d ו-7', '\\d'), 1, 'לוכסן הפוך הוא תו, לא ספרה');
  eq(hitCount('$^ ו-', '$^'), 1, 'עוגנים הם תווים');
});

check('בלי נרמול ניקוד — אותו כלל כמו החיפוש בשרת', () => {
  // ההחלטה מתועדת בסעיף "חיפוש בפתקים" במסמך הפיתוח: נרמול בצד אחד בלבד
  // היה יוצר בדיוק את הפער בין "נמצא בחיפוש" לבין "מודגש בתוכו".
  eq(hitCount('שָׁלוֹם', 'שלום'), 0, 'מחט בלי ניקוד אינה תופסת טקסט מנוקד');
  eq(hitCount('שָׁלוֹם', 'שָׁלוֹם'), 1, 'אבל אותו טקסט בדיוק נתפס');
});

check('מופעים סמוכים אינם חופפים', () => {
  eq(parts('aaaa', 'aa'), [['aa', true], ['aa', true]], 'שני מופעים, בלי קטע ריק ביניהם');
  eq(parts('aaa', 'aa'), [['aa', true], ['a', false]], 'והשארית נשארת רגילה');
});

check('מופע בתחילת המחרוזת ובסופה — בלי קטע ריק', () => {
  eq(parts('פתק באמצע פתק', 'פתק'), [['פתק', true], [' באמצע ', false], ['פתק', true]], 'שלושה קטעים');
});

check('מחט ריקה אינה מסמנת, וטקסט ריק אינו מייצר קטעים', () => {
  eq(parts('טקסט כלשהו', ''), [['טקסט כלשהו', false]], 'מחט ריקה');
  eq(parts('טקסט כלשהו', null), [['טקסט כלשהו', false]], 'מחט null');
  eq(parts('', 'x'), [], 'טקסט ריק');
  eq(parts(null, 'x'), [], 'טקסט null');
  eq(parts(undefined, undefined), [], 'שניהם חסרים');
});

check('ערך שאינו מחרוזת הופך למחרוזת ואינו מפיל', () => {
  // ``notes_search.js`` מעביר ערכים שהגיעו ב-JSON מהשרת.
  eq(parts(12345, 34), [['12', false], ['34', true], ['5', false]], 'מספר');
});

check('escapeRegExp: כל תו מיוחד מתאים רק לעצמו', () => {
  '.*+?^${}()|[]\\'.split('').forEach((ch) => {
    const re = new RegExp(escapeRegExp(ch));
    eq(re.test(ch), true, `${JSON.stringify(ch)} מתאים לעצמו`);
    eq(re.test('x'), false, `${JSON.stringify(ch)} אינו מתאים ל-x`);
  });
});

// ── בנייה מטקסט: appendHighlighted ─────────────────────────────────────────

function build(text, term, opts) {
  const box = new FakeNode('SPAN');
  const hits = appendHighlighted(box, text, term, opts || { className: 'notes-search-mark' });
  return { hits, box, tags: box.children.map((c) => c.tagName) };
}

check('appendHighlighted: מחזיר את מספר המופעים, ועוטף ב-mark כברירת מחדל', () => {
  const r = build('פתק ועוד פתק', 'פתק');
  eq(r.hits, 2, 'שני מופעים');
  eq(r.tags, ['MARK', '#text', 'MARK'], 'עטיפה, טקסט, עטיפה');
  eq(r.box.children.filter((c) => c.tagName === 'MARK').map((c) => c.className),
     ['notes-search-mark', 'notes-search-mark'], 'המחלקה שהתבקשה');
  eq(r.box.textContent, 'פתק ועוד פתק', 'הטקסט שלם');
});

check('appendHighlighted: תגית אחרת לפי בקשה', () => {
  const r = build('abc', 'b', { tagName: 'span', className: 'hit' });
  eq(r.tags, ['#text', 'SPAN', '#text'], 'span במקום mark');
});

check('appendHighlighted: HTML בתוכן נשאר טקסט', () => {
  // הצומת היחיד שנוצר הוא העטיפה שלנו. כל השאר צמתי טקסט — ולכן
  // ``<img onerror=…>`` אינו יכול לרוץ. זה ``bugbot-rules/xss-innerhtml``.
  const payload = '<img src=x onerror="alert(1)"> מיגרציה "ציטוט" & עוד';
  const r = build(payload, 'מיגרציה');
  eq(r.tags.filter((t) => t !== '#text' && t !== 'MARK').length, 0, 'לא נוצר שום אלמנט זר');
  eq(r.box.textContent, payload, 'כולל המרכאות והאמפרסנד, בדיוק כפי שהגיעו');
});

check('appendHighlighted: אפס מופעים — הטקסט מוצג, והספירה אפס', () => {
  const r = build('תצוגה מקדימה', 'מיגרציה');
  eq(r.hits, 0, 'אפס');
  eq(r.tags, ['#text'], 'צומת טקסט אחד');
  eq(r.box.textContent, 'תצוגה מקדימה', 'והטקסט שלם');
});

// ── שם המחלקה הוא חובה, ונבדק לפני שנוגעים ב-DOM ──────────────────────────

check('בלי שם מחלקה תקין — TypeError, ולא עטיפה שאי אפשר לנקות', () => {
  // עטיפה בלי מחלקה, או עם מחלקה שאינה סלקטור פשוט, היא עטיפה ש-
  // ``clearHighlights`` לא ימצא — כלומר הדגשה שנשארת לתמיד.
  throwsType(() => appendHighlighted(new FakeNode('SPAN'), 'a', 'a', {}), 'בלי className');
  throwsType(() => appendHighlighted(new FakeNode('SPAN'), 'a', 'a'), 'בלי אפשרויות בכלל');
  throwsType(() => appendHighlighted(new FakeNode('SPAN'), 'a', 'a', { className: 'a b' }), 'שתי מחלקות');
  throwsType(() => appendHighlighted(new FakeNode('SPAN'), 'a', 'a', { className: '.x' }), 'נקודה בשם');
  // השורש כאן זורק ``Error`` רגיל בכל נגיעה בו. כך ``TypeError`` מוכיח
  // שהבדיקה קדמה לכל גישה לשורש — ולא ששורש ריק הפיל את הקריאה.
  const untouchable = { querySelectorAll() { throw new Error('נגעו בשורש לפני הבדיקה'); } };
  throwsType(() => clearHighlights(untouchable, 'x y'), 'clearHighlights');
  throwsType(() => highlightWithin(untouchable, 'x', { className: '' }), 'highlightWithin');
});

// ── חיווט: כל תבנית שמשתמשת במודול טוענת אותו ─────────────────────────────

/** כל הקבצים תחת ``dir`` (רקורסיבי). */
function walk(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory() ? walk(path.join(dir, e.name)) : [path.join(dir, e.name)]);
}

check('חיווט: כל תבנית שמשתמשת במודול טוענת אותו עם ?v=, בלי defer, ולפני השימוש', () => {
  // **הצרכנים נגזרים מהקוד, ולא נמנים כאן.** כל קובץ JS שקורא
  // ``window.TextHighlight`` הוא צרכן, וכל תבנית שטוענת צרכן — או שקוראת
  // למודול בסקריפט אינליין — חייבת לטעון את המודול לפניו. רשימה ידנית
  // הייתה מתיישנת ברגע שנוסף צרכן חמישי; הגזירה תופסת אותו מאליו.
  //
  // בלי התג ההדגשה נעלמת מהעמוד **בשקט**: כל צרכן מטפל בהיעדר המודול
  // כהיעדר יכולת (תיבה מושבתת, טקסט בלי הדגשה), ולכן אין שגיאה שתצעק.
  const jsRoot = path.join(__dirname, '..', 'webapp', 'static', 'js');
  const consumers = walk(jsRoot)
    .filter((f) => f.endsWith('.js') && !f.endsWith('.bundle.js') && f !== MODULE_PATH)
    .filter((f) => fs.readFileSync(f, 'utf8').includes('window.TextHighlight'))
    .map((f) => "filename='js/" + path.relative(jsRoot, f).split(path.sep).join('/') + "'");
  eq(consumers.length >= 1, true, 'נמצאו קובצי JS שצורכים את המודול');

  const MODULE_REF = "filename='js/utils/text-highlight.js'";
  const tplRoot = path.join(__dirname, '..', 'webapp', 'templates');
  let hosts = 0;
  walk(tplRoot).filter((f) => f.endsWith('.html')).forEach((f) => {
    const src = fs.readFileSync(f, 'utf8');
    const uses = consumers.map((c) => src.indexOf(c)).filter((i) => i !== -1);
    const inline = src.indexOf('window.TextHighlight');
    if (inline !== -1) uses.push(inline);
    if (!uses.length) return;
    hosts += 1;
    const name = path.relative(tplRoot, f);
    const mod = src.indexOf(MODULE_REF);
    eq(mod !== -1, true, name + ' טוען את המודול');
    eq(mod < Math.min(...uses), true, name + ' טוען אותו לפני השימוש הראשון');
    const tag = new RegExp("<script[^>]*" + escapeRegExp(MODULE_REF) + "[^>]*>").exec(src);
    eq(/\?v=\{\{\s*static_version\s*\}\}/.test(tag ? tag[0] : ''), true, name + ' עם ?v=static_version');
    // מיקום בקובץ שווה לסדר הרצה רק כשהמודול אינו דחוי: סקריפט דחוי רץ
    // אחרי הניתוח, ולכן אחרי כל סקריפט רגיל שבא אחריו בקובץ.
    eq(/\bdefer\b/.test(tag ? tag[0] : ''), false, name + ' בלי defer');
  });
  eq(hosts >= 2, true, 'נמצאו תבניות שמשתמשות במודול (' + hosts + ')');
});

check('הממשק קפוא', () => {
  // בלי הקפאה כל סקריפט בעמוד היה יכול להחליף את ``splitMatches`` ולשנות
  // בכך את ההדגשה בשלושת הצרכנים יחד.
  eq(Object.isFrozen(TextHighlight), true, 'Object.isFrozen');
});

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
