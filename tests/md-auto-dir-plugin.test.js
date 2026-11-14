/**
 * טסטים ל-webapp/static/js/md-auto-dir-plugin.js — קוד בתוך שורה ותאי טבלה מקבלים ``dir="auto"``.
 *
 * הרצה:  node tests/md-auto-dir-plugin.test.js
 * (קובץ עצמאי שמריץ את הבדיקות בעצמו ויוצא בקוד 1 בכישלון: ``.github/workflows/ci.yml`` רץ בלולאה על
 *  ``tests/*.test.js`` עם ``node "$f"``.)
 *
 * **הבאג.** העמודים בוובאפ הם ``dir="rtl"``, וקוד בשורה ותא בטבלה ירשו את הכיוון הזה: ``--flag`` הוצג ``flag--``,
 * ``foo()`` הוצג ``()foo`` ו-``C++`` בטבלה הוצג ``++C``. ההסבר המלא בראש התוסף.
 *
 * **מה נבדק כאן:**
 * - ההתנהגות: ``dir="auto"`` על כל ``code`` של קוד בשורה — גם בתוך כותרת, הדגשה, קישור ותא — ועל כל ``th`` ו-``td``;
 *   לא על בלוק קוד (גדר או הזחה); היישור שהוגדר בשורת ההפרדה נשמר; ועם ``md-source-lines-plugin.js``, בכל סדר
 *   התקנה, התא נושא גם את ``data-row-line`` / ``data-col`` וגם את ``dir``.
 * - הרנדרר של ``live-preview.js``: אין בוובאפ כלל ``code_inline`` שאינו כותב את מאפייני הטוקן. כלל כזה ישב שם עד
 *   התיקון, ומחק את ``dir`` בשקט בתצוגה החיה, בייצוא, בדפדפן הריפו ובכרטיסי החיפוש בתיעוד.
 * - החיווט: כל מקום שיוצר את markdown-it מתקין את התוסף, וכל תבנית שמארחת רנדרר טוענת את הקובץ עם
 *   ``?v={{ static_version }}``, לפני ``live-preview.js``.
 * - בקרה: בלי התוסף אין ``dir``, וכלל ``code_inline`` כמו זה שהוסר מוחק אותו גם כשהתוסף מותקן.
 *
 * הרינדור כאן הוא markdown-it מ-``node_modules``, אותה גרסה שבבאנדל שהדפדפן טוען (``md_preview.bundle.js``), עם
 * האפשרויות של העמודים (``breaks``, ``linkify``, ``typographer``, ``html: false``). מה שהדפדפן מצייר מהמאפיין — הסדר
 * של התווים על המסך והיישור — נבדק בכרומיום, בעמודים האמיתיים, ב-``tests/test_md_auto_dir_browser.py``.
 *
 * הקבצים הנבדקים נטענים כמו בדפדפן — script קלאסי שמגדיר משתנה על ``window`` — כי ``package.json`` מוגדר
 * ``"type": "module"`` ולכן ``require()`` רגיל לא היה עובד עליהם.
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';
import MarkdownIt from 'markdown-it';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const JS_DIR = path.join(ROOT, 'webapp', 'static', 'js');
const MODULE_PATH = path.join(JS_DIR, 'md-auto-dir-plugin.js');

function loadWindow(...files) {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  for (const file of files) vm.runInContext(fs.readFileSync(path.join(JS_DIR, file), 'utf8'), sandbox);
  return sandbox.window;
}

// **עם ``utils/file-name.js`` באותו ``window``, כמו בכל עמוד שטוען את התוסף** (בדיקת החיווט למטה): משם התוסף קורא את
// הפירוק של שם קובץ עברי. ``bareAutoDirPlugin`` — בלעדיו, לבקרה.
const autoDirPlugin = loadWindow('utils/file-name.js', 'md-auto-dir-plugin.js').MdAutoDirPlugin;
const bareAutoDirPlugin = loadWindow('md-auto-dir-plugin.js').MdAutoDirPlugin;
const sourceLines = loadWindow('md-source-lines-plugin.js').MdSourceLines;

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

/** האפשרויות של הרנדררים בעמודים (``md_preview.html``, ``ensureRenderer`` ב-``live-preview.js``). */
function pageMd() {
  return new MarkdownIt({ breaks: true, linkify: true, typographer: true, html: false });
}

/** כל התגיות הפותחות מהסוג ``tag`` ב-HTML, כטקסט. */
function openTags(html, tag) {
  return [...html.matchAll(new RegExp(`<${tag}(?=[\\s>])[^>]*>`, 'g'))].map((m) => m[0]);
}

const INLINE = [
  'פסקה עם `--flag` באמצע',
  '# כותרת עם `foo()`',
  'מודגש: **הריצו `npm install` לפני**',
  'קישור: [`readme.md`](https://example.com/readme)',
  'שם קובץ בעברית: `הפניות-שלא-חלו.md`',
].join('\n\n');

const TABLE = [
  '| שם | ערך | מימין |',
  '|---|---|---:|',
  '| שפה | C++ | x |',
  '| פונקציה | `foo()` | y |',
].join('\n');

const BLOCKS = [
  '```js',
  'const a = `x`;',
  '```',
  '',
  '    indented();',
].join('\n');

console.log('קוד בשורה מקבל dir="auto"');
{
  const html = pageMd().use(autoDirPlugin).render(INLINE);
  const codes = openTags(html, 'code');
  check('חמישה קטעי קוד בשורה, בפסקה, בכותרת, בהדגשה, בקישור ובשם בעברית', codes.length === 5, codes);
  check('כולם עם dir="auto"', codes.every((tag) => tag === '<code dir="auto">'), codes);
}

console.log('תאי טבלה מקבלים dir="auto", והיישור מהמסמך נשמר');
{
  const html = pageMd().use(autoDirPlugin).render(TABLE);
  const cells = [...openTags(html, 'th'), ...openTags(html, 'td')];
  check('תשעה תאים', cells.length === 9, cells);
  check('כולם עם dir="auto"', cells.every((tag) => /\sdir="auto"/.test(tag)), cells);
  const right = cells.filter((tag) => /style="text-align:right"/.test(tag));
  check('שלושת התאים בעמודה שהוגדרה ---: שומרים על text-align:right', right.length === 3, right);
  check('קוד בשורה בתוך תא — גם הוא עם dir="auto"', /<td dir="auto"><code dir="auto">foo\(\)<\/code><\/td>/.test(html), html);
}

console.log('שם קובץ עברי בקוד בשורה: dir="rtl" והסיומת ב-<bdi>');
{
  const md = pageMd().use(autoDirPlugin);
  const one = (src) => md.renderInline(src);
  check('מדריך-תצוגת-Markdown-RTL.md — מפורק',
    one('`מדריך-תצוגת-Markdown-RTL.md`') === '<code dir="rtl">מדריך-תצוגת-Markdown-RTL.<bdi>md</bdi></code>',
    one('`מדריך-תצוגת-Markdown-RTL.md`'));
  check('Report-דוח-Q3.md — מפורק, גם כשהשם מתחיל באנגלית',
    one('`Report-דוח-Q3.md`') === '<code dir="rtl">Report-דוח-Q3.<bdi>md</bdi></code>', one('`Report-דוח-Q3.md`'));
  // ההחלטה מתי מפרקים נבדקת לעומק ב-``tests/file-name.test.js``; כאן — שהתוסף שואל אותה, ושהוא לא מפרק סתם.
  for (const keep of ['ערכות.md', 'morass-Tech-theme.json', 'דוח.tar.gz', 'docs/מדריך/Guide-RTL.md', '--flag']) {
    check(`${keep} — נשאר dir="auto" ובלי <bdi>`, one('`' + keep + '`') === `<code dir="auto">${keep}</code>`, one('`' + keep + '`'));
  }
  check('הטקסט עובר בריחה גם כשהשם מפורק',
    one('`<b>דוח-RTL.md`') === '<code dir="rtl">&lt;b&gt;דוח-RTL.<bdi>md</bdi></code>', one('`<b>דוח-RTL.md`'));
  const html = pageMd().use(autoDirPlugin).render('| שם |\n|---|\n| `מדריך-RTL.md` |');
  check('גם בתוך תא, והתא נשאר dir="auto"', /<td dir="auto"><code dir="rtl">מדריך-RTL\.<bdi>md<\/bdi><\/code><\/td>/.test(html), html);
  const both = pageMd().use(sourceLines.plugin).use(autoDirPlugin).render('`מדריך-RTL.md` ו-`foo()`');
  check('יחד עם md-source-lines-plugin.js', /<code dir="rtl">מדריך-RTL\.<bdi>md<\/bdi><\/code>/.test(both) &&
    /<code dir="auto">foo\(\)<\/code>/.test(both), both);
}

console.log('בלוק קוד לא מקבל dir — הכיוון שלו נקבע ב-utils/rtl-code.js');
{
  const html = pageMd().use(autoDirPlugin).render(BLOCKS);
  const codes = openTags(html, 'code');
  check('שני בלוקים, גדר והזחה', codes.length === 2, codes);
  check('אף אחד מהם בלי dir', codes.every((tag) => !/\sdir=/.test(tag)), codes);
}

console.log('יחד עם md-source-lines-plugin.js, בכל סדר התקנה');
{
  const orders = {
    'auto-dir ואז source-lines': () => pageMd().use(autoDirPlugin).use(sourceLines.plugin),
    'source-lines ואז auto-dir': () => pageMd().use(sourceLines.plugin).use(autoDirPlugin),
  };
  for (const [name, make] of Object.entries(orders)) {
    const html = make().render(TABLE);
    const tds = openTags(html, 'td');
    const both = tds.filter((tag) => /\sdir="auto"/.test(tag) && /\sdata-row-line="\d+"/.test(tag) && /\sdata-col="\d+"/.test(tag));
    check(`${name}: כל ששת התאים נושאים dir, data-row-line ו-data-col`, tds.length === 6 && both.length === 6, tds);
  }
}

// ---------------------------------------------------------------------------
// הרנדרר של live-preview.js — אין כלל code_inline שמוחק את המאפיינים
// ---------------------------------------------------------------------------

function walk(dir, accept, out = []) {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(full, accept, out);
    else if (accept(entry.name)) out.push(full);
  }
  return out;
}

const SOURCES = [
  ...walk(path.join(ROOT, 'webapp', 'templates'), (name) => name.endsWith('.html')),
  ...walk(path.join(ROOT, 'webapp', 'static'), (name) => name.endsWith('.js') && !name.endsWith('.bundle.js')),
];

/**
 * כמה כללי ``code_inline`` בטקסט מוחלפים ידנית (``rules.code_inline = ...``) בלי לקרוא ל-``renderAttrs``. כלל כזה
 * מוחק את ``dir`` שהתוסף כתב על הטוקן. הגוף נחתך עד ההשמה הבאה לכלל רינדור, או עד 1,500 תווים — מה שקודם.
 */
function codeInlineOffenders(src) {
  let count = 0;
  for (const match of src.matchAll(/rules\.code_inline\s*=(?!=)/g)) {
    const body = src.slice(match.index, match.index + 1500).split(/rules\.\w+\s*=(?!=)/)[1] || '';
    if (!/renderAttrs/.test(body)) count += 1;
  }
  return count;
}

console.log('אין בוובאפ כלל code_inline שאינו כותב את מאפייני הטוקן');
{
  const offenders = SOURCES.filter((file) => codeInlineOffenders(fs.readFileSync(file, 'utf8')) > 0)
    .map((file) => path.relative(ROOT, file));
  check('אין כלל code_inline שמוחק מאפיינים', offenders.length === 0, offenders);
}

// ---------------------------------------------------------------------------
// חיווט
// ---------------------------------------------------------------------------

console.log('חיווט: כל מקום שיוצר את markdown-it מתקין את התוסף');
{
  const sites = [];
  const missing = [];
  for (const file of SOURCES) {
    if (file === MODULE_PATH) continue;
    const src = fs.readFileSync(file, 'utf8');
    // שתי הצורות שבהן נוצר מופע: קריאה ישירה עם אפשרויות (``live-preview.js``, ``repo-browser.js``), והצורה של
    // ``md_preview.html``, שבוחרת בין ``window.markdownit`` לאובייקט גיבוי. הבדיקה על ``expected`` למטה תופסת צורה שלישית.
    const creates = (src.match(/\bwindow\.markdownit\s*\(\s*\{|\bwindow\.markdownit\s*\?\s*window\.markdownit\b/g) || []).length;
    if (!creates) continue;
    const rel = path.relative(ROOT, file);
    sites.push(rel);
    const installs = (src.match(/\.use\(\s*window\.MdAutoDirPlugin\s*\)/g) || []).length;
    if (installs < creates) missing.push(`${rel} (${creates} יצירות, ${installs} התקנות)`);
  }
  // בלי זה, סריקה שלא מצאה כלום — למשל אחרי שינוי בצורת הכתיבה — הייתה עוברת.
  const expected = [
    path.join('webapp', 'templates', 'md_preview.html'),
    path.join('webapp', 'static', 'js', 'live-preview.js'),
    path.join('webapp', 'static', 'js', 'repo-browser.js'),
  ];
  check('הסריקה מצאה את המקומות הידועים', expected.every((rel) => sites.includes(rel)), sites);
  check('כל מקום שיוצר את markdown-it מתקין את התוסף', missing.length === 0, missing);
}

console.log('חיווט: כל תבנית שמארחת רנדרר טוענת את התוסף');
{
  // התבניות שמארחות רנדרר הן אלה שטוענות את ``md-mark-plugin.js`` — התוסף האח, שכל הרנדררים מתקינים — ובנוסף כל
  // תבנית שטוענת את ``live-preview.js``, כדי שתבנית שתטען אותו בלי המארקר לא תיפול בין הכיסאות.
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
    const plugin = src.search(/<script[^>]*js\/md-auto-dir-plugin\.js'\) \}\}\?v=\{\{ static_version \}\}/);
    if (plugin < 0 || (live >= 0 && plugin > live)) missing.push(rel);
  }
  const expected = [
    path.join('webapp', 'templates', '_live_preview_scripts.html'),
    path.join('webapp', 'templates', 'files.html'),
    path.join('webapp', 'templates', 'md_preview.html'),
    path.join('webapp', 'templates', 'repo', 'base_repo.html'),
  ];
  check('הסריקה מצאה את התבניות הידועות', expected.every((rel) => hosts.includes(rel)), hosts);
  check('כולן טוענות את md-auto-dir-plugin.js עם ?v={{ static_version }}, לפני live-preview.js',
    missing.length === 0, missing);
}

console.log('חיווט: כל עמוד שטוען את התוסף מקבל את utils/file-name.js לפניו');
{
  // התוסף קורא את הפירוק של שם קובץ עברי מ-``window.FileName`` בזמן הרינדור. בלעדיו שם כזה מוצג עם הסיומת באמצע, ורק
  // אזהרה בקונסול אומרת למה. ``base.html`` טוען אותו ב-``<head>``, בלי ``defer`` — לפני כל בלוק של עמוד, ולכן לפני כל
  // סקריפט, דחוי או לא. כל תבנית שטוענת את התוסף יורשת מ-``base.html``, חוץ מה-partial ``_live_preview_scripts.html``:
  // כל מי שכולל אותו יורש מ-``base.html``, או טוען את ``file-name.js`` בעצמו לפני ה-include (עמוד הייצוא המעוצב).
  const templatesDir = path.join(ROOT, 'webapp', 'templates');
  const templates = walk(templatesDir, (name) => name.endsWith('.html'));
  const read = (file) => fs.readFileSync(file, 'utf8');
  const tagRe = (attrs) => new RegExp(`<script src="\\{\\{ url_for\\('static', filename='js/utils/file-name\\.js'\\) \\}\\}\\?v=\\{\\{ static_version \\}\\}"${attrs}></script>`);

  const base = read(path.join(templatesDir, 'base.html'));
  const headEnd = base.indexOf('</head>');
  const baseTag = tagRe('').exec(base);
  check('base.html טוען את file-name.js עם ?v=, בלי defer, בתוך <head>', !!baseTag && baseTag.index < headEnd,
    baseTag ? baseTag.index : 'לא נמצא');

  // יורש מ-``base.html``, ישירות או דרך תבנית ביניים (``base_boards.html``, ``repo/base_repo.html``).
  const extendsBase = (file, seen = new Set()) => {
    const m = /\{%\s*extends\s+"([^"]+)"\s*%\}/.exec(read(file));
    if (!m) return false;
    if (m[1] === 'base.html') return true;
    const parent = path.join(templatesDir, m[1]);
    return !seen.has(parent) && fs.existsSync(parent) && extendsBase(parent, new Set([...seen, parent]));
  };
  const hosts = [];
  const problems = [];
  for (const file of templates) {
    const src = read(file);
    if (src.search(/<script[^>]*js\/md-auto-dir-plugin\.js/) < 0) continue;
    const rel = path.relative(ROOT, file);
    hosts.push(rel);
    if (extendsBase(file)) continue;
    if (path.basename(file) !== '_live_preview_scripts.html') { problems.push(`${rel}: אינו יורש מ-base.html`); continue; }
    for (const includer of templates) {
      const isrc = read(includer);
      const inc = isrc.search(/\{%\s*include\s+"_live_preview_scripts\.html"\s*%\}/);
      if (inc < 0 || extendsBase(includer)) continue;
      const own = tagRe(' defer').exec(isrc) || tagRe('').exec(isrc);
      if (!own || own.index > inc) problems.push(`${path.relative(ROOT, includer)}: כולל את ${rel} בלי file-name.js לפניו`);
    }
  }
  const known = ['_live_preview_scripts.html', 'files.html', 'md_preview.html', path.join('repo', 'base_repo.html')]
    .map((name) => path.join('webapp', 'templates', name));
  check('הסריקה מצאה את התבניות הידועות', known.every((rel) => hosts.includes(rel)), hosts);
  check('בכולן file-name.js נטען לפני התוסף', problems.length === 0, problems);
}

// ---------------------------------------------------------------------------
// בקרה: אותם מקרים בלי התוסף, ועם כלל code_inline כמו זה שהוסר. בדיקה שאינה נופלת שם אינה בודקת כלום.
// ---------------------------------------------------------------------------

console.log('בקרה — בלי התוסף');
{
  const md = pageMd();
  const codes = openTags(md.render(INLINE), 'code');
  check('קוד בשורה בלי dir', codes.length === 5 && codes.every((tag) => tag === '<code>'), codes);
  const html = md.render(TABLE);
  const cells = [...openTags(html, 'th'), ...openTags(html, 'td')];
  check('תאים בלי dir', cells.length === 9 && cells.every((tag) => !/\sdir=/.test(tag)), cells);
}

console.log('בקרה — התוסף בלי utils/file-name.js: שם קובץ עברי אינו מפורק, וכל השאר כמו תמיד');
{
  const md = pageMd().use(bareAutoDirPlugin);
  const out = md.renderInline('`מדריך-תצוגת-Markdown-RTL.md` ו-`foo()`');
  check('בלי <bdi>, ושני הקודים dir="auto"', out === '<code dir="auto">מדריך-תצוגת-Markdown-RTL.md</code> ו-<code dir="auto">foo()</code>', out);
}

console.log('בקרה — כלל code_inline שאינו כותב את המאפיינים, כמו זה שהוסר מ-live-preview.js');
{
  const md = pageMd().use(autoDirPlugin);
  md.renderer.rules.code_inline = (tokens, idx) => `<code class="inline-code">${md.utils.escapeHtml(tokens[idx].content)}</code>`;
  const codes = openTags(md.render(INLINE), 'code');
  check('dir נמחק, אף שהתוסף מותקן', codes.length === 5 && codes.every((tag) => !/\sdir=/.test(tag)), codes);
}

console.log('בקרה — הסורק של כללי code_inline מזהה כלל כזה, ולא כלל שכותב את המאפיינים');
{
  // הכלל שישב ב-``ensureRenderer`` עד התיקון, כלשונו. בלי הבקרה הזו, סורק שאינו מוצא כלום היה מאשר את עצמו.
  const removed = [
    'md.renderer.rules.code_inline = (tokens, idx, options, env, slf) => {',
    '  try {',
    "    const content = tokens[idx] && typeof tokens[idx].content === 'string' ? tokens[idx].content : '';",
    '    const escaped = escapeHtml(content);',
    '    return `<code class="inline-code">${escaped}</code>`;',
    '  } catch (_) {',
    "    return defaultInlineCode ? defaultInlineCode(tokens, idx, options, env, slf) : '';",
    '  }',
    '};',
  ].join('\n');
  check('הכלל שהוסר מזוהה', codeInlineOffenders(removed) === 1);
  const keeps = "md.renderer.rules.code_inline = (t, i, o, e, slf) => '<code' + slf.renderAttrs(t[i]) + '>' + x + '</code>';";
  check('כלל שכותב את המאפיינים אינו מזוהה', codeInlineOffenders(keeps) === 0);
}

console.log(`\n${passed} עברו, ${failed} נכשלו`);
if (failed) process.exit(1);
