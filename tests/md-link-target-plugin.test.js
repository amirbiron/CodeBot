/**
 * טסטים ל-webapp/static/js/md-link-target-plugin.js — קישור במסמך שמוביל לעמוד נפתח בלשונית חדשה, ועוגן נשאר.
 *
 * הרצה:  node tests/md-link-target-plugin.test.js
 * (קובץ עצמאי שמריץ את הבדיקות בעצמו ויוצא בקוד 1 בכישלון: ``.github/workflows/ci.yml`` רץ בלולאה על
 *  ``tests/*.test.js`` עם ``node "$f"``.)
 *
 * **מה נבדק כאן:**
 * - הכלל (``opensInNewTab``) מול ``tests/fixtures/md_link_target_cases.json`` — אותה טבלה ש-``tests/test_md_link_target.py``
 *   מריץ מול ``opens_in_new_tab`` של צד השרת, כדי ששני העותקים של הכלל לא ייפרדו.
 * - הרינדור: כל דרך לכתוב קישור — ``[טקסט](כתובת)``, ``<כתובת>``, כתובת חשופה (linkify), קישור בהפניה — יוצאת עם
 *   ``target="_blank"`` ו-``rel="noopener noreferrer"``; ועוגנים — ``[טקסט](#סעיף)``, ה-``¶`` של markdown-it-anchor, תוכן
 *   העניינים של markdown-it-toc-done-right והערות השוליים של markdown-it-footnote — יוצאים בלי. אלה התוספים שהעמודים
 *   מתקינים, מ-``node_modules``, באותן גרסאות שבבאנדל (``md_preview.bundle.js``).
 * - כלל ``link_open`` שהוגדר לפני התוסף ממשיך לרוץ.
 * - החיווט: כל קובץ בוובאפ שיוצר את markdown-it (הסימן: ``linkify: true``, כמו ב-``tests/md-linkify-plugin.test.js``) מתקין
 *   את התוסף, וכל תבנית שמארחת רנדרר טוענת אותו עם ``?v={{ static_version }}``, לפני ``live-preview.js``.
 * - בקרה: בלי התוסף אף קישור לא יוצא עם ``target`` — כלומר הבדיקות באמת מעידות על התוסף.
 *
 * העמודים עצמם, עם כל התצורה שלהם, נבדקים בכרומיום ב-``tests/test_md_link_target_browser.py``.
 *
 * הקובץ הנבדק נטען כמו בדפדפן — script קלאסי שמגדיר ``window.MdLinkTargetPlugin`` — כי ``package.json`` מוגדר
 * ``"type": "module"`` ולכן ``require()`` רגיל לא היה עובד עליו.
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';
import MarkdownIt from 'markdown-it';
import markdownItAnchor from 'markdown-it-anchor';
import markdownItFootnote from 'markdown-it-footnote';
import markdownItTocDoneRight from 'markdown-it-toc-done-right';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const MODULE_PATH = path.join(ROOT, 'webapp', 'static', 'js', 'md-link-target-plugin.js');
const CASES_PATH = path.join(__dirname, 'fixtures', 'md_link_target_cases.json');

function loadPlugin() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox.window.MdLinkTargetPlugin;
}

const linkTargetPlugin = loadPlugin();
const { cases: CASES } = JSON.parse(fs.readFileSync(CASES_PATH, 'utf8'));

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

/**
 * התוספים שמייצרים קישורים בעמודים: עוגני כותרות עם ``¶`` (כמו ב-``md_preview.html``), הערות שוליים ותוכן עניינים.
 * האזהרה "Using deprecated markdown-it-anchor permalink option" בפלט באה מ-``permalink: true`` — אותה אפשרות שהעמודים
 * מעבירים, ולכן היא כאן.
 */
function renderer(withTarget) {
  const md = new MarkdownIt({ linkify: true, html: false })
    .use(markdownItAnchor, { permalink: true, permalinkSymbol: '¶' })
    .use(markdownItFootnote)
    .use(markdownItTocDoneRight);
  return withTarget ? md.use(linkTargetPlugin) : md;
}

/** כל ``<a>`` ב-HTML, כ-``{text, href, target, rel}``. ה-HTML כאן הוא הפלט של markdown-it, בלי מרכאות בתוך ערכים. */
function anchors(html) {
  const out = [];
  const re = /<a\b([^>]*)>([\s\S]*?)<\/a>/g;
  let m;
  while ((m = re.exec(html))) {
    const attr = (name) => {
      const hit = new RegExp(`\\s${name}="([^"]*)"`).exec(m[1]);
      return hit ? hit[1] : null;
    };
    out.push({ text: m[2].replace(/<[^>]+>/g, '').trim(), href: attr('href'), target: attr('target'), rel: attr('rel') });
  }
  return out;
}

const SAMPLE = [
  '${toc}',
  '',
  '# פתיחה',
  '',
  'קישור [מדריך](https://example.com/docs), כתובת חשופה https://example.com/guide, ו-<https://example.com/auto>.',
  'קישור [בהפניה][ref], [קובץ](docs/a.md), [בתוך המסמך](#פתיחה), מייל <someone@example.com> ו-[טלפון](tel:+972501234567).',
  'הערה[^1].',
  '',
  '[ref]: https://example.com/ref',
  '',
  '[^1]: תוכן ההערה.',
  '',
].join('\n');

// ---------------------------------------------------------------------------
// הכלל — אותה טבלה כמו בצד השרת
// ---------------------------------------------------------------------------

console.log('הכלל: opensInNewTab מול tests/fixtures/md_link_target_cases.json');
{
  check('הטבלה לא ריקה', CASES.length > 0, CASES.length);
  const wrong = CASES.filter(([href, expected]) => linkTargetPlugin.opensInNewTab(href) !== expected)
    .map(([href, expected, why]) => `${JSON.stringify(href)} → ${!expected} (${why})`);
  check('כל המקרים בטבלה', wrong.length === 0, wrong);
  check('null ו-undefined אינם נפתחים', !linkTargetPlugin.opensInNewTab(null) && !linkTargetPlugin.opensInNewTab(undefined));
}

// ---------------------------------------------------------------------------
// הרינדור
// ---------------------------------------------------------------------------

console.log('רינדור: קישור לעמוד נפתח בלשונית חדשה, ועוגן נשאר');
{
  const links = anchors(renderer(true).render(SAMPLE));
  const byHref = (href) => links.filter((a) => a.href === href);
  const newTab = (a) => a.target === '_blank' && a.rel === 'noopener noreferrer';

  for (const href of [
    'https://example.com/docs', 'https://example.com/guide', 'https://example.com/auto', 'https://example.com/ref', 'docs/a.md',
  ]) {
    const found = byHref(href);
    check(`${href}: target="_blank" ו-rel="noopener noreferrer"`, found.length === 1 && newTab(found[0]), found);
  }
  for (const href of ['mailto:someone@example.com', 'tel:+972501234567']) {
    const found = byHref(href);
    check(`${href}: בלי target ובלי rel`, found.length === 1 && found[0].target === null && found[0].rel === null, found);
  }

  // העוגנים מזוהים לפי הטקסט שלהם: הכתובת של כותרת בעברית יוצאת מקודדת (``#%D7%A4...``).
  const fragments = links.filter((a) => (a.href || '').startsWith('#'));
  const texts = fragments.map((a) => a.text);
  // בלי זה, דגימה שלא ייצרה עוגנים — למשל אחרי שינוי באחד התוספים — הייתה עוברת.
  const kinds = { '¶': '¶ של כותרת', 'פתיחה': 'תוכן עניינים', 'בתוך המסמך': 'קישור פנימי', '[1]': 'הערת שוליים', '↩︎': 'חזרה מהערה' };
  const absent = Object.keys(kinds).filter((text) => !texts.includes(text)).map((text) => kinds[text]);
  check('נוצרו ¶, תוכן עניינים, קישור פנימי והערות שוליים — כולם עוגנים', absent.length === 0, { absent, fragments });
  const opened = fragments.filter((a) => a.target !== null || a.rel !== null);
  check('אף עוגן לא מקבל target או rel', opened.length === 0, opened);
}

console.log('רינדור: כלל link_open שהוגדר לפני התוסף ממשיך לרוץ');
{
  const md = new MarkdownIt();
  md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
    tokens[idx].attrSet('data-earlier', '1');
    return self.renderToken(tokens, idx, options);
  };
  md.use(linkTargetPlugin);
  const html = md.renderInline('[a](https://example.com)');
  check('הכלל הקודם והתוסף חלים שניהם', /data-earlier="1"/.test(html) && /target="_blank"/.test(html), html);
}

// ---------------------------------------------------------------------------
// חיווט
// ---------------------------------------------------------------------------

function walk(dir, accept) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...walk(full, accept));
    else if (accept(entry.name)) out.push(full);
  }
  return out;
}

console.log('חיווט: כל מקום שיוצר markdown-it מתקין את התוסף');
{
  // כל רנדרר בוובאפ נוצר עם ``linkify: true`` (``tests/md-linkify-plugin.test.js`` מחייב שם את התוסף האח לכל אחד מהם),
  // ולכן זה הסימן ליצירה. הבאנדל הוא markdown-it עצמו, והתוסף האח מזכיר את ``linkify: true`` בהסבר שלו.
  const sources = [
    ...walk(path.join(ROOT, 'webapp', 'templates'), (name) => name.endsWith('.html')),
    ...walk(path.join(ROOT, 'webapp', 'static'), (name) => name.endsWith('.js') && !name.endsWith('.bundle.js')),
  ].filter((file) => file !== MODULE_PATH && !file.endsWith('md-linkify-plugin.js'));
  const sites = [];
  const missing = [];
  for (const file of sources) {
    const src = fs.readFileSync(file, 'utf8');
    const creations = (src.match(/\blinkify\s*:\s*true\b/g) || []).length;
    if (!creations) continue;
    const rel = path.relative(ROOT, file);
    sites.push(rel);
    const installs = (src.match(/\.use\(\s*window\.MdLinkTargetPlugin\s*\)/g) || []).length;
    if (installs < creations) missing.push(`${rel} (${creations} יצירות, ${installs} התקנות)`);
  }
  const expected = [
    path.join('webapp', 'templates', 'md_preview.html'),
    path.join('webapp', 'static', 'js', 'live-preview.js'),
    path.join('webapp', 'static', 'js', 'repo-browser.js'),
  ];
  check('הסריקה מצאה את המקומות הידועים', expected.every((rel) => sites.includes(rel)), sites);
  check('כל מקום שיוצר markdown-it מתקין את התוסף', missing.length === 0, missing);
}

console.log('חיווט: כל תבנית שמארחת רנדרר טוענת את התוסף');
{
  // אותה הגדרה של "מארחת רנדרר" כמו ב-``tests/md-linkify-plugin.test.js``: טוענת את ``md-mark-plugin.js`` או את
  // ``live-preview.js``.
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
    const plugin = src.search(/<script[^>]*js\/md-link-target-plugin\.js'\) \}\}\?v=\{\{ static_version \}\}/);
    if (plugin < 0 || (live >= 0 && plugin > live)) missing.push(rel);
  }
  const expected = [
    path.join('webapp', 'templates', '_live_preview_scripts.html'),
    path.join('webapp', 'templates', 'files.html'),
    path.join('webapp', 'templates', 'md_preview.html'),
    path.join('webapp', 'templates', 'repo', 'base_repo.html'),
  ];
  check('הסריקה מצאה את התבניות הידועות', expected.every((rel) => hosts.includes(rel)), hosts);
  check('כולן טוענות את md-link-target-plugin.js עם ?v={{ static_version }}, לפני live-preview.js',
    missing.length === 0, missing);
}

// ---------------------------------------------------------------------------
// בקרה: בלי התוסף. בדיקה שאינה נופלת שם אינה בודקת כלום.
// ---------------------------------------------------------------------------

console.log('בקרה — בלי התוסף');
{
  const links = anchors(renderer(false).render(SAMPLE));
  const pages = links.filter((a) => linkTargetPlugin.opensInNewTab(a.href));
  check('יש בדגימה קישורים לעמודים', pages.length >= 5, pages);
  const withTarget = links.filter((a) => a.target !== null);
  check('אף קישור לא יוצא עם target — markdown-it לא מוסיף אותו בעצמו', withTarget.length === 0, withTarget);
}

console.log(`\n${passed} עברו, ${failed} נכשלו`);
if (failed) process.exit(1);
