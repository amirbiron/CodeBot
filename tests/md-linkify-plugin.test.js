/**
 * טסטים ל-webapp/static/js/md-linkify-plugin.js — קישור אוטומטי נוצר רק מכתובת שנכתבה עם פרוטוקול, ולא משם קובץ.
 *
 * הרצה:  node tests/md-linkify-plugin.test.js
 * (קובץ עצמאי שמריץ את הבדיקות בעצמו ויוצא בקוד 1 בכישלון: ``.github/workflows/ci.yml`` רץ בלולאה על
 *  ``tests/*.test.js`` עם ``node "$f"``.)
 *
 * **הבאג.** markdown-it נוצר בוובאפ עם ``linkify: true``, ו-linkify-it ניחש כתובות בלי פרוטוקול: ``readme.md``,
 * ``app.py`` ו-``myAgent-spec.ms`` הוצגו כקישור ל-``http://readme.md``, כי ``md``, ``py`` ו-``ms`` הם קודי מדינה.
 * ההסבר המלא בראש התוסף.
 *
 * **מה נבדק כאן:**
 * - ההתנהגות: שמות קבצים נשארים טקסט — השמות מהדיווח, ושם קובץ לכל סיומת נפוצה שהספרייה ניחשה כאתר; וכתובת עם
 *   פרוטוקול, מייל, ``[טקסט](כתובת)`` ו-``<כתובת>`` נשארים קישור, לאותה כתובת. זה גם מה שמקבע את ההתנהגות של
 *   linkify-it שהתוסף נשען עליה, כך ששדרוג שמשנה אותה נופל כאן.
 * - החיווט: כל קובץ בוובאפ שיוצר את markdown-it עם ``linkify: true`` מתקין את התוסף, וכל תבנית שמארחת רנדרר טוענת
 *   את הקובץ עם ``?v={{ static_version }}``, לפני ``live-preview.js``.
 * - בקרה: אותם מקרים בלי התוסף נכשלים — כלומר הם באמת מעידים על התיקון.
 *
 * הרינדור כאן הוא markdown-it מ-``node_modules``, אותה גרסה שבבאנדל שהדפדפן טוען (``md_preview.bundle.js``), עם
 * ``linkify: true`` בלבד: זו האפשרות היחידה מאלה של העמודים שנוגעת בזיהוי קישורים. העמודים עצמם, עם כל התצורה
 * שלהם, נבדקים בכרומיום ב-``tests/test_md_autolink_browser.py``.
 *
 * הקובץ הנבדק נטען כמו בדפדפן — script קלאסי שמגדיר ``window.MdLinkifyPlugin`` — כי ``package.json`` מוגדר
 * ``"type": "module"`` ולכן ``require()`` רגיל לא היה עובד עליו.
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';
import MarkdownIt from 'markdown-it';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const MODULE_PATH = path.join(ROOT, 'webapp', 'static', 'js', 'md-linkify-plugin.js');

function loadPlugin() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox.window.MdLinkifyPlugin;
}

const linkifyPlugin = loadPlugin();

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

function withPlugin() {
  return new MarkdownIt({ linkify: true }).use(linkifyPlugin);
}

function withoutPlugin() {
  return new MarkdownIt({ linkify: true });
}

/** כל הקישורים שהשורה יצרה, כ-``[טקסט, href]``. */
function links(md, src) {
  const html = md.renderInline(src);
  return [...html.matchAll(/<a href="([^"]*)">([^<]*)<\/a>/g)].map((m) => [m[2], m[1]]);
}

// השמות מהדיווח (צילום התצוגה החיה בעמוד העריכה): כל מה שהפך לקישור, וגם ``.mj`` שלא הפך, לבקרה.
const REPORTED_NAMES = [
  'מדריך-תצוגת-Markdown-RTL.md',
  'myAgent-spec.md',
  'myAgent-spec.ms',
  'myAgent-spec.mr',
  'myAgent-spec.me',
  'myAgent-spec.mw',
  'myAgent-spec.py',
  'myAgent-spec.ht',
];

// סיומות נפוצות של קבצים שהספרייה ניחשה כאתר. נמדד ב-linkify-it 5.0.0 על ``file.<סיומת>`` (13.11.2026), ומאומת
// שוב בבקרה למטה: כל אחת מהן הייתה קישור בלי התוסף.
const FILE_EXTENSIONS = [
  'md', 'py', 'sh', 'rs', 'pl', 'pm', 'tf', 'cc', 'ml', 'mk', 'sv', 'so', 'ai', 'ly', 'gs', 'st', 'ws', 'cr', 'sc',
  'pro', 'org', 'com', 'info', 'name', 'mo', 'me', 'io', 'do', 'am', 'ac', 'in',
];

// כתובת שהכותב סימן בעצמו כקישור: ``[מקור, טקסט הקישור, href]``.
const EXPLICIT = [
  ['https://example.com/a?b=1', 'https://example.com/a?b=1', 'https://example.com/a?b=1'],
  ['http://example.org', 'http://example.org', 'http://example.org'],
  ['ftp://files.example.com/x.zip', 'ftp://files.example.com/x.zip', 'ftp://files.example.com/x.zip'],
  ['https://example.com/docs/readme.md', 'https://example.com/docs/readme.md', 'https://example.com/docs/readme.md'],
  ['mailto:someone@example.com', 'mailto:someone@example.com', 'mailto:someone@example.com'],
  ['someone@example.com', 'someone@example.com', 'mailto:someone@example.com'],
  ['//cdn.example.com/lib.js', '//cdn.example.com/lib.js', '//cdn.example.com/lib.js'],
  ['[מדריך](https://example.com/guide)', 'מדריך', 'https://example.com/guide'],
  ['<https://example.com/x>', 'https://example.com/x', 'https://example.com/x'],
];

console.log('שמות קבצים נשארים טקסט');
{
  const md = withPlugin();
  REPORTED_NAMES.forEach((name) => {
    check(`${name} — לא קישור`, links(md, name).length === 0, md.renderInline(name));
  });
  const linked = FILE_EXTENSIONS.filter((ext) => links(md, `file.${ext}`).length > 0);
  check(`שם קובץ עם כל אחת מ-${FILE_EXTENSIONS.length} הסיומות — לא קישור`, linked.length === 0, linked);
  // בלוק שלם, כמו בצילום: שם בכל שורה, עם ``breaks`` של העמודים.
  const block = new MarkdownIt({ linkify: true, breaks: true }).use(linkifyPlugin).render(REPORTED_NAMES.join('\n'));
  check('רשימת השמות מהדיווח כבלוק — אין בה קישור', block.indexOf('<a ') === -1, block);
}

console.log('כתובת בלי פרוטוקול נשארת טקסט — החלטת המשתמש (נובמבר 2026), בלי כלל מיוחד ל-www.');
{
  const md = withPlugin();
  ['www.example.com', 'example.com', 'docs.python.org', 'google.co.il'].forEach((src) => {
    check(`${src} — לא קישור`, links(md, src).length === 0, md.renderInline(src));
  });
}

console.log('מה שהכותב סימן כקישור נשאר קישור, לאותה כתובת');
{
  const md = withPlugin();
  EXPLICIT.forEach(([src, text, href]) => {
    const got = links(md, src);
    check(`${src} ← <a href="${href}">`, got.length === 1 && got[0][0] === text && got[0][1] === href, got);
  });
  const mixed = links(md, 'ראו את readme.md ואת https://example.com/readme.md');
  check('בשורה עם שם קובץ וכתובת — רק הכתובת היא קישור',
    mixed.length === 1 && mixed[0][1] === 'https://example.com/readme.md', mixed);
}

console.log('ההגדרה שייכת למופע שהתקין את התוסף בלבד');
{
  // ``md.linkify`` הוא מופע של linkify-it לכל ``new MarkdownIt()``. אילו היה משותף, התוסף בעמוד אחד היה משנה גם
  // רנדרר אחר באותו עמוד, ושני הצדדים של הבקרה למטה היו נראים אותו דבר.
  const a = withPlugin();
  const b = withoutPlugin();
  check('מופע בלי התוסף, שנוצר אחרי מופע עם התוסף, עדיין מנחש', links(b, 'readme.md').length === 1, links(b, 'readme.md'));
  check('והמופע עם התוסף לא מנחש', links(a, 'readme.md').length === 0, links(a, 'readme.md'));
}

// ---------------------------------------------------------------------------
// חיווט
// ---------------------------------------------------------------------------

function walk(dir, accept, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, accept, out);
    else if (accept(entry.name)) out.push(full);
  }
  return out;
}

console.log('חיווט: כל מקום שמדליק linkify מתקין את התוסף');
{
  // הבאנדל (``*.bundle.js``) הוא הקוד של markdown-it עצמו, והתוסף מזכיר את ``linkify: true`` בהסבר שלו. אף אחד
  // מהם אינו מקום שיוצר מופע.
  const sources = [
    ...walk(path.join(ROOT, 'webapp', 'templates'), (name) => name.endsWith('.html')),
    ...walk(path.join(ROOT, 'webapp', 'static'), (name) => name.endsWith('.js') && !name.endsWith('.bundle.js')),
  ].filter((file) => file !== MODULE_PATH);
  const sites = [];
  const missing = [];
  for (const file of sources) {
    const src = fs.readFileSync(file, 'utf8');
    const enables = (src.match(/\blinkify\s*:\s*true\b/g) || []).length;
    if (!enables) continue;
    const rel = path.relative(ROOT, file);
    sites.push(rel);
    const installs = (src.match(/\.use\(\s*window\.MdLinkifyPlugin\s*\)/g) || []).length;
    if (installs < enables) missing.push(`${rel} (${enables} יצירות, ${installs} התקנות)`);
  }
  // בלי זה, סריקה שלא מצאה כלום — למשל אחרי שינוי בצורת הכתיבה — הייתה עוברת.
  const expected = [
    path.join('webapp', 'templates', 'md_preview.html'),
    path.join('webapp', 'static', 'js', 'live-preview.js'),
    path.join('webapp', 'static', 'js', 'repo-browser.js'),
  ];
  check('הסריקה מצאה את המקומות הידועים', expected.every((rel) => sites.includes(rel)), sites);
  check('כל מקום שמדליק linkify מתקין את התוסף', missing.length === 0, missing);
}

console.log('חיווט: כל תבנית שמארחת רנדרר טוענת את התוסף');
{
  // התבניות שמארחות רנדרר הן אלה שטוענות את ``md-mark-plugin.js`` — התוסף האח, שכל הרנדררים האלה מתקינים —
  // ובנוסף כל תבנית שטוענת את ``live-preview.js``, כדי שתבנית שתטען אותו בלי המארקר לא תיפול בין הכיסאות.
  const templates = walk(path.join(ROOT, 'webapp', 'templates'), (name) => name.endsWith('.html'));
  const hosts = [];
  const missing = [];
  for (const file of templates) {
    const src = fs.readFileSync(file, 'utf8');
    const mark = src.search(/<script[^>]*js\/md-mark-plugin\.js/);
    const live = src.search(/<script[^>]*js\/live-preview\.js/);
    if (mark < 0 && live < 0) continue;
    const rel = path.relative(ROOT, file);
    hosts.push(rel);
    const plugin = src.search(/<script[^>]*js\/md-linkify-plugin\.js'\) \}\}\?v=\{\{ static_version \}\}/);
    if (plugin < 0 || (live >= 0 && plugin > live)) missing.push(rel);
  }
  const expected = [
    path.join('webapp', 'templates', '_live_preview_scripts.html'),
    path.join('webapp', 'templates', 'files.html'),
    path.join('webapp', 'templates', 'md_preview.html'),
    path.join('webapp', 'templates', 'repo', 'base_repo.html'),
  ];
  check('הסריקה מצאה את התבניות הידועות', expected.every((rel) => hosts.includes(rel)), hosts);
  check('כולן טוענות את md-linkify-plugin.js עם ?v={{ static_version }}, לפני live-preview.js',
    missing.length === 0, missing);
}

// ---------------------------------------------------------------------------
// בקרה: אותם מקרים בלי התוסף. בדיקה שאינה נופלת שם אינה בודקת כלום.
// ---------------------------------------------------------------------------

console.log('בקרה — בלי התוסף');
{
  const md = withoutPlugin();
  const stillText = REPORTED_NAMES.filter((name) => links(md, name).length === 0);
  check('כל השמות מהדיווח היו קישור', stillText.length === 0, stillText);
  const notLinked = FILE_EXTENSIONS.filter((ext) => links(md, `file.${ext}`).length === 0);
  check(`כל ${FILE_EXTENSIONS.length} הסיומות היו קישור`, notLinked.length === 0, notLinked);
  check('www.example.com היה קישור', links(md, 'www.example.com').length === 1, links(md, 'www.example.com'));
  check('myAgent-spec.mj לא היה קישור גם קודם — mj אינה סיומת של אתר', links(md, 'myAgent-spec.mj').length === 0);
  const changed = EXPLICIT.filter(([src, text, href]) => {
    const got = links(md, src);
    return !(got.length === 1 && got[0][0] === text && got[0][1] === href);
  }).map(([src]) => src);
  check('הכתובות המפורשות היו קישור גם קודם, לאותה כתובת — התוסף לא שינה אותן', changed.length === 0, changed);
}

console.log(`\n${passed} עברו, ${failed} נכשלו`);
if (failed) process.exit(1);
