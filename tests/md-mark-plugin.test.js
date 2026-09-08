/**
 * טסטים ל-webapp/static/js/md-mark-plugin.js — התוסף שהופך ``==טקסט==`` ל-``<mark>``.
 *
 * הרצה:  node tests/md-mark-plugin.test.js
 * (קובץ עצמאי שמריץ את הבדיקות בעצמו ויוצא בקוד 1 בכישלון — זו דרישה של ה-CI:
 *  ``.github/workflows/ci.yml`` רץ בלולאה על ``tests/*.test.js`` עם ``node "$f"``,
 *  וקובץ בסגנון describe/it נספר שם ככשל ולא כדילוג.)
 *
 * **מה הטסט הזה שומר עליו.** התוסף היה כתוב ביד ועשה ``state.md.inline.parse`` מקונן
 * מתוך כלל inline. הקריאה הזו מריצה את שלבי הסיום על מערך הטוקנים המשותף ומקצרת אותו,
 * ולכן כל מסמך עם ``**מודגש**`` ואחריו ``==מארקר==`` באותה פסקה זרק חריגה — והמשתמש
 * ראה "שגיאה ברינדור Markdown" בלי סיבה. בארבעה מקרים נוספים הוא לא זרק כלום אלא
 * **השמיד תוכן בשקט**, וזה הרבה יותר מסוכן מקריסה.
 *
 * **החוזה שנבדק כאן הוא התנהגות, לא מימוש:** הפלט המדויק, ולא "לא קרס".
 *
 * הקובץ הנבדק נטען כמו בדפדפן — script קלאסי שמגדיר ``window.MdMarkPlugin`` — כי
 * ``package.json`` מוגדר ``"type": "module"`` ולכן ``require()`` רגיל לא היה עובד עליו.
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';
import MarkdownIt from 'markdown-it';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'md-mark-plugin.js');

// אותן אופציות בדיוק כמו בשני אתרי הקריאה (md_preview.html ו-live-preview.js).
// אם הן יסטו שם, הטסט יבדוק תצורה שאף אחד לא מריץ.
const RENDER_OPTIONS = { breaks: true, linkify: true, typographer: true, html: false };

function loadPlugin() {
  const code = fs.readFileSync(MODULE_PATH, 'utf8');
  // סנדבוקס טרי לכל טעינה, בלי state משותף בין בדיקות.
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return sandbox.window.MdMarkPlugin;
}

/**
 * התוסף **הישן והשבור**, מועתק מילה במילה מ-``live-preview.js`` שלפני התיקון
 * (הוא היה זהה תו-בתו גם ב-``md_preview.html``). הוא קיים כאן רק כדי להוכיח
 * שהבדיקות למטה מסוגלות להיכשל — בדיקה שלא נופלת על הקוד הישן אינה בודקת כלום.
 */
function brokenPlugin(mdInstance) {
  function isSpace(code) { return code === 0x20 || code === 0x0A || code === 0x09; }
  function isEscaped(src, pos) {
    let backslashes = 0;
    let i = pos - 1;
    while (i >= 0 && src.charCodeAt(i) === 0x5C) { backslashes += 1; i -= 1; }
    return (backslashes % 2) === 1;
  }
  function tokenize(state, silent) {
    const start = state.pos;
    const max = state.posMax;
    const src = state.src;
    if (start + 4 > max) return false;
    if (src.charCodeAt(start) !== 0x3D || src.charCodeAt(start + 1) !== 0x3D) return false;
    const next = src.charCodeAt(start + 2);
    if (isSpace(next)) return false;
    let end = start + 2;
    while (true) {
      end = src.indexOf('==', end);
      if (end < 0 || end + 2 > max) return false;
      if (end === start + 2) { end += 2; continue; }
      if (isSpace(src.charCodeAt(end - 1))) { end += 2; continue; }
      if (isEscaped(src, end)) { end += 2; continue; }
      break;
    }
    if (silent) return true;
    const open = state.push('mark_open', 'mark', 1);
    open.markup = '==';
    const inner = src.slice(start + 2, end);
    state.md.inline.parse(inner, state.md, state.env, state.tokens);
    const close = state.push('mark_close', 'mark', -1);
    close.markup = '==';
    state.pos = end + 2;
    return true;
  }
  mdInstance.inline.ruler.before('emphasis', 'mark', tokenize);
}

function render(plugin, src) {
  const md = new MarkdownIt(RENDER_OPTIONS).use(plugin);
  return md.render(src).trim();
}

let passed = 0;
let failed = 0;

function check(name, fn) {
  try { fn(); passed += 1; console.log('  ✅', name); }
  catch (e) { failed += 1; console.log('  ❌', name, '\n     ', e.message); }
}

function eq(actual, expected, label) {
  if (actual !== expected) {
    throw new Error(`${label}\n      ציפיתי: ${expected}\n      קיבלתי: ${actual}`);
  }
}

// ---------------------------------------------------------------------------
// החוזה: קלט ← פלט מדויק. אותה רשימה בדיוק מורצת אחר כך על התוסף הישן.
// ---------------------------------------------------------------------------

/** מקרים שקרסו לגמרי בתוסף הישן — כל אחד מהם הפיל את **כל** העמוד. */
const CRASHED = [
  ['מודגש ואז מארקר', '**abc** then ==def==', '<p><strong>abc</strong> then <mark>def</mark></p>'],
  ['המחרוזת מהדיווח', "**Let's** give it a==shot==", '<p><strong>Let’s</strong> give it a<mark>shot</mark></p>'],
  ['עברית', '**מודגש** ואז ==מארקר==', '<p><strong>מודגש</strong> ואז <mark>מארקר</mark></p>'],
  ['מודגש ומארקר לסירוגין', '**a** ==b== **c** ==d==',
    '<p><strong>a</strong> <mark>b</mark> <strong>c</strong> <mark>d</mark></p>'],
  ['בתוך כותרת', '## **כותרת** עם ==מארקר==', '<h2><strong>כותרת</strong> עם <mark>מארקר</mark></h2>'],
  ['בתוך פריט רשימה', '- **פריט** עם ==מארקר==',
    '<ul>\n<li><strong>פריט</strong> עם <mark>מארקר</mark></li>\n</ul>'],
];

/**
 * מקרים שבהם התוסף הישן **לא** זרק חריגה אלא השמיד תוכן בשקט.
 * אלה המסוכנים: אף אחד לא ראה שגיאה, והטקסט פשוט נעלם מהמסך.
 */
const SILENTLY_CORRUPTED = [
  ['נטוי ואז מארקר', '*italic* then ==def==', '<p><em>italic</em> then <mark>def</mark></p>'],
  ['קו חוצה ואז מארקר', '~~strike~~ then ==def==', '<p><s>strike</s> then <mark>def</mark></p>'],
  ['מארקר בתוך מודגש', '**bold ==mark== more**', '<p><strong>bold <mark>mark</mark> more</strong></p>'],
];

/** מקרים שעבדו כבר קודם — כאן כדי לוודא שהמעבר לא שינה כלום. */
const UNCHANGED = [
  ['מארקר לבד', '==abc==', '<p><mark>abc</mark></p>'],
  ['מארקר ואז מודגש', '==abc== then **def**', '<p><mark>abc</mark> then <strong>def</strong></p>'],
  ['מודגש בתוך מארקר', '==abc **def** ghi==', '<p><mark>abc <strong>def</strong> ghi</mark></p>'],
  ['שני מארקרים', '==abc== ו-==def==', '<p><mark>abc</mark> ו-<mark>def</mark></p>'],
  ['קישור בתוך מארקר', '==[link](http://x.com)==',
    '<p><mark><a href="http://x.com">link</a></mark></p>'],
  // הגבולות שמונעים תפיסות שווא — כל אחד מהם הוא שימוש רגיל בכלי שכולו על קוד:
  ['רווח אחרי הפותח אינו מארקר', '== abc ==', '<p>== abc ==</p>'],
  ['השוואה בפייתון אינה מארקר', 'if a == b == c:', '<p>if a == b == c:</p>'],
  ['מפריד ASCII אינו מארקר', '=====', '<p>=====</p>'],
  ['ארבעה סימנים', '====', '<p>====</p>'],
  ['פותח בלי סוגר', '==abc', '<p>==abc</p>'],
  ['סוגר בלי פותח', 'abc == def', '<p>abc == def</p>'],
  ['בתוך קוד מוטבע', '`==abc==`', '<p><code>==abc==</code></p>'],
  // ה-escape נצרך על ידי כלל ה-escape של הספרייה עצמה, הרצף נשבר ואין הזדווגות.
  // **הפלט הזה נמדד ולא הונח** — הציפייה הראשונה שלי כאן הייתה שגויה. אותה תוצאה
  // בדיוק מתקבלת גם עם ``\\~~abc~~`` מול ה-strikethrough המובנה, וגם בלי שום תוסף.
  ['escape על הפותח', '\\==abc==', '<p>==abc==</p>'],
  ['escape על הסוגר', '==abc\\==', '<p>==abc==</p>'],
];

const ALL = [...CRASHED, ...SILENTLY_CORRUPTED, ...UNCHANGED];

console.log('\nתוסף ==מארקר== — התנהגות מול markdown-it 14.1.0:');

const plugin = loadPlugin();

check('הקובץ מייצא את window.MdMarkPlugin', () => {
  if (typeof plugin !== 'function') {
    throw new Error('window.MdMarkPlugin אינו פונקציה — אתרי הקריאה עושים md.use עליו');
  }
});

for (const [name, src, expected] of ALL) {
  check(name, () => eq(render(plugin, src), expected, `קלט: ${JSON.stringify(src)}`));
}

// ---------------------------------------------------------------------------
// המנגנון עצמו: לא רק שהתוצאה נכונה, אלא שהיא מושגת בדרך התקנית.
// ---------------------------------------------------------------------------

check('התוסף נרשם גם ב-ruler וגם ב-ruler2', () => {
  const md = new MarkdownIt(RENDER_OPTIONS).use(plugin);
  const inRuler = md.inline.ruler.__rules__.some(r => r.name === 'mark');
  const inRuler2 = md.inline.ruler2.__rules__.some(r => r.name === 'mark');
  if (!inRuler) throw new Error('הכלל mark לא נרשם ב-inline.ruler');
  if (!inRuler2) {
    throw new Error('הכלל mark לא נרשם ב-inline.ruler2 — בלי שלב ה-postProcess ' +
      'הטוקנים נשארים טקסט, וזה בדיוק מה שהמנגנון התקני דורש');
  }
});

check('אין פרסור מקונן — זה היה השורש של הבאג', () => {
  const code = fs.readFileSync(MODULE_PATH, 'utf8');
  // ההערה בראש הקובץ מצטטת את השורה השבורה כדי להסביר אותה, ולכן מחפשים
  // רק מחוץ להערות: שורת קוד ממשית שקוראת ל-inline.parse.
  const codeOnly = code
    .split('\n')
    .filter(l => !/^\s*(\*|\/\*|\/\/)/.test(l))
    .join('\n');
  if (/inline\s*\.\s*parse\s*\(/.test(codeOnly)) {
    throw new Error('חזרה קריאה ל-inline.parse מתוך התוסף. היא מריצה את שלבי ' +
      'הסיום על מערך הטוקנים המשותף ומקצרת אותו (fragments_join), ואז האינדקסים ' +
      'של הדלימיטרים החיצוניים מצביעים מעבר לסוף.');
  }
});

check('הדלימיטר נרשם עם length: 0', () => {
  const code = fs.readFileSync(MODULE_PATH, 'utf8');
  if (!/length:\s*0/.test(code)) {
    throw new Error('חסר length: 0 ברשומת הדלימיטר. בלעדיו נכנס "כלל השלוש" ' +
      'שנועד להדגשות בלבד, ו-==a== ליד סימני שווה נוספים מפסיק להזדווג. ' +
      'מקור: markdown-it/lib/rules_inline/balance_pairs.mjs, שורות 30-34.');
  }
});

// ---------------------------------------------------------------------------
// בקרה: אותן טענות בדיוק, על התוסף הישן. בדיקה שאינה נופלת שם אינה בודקת כלום.
// ---------------------------------------------------------------------------

console.log('\nבקרה — אותן בדיקות על התוסף הישן (חייבות ליפול):');

let brokeAsExpected = 0;
let unexpectedlyPassed = [];

for (const [name, src, expected] of [...CRASHED, ...SILENTLY_CORRUPTED]) {
  let actual;
  try { actual = render(brokenPlugin, src); }
  catch (e) { actual = 'CRASH: ' + e.message; }
  if (actual === expected) unexpectedlyPassed.push(name);
  else brokeAsExpected += 1;
}

check(`כל ${CRASHED.length + SILENTLY_CORRUPTED.length} המקרים הפגומים נכשלים על הקוד הישן`, () => {
  if (unexpectedlyPassed.length) {
    throw new Error('המקרים האלה עברו גם על הקוד הישן, כלומר הם לא מעידים על התיקון: ' +
      unexpectedlyPassed.join(', '));
  }
});

check(`כל ${UNCHANGED.length} המקרים שעבדו קודם עדיין נותנים את אותו פלט בדיוק`, () => {
  const changed = [];
  for (const [name, src, expected] of UNCHANGED) {
    let old;
    try { old = render(brokenPlugin, src); } catch (e) { old = 'CRASH: ' + e.message; }
    if (old !== expected) changed.push(`${name} (ישן: ${old})`);
  }
  if (changed.length) {
    throw new Error('המעבר שינה התנהגות שעבדה קודם:\n      ' + changed.join('\n      '));
  }
});

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
