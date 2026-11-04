/**
 * טסטים ל-webapp/static/js/md-source-lines-plugin.js — כל בלוק מרונדר מסומן בשורות המקור שלו, ותא בטבלה בשורה ובעמודה.
 *
 * הרצה:  node tests/md-source-lines-plugin.test.js
 * (בריפו אין runner מוגדר ל-JS, ולכן הקובץ עצמאי ומחזיר קוד יציאה 1 בכישלון.)
 *
 * הקובץ הנבדק נטען כמו בדפדפן — script קלאסי שמגדיר ``window.MdSourceLines`` — כי ``package.json`` מוגדר
 * ``"type": "module"`` ולכן ``require()`` רגיל לא היה עובד עליו. ה-renderer הוא markdown-it מ-``node_modules``, אותה
 * גרסה שבחבילה שהדפדפן טוען (``md_preview.bundle.js``).
 *
 * החיווט — ששני הרנדררים טוענים את התוסף, ושאין עותק שלו בתבנית — נבדק ב-``tests/sticky-notes-target.test.js``.
 * הצרכנים בדפדפן: הצ'קליסט והגלילה המסונכרנת בתצוגה החיה (``tests/test_markdown_editor_browser.py``).
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';
import MarkdownIt from 'markdown-it';
import markdownItTaskLists from 'markdown-it-task-lists';
import katex from 'katex';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const JS_DIR = path.join(__dirname, '..', 'webapp', 'static', 'js');

function loadWindow(file) {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(JS_DIR, file), 'utf8'), sandbox);
  return sandbox.window;
}

const { MdSourceLines } = loadWindow('md-source-lines-plugin.js');
const { MdMathPlugin } = loadWindow('md-math-plugin.js');
const { MdAnchors } = loadWindow('md-anchors.js');

let passed = 0;
let failed = 0;

function check(name, condition, actual) {
  if (condition) {
    passed += 1;
    console.log('  ✅', name);
  } else {
    failed += 1;
    console.log('  ❌', name, actual !== undefined ? '\n     actual: ' + JSON.stringify(actual) : '');
  }
}

/** ה-renderer של התצוגה החיה, בקטן: התוספים שמחליפים כללי רינדור לפני התוסף, והוא אחרון. */
function renderer() {
  return new MarkdownIt()
    .use(MdMathPlugin, { katex })
    .use(markdownItTaskLists, { label: true, enabled: true })
    .use(MdSourceLines.plugin);
}

/** ``[start, end]`` של התגית הראשונה מהסוג ``tag`` שיש עליה סימון. */
function linesOf(html, tag) {
  const m = html.match(new RegExp(`<${tag}\\b[^>]*data-source-line="(\\d+)" data-source-line-end="(\\d+)"`));
  return m ? [Number(m[1]), Number(m[2])] : null;
}

console.log('כל סוג בלוק מסומן בשורה הראשונה שלו ובשורה שאחרי האחרונה (0-based)');
{
  const src = [
    '# כותרת',           // 0
    '',                  // 1
    'פסקה בשורה',        // 2
    'ועוד שורה',          // 3
    '',                  // 4
    '> ציטוט',            // 5
    '',                  // 6
    '- פריט',             // 7
    '- פריט שני',         // 8
    '',                  // 9
    '```js',             // 10
    'x = 1',             // 11
    '```',               // 12
    '',                  // 13
    '---',               // 14
    '',                  // 15
    '$$',                // 16
    'a^2',               // 17
    '$$',                // 18
  ].join('\n');
  const html = renderer().render(src);
  check('כותרת', JSON.stringify(linesOf(html, 'h1')) === '[0,1]', linesOf(html, 'h1'));
  check('פסקה של שתי שורות', JSON.stringify(linesOf(html, 'p')) === '[2,4]', linesOf(html, 'p'));
  check('ציטוט', JSON.stringify(linesOf(html, 'blockquote')) === '[5,6]', linesOf(html, 'blockquote'));
  // הטווח של רשימה ב-markdown-it כולל את השורה הריקה שאחריה, עד הבלוק הבא (נמדד בגרסה 14.1.0).
  check('רשימה — עד הבלוק הבא', JSON.stringify(linesOf(html, 'ul')) === '[7,10]', linesOf(html, 'ul'));
  check('פריט ראשון ברשימה', JSON.stringify(linesOf(html, 'li')) === '[7,8]', linesOf(html, 'li'));
  // ב-fence של markdown-it המאפיינים נכתבים על ה-<code> שבתוך ה-<pre>, יחד עם ה-class של השפה.
  check('בלוק קוד — על ה-<code>', /<pre><code data-source-line="10" data-source-line-end="13" class="language-js">/.test(html), html);
  check('קו מפריד', /<hr data-source-line="14" data-source-line-end="15">/.test(html), html);
  // ``math_block`` של md-math-plugin.js מרנדר את מאפייני הטוקן — ולכן התוסף מותקן אחריו.
  check('נוסחה בבלוק', /<div class="md-math" dir="ltr" data-source-line="16" data-source-line-end="19">/.test(html), html);
}

console.log('תא בטבלה: השורה של השורה שלו בטבלה, ומספר העמודה');
{
  const html = renderer().render('| א | ב |\n|---|---|\n| 1 | 2 |\n| 3 | 4 |\n');
  check('שורות הטבלה מסומנות', /<tr data-source-line="2" data-source-line-end="3">/.test(html) && /<tr data-source-line="3" data-source-line-end="4">/.test(html), html);
  check('תא כותרת: שורה 0, עמודה 1', /<th data-row-line="0" data-col="1">ב<\/th>/.test(html), html);
  check('תא בשורה השלישית: שורה 3, עמודה 0', /<td data-row-line="3" data-col="0">3<\/td>/.test(html), html);
}

console.log('מפת השורות: בלי מפה — שורות הטקסט שפוענח; עם מפה — השורות בעורך');
{
  // שורה שכולה עוגן מוסרת לפני הפענוח (``MdAnchors.extractExplicitAnchors``), ולכן מה שאחריה זז בשורה אחת.
  const src = '# ראשית\n\n<a id="x"></a>\n## שנייה\n\n- [ ] משימה\n';
  const extracted = MdAnchors.extractExplicitAnchors(src);
  check('התנאי של הבדיקה: שורת העוגן (2) הוסרה', JSON.stringify(extracted.lineMap) === '[0,1,3,4,5,6]', extracted.lineMap);
  const md = renderer();
  const plain = md.render(extracted.source);
  const mapped = md.render(extracted.source, { sourceLineMap: extracted.lineMap });
  check('בלי מפה — שורת הטקסט שפוענח', JSON.stringify(linesOf(plain, 'h2')) === '[2,3]', linesOf(plain, 'h2'));
  check('עם מפה — השורה בעורך', JSON.stringify(linesOf(mapped, 'h2')) === '[3,4]', linesOf(mapped, 'h2'));
  // הצ'קליסט של התצוגה החיה מתרגם לחיצה לשורה לפי ה-<li> הזה (``handleTaskToggle`` ב-``live-preview.js``).
  check('פריט משימה — השורה שלו בעורך', /<li class="task-list-item enabled" data-source-line="5" data-source-line-end="6">/.test(mapped), mapped);
  check('כותרת לפני שורת העוגן לא זזה', JSON.stringify(linesOf(mapped, 'h1')) === '[0,1]', linesOf(mapped, 'h1'));
}

console.log('בלוק שנגמר בסוף הטקסט, עם מפה: הקצה הוא השורה שאחרי האחרונה, גם כשאין לה ערך במפה');
{
  const extracted = MdAnchors.extractExplicitAnchors('<a id="top"></a>\n# כותרת\nפסקה אחרונה');
  const html = renderer().render(extracted.source, { sourceLineMap: extracted.lineMap });
  check('הפסקה האחרונה: [2, 3]', JSON.stringify(linesOf(html, 'p')) === '[2,3]', html);
}

console.log('התוסף עוטף את כלל הרינדור שכבר קיים — ולא מחליף אותו');
{
  const md = new MarkdownIt();
  md.renderer.rules.hr = () => '<hr class="custom">\n';
  md.use(MdSourceLines.plugin);
  check('הכלל המקורי של hr עדיין מרנדר', md.render('---\n').trim() === '<hr class="custom">', md.render('---\n'));
}

console.log(`\n${passed} עברו, ${failed} נכשלו`);
if (failed) process.exit(1);
