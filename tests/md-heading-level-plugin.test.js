/**
 * טסטים ל-webapp/static/js/md-heading-level-plugin.js — כותרת עמוקה מהמגבלה מוצגת כפסקה, כמו שנכתבה.
 *
 * הרצה:  node tests/md-heading-level-plugin.test.js
 * (בריפו אין runner מוגדר ל-JS, ולכן הקובץ עצמאי ומחזיר קוד יציאה 1 בכישלון.)
 *
 * הקובץ הנבדק נטען כמו בדפדפן — script קלאסי שמגדיר ``window.MdHeadingLevel`` — כי ``package.json`` מוגדר
 * ``"type": "module"`` ולכן ``require()`` רגיל לא היה עובד עליו. ה-renderer הוא markdown-it מ-``node_modules``, אותה
 * גרסה שבחבילה שהדפדפן טוען (``md_preview.bundle.js``).
 *
 * והחוזה עם ``md-anchors.js``: הפסקה מסומנת, ונשארת יעד לעוגן מפורש. החיווט — ששני הרנדררים טוענים את התוסף —
 * נבדק ב-``tests/sticky-notes-target.test.js``,
 * וההתנהגות בדפדפן ב-``tests/test_md_preview_heading_level_browser.py`` (תצוגת המסמך) וב-
 * ``tests/test_markdown_editor_browser.py`` (התצוגה החיה).
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';
import MarkdownIt from 'markdown-it';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'md-heading-level-plugin.js');

function loadPlugin() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox.window.MdHeadingLevel;
}

const MdHeadingLevel = loadPlugin();

function loadMdAnchors() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'webapp', 'static', 'js', 'md-anchors.js'), 'utf8'), sandbox);
  return sandbox.window.MdAnchors;
}

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

function renderer(maxLevel) {
  return new MarkdownIt().use(MdHeadingLevel.plugin, { maxLevel });
}

console.log('המגבלה של תצוגת המסמך: כותרות עד H4, ו-H5/H6 כפסקה');
{
  const html = renderer(MdHeadingLevel.DOCUMENT_MAX_LEVEL).render(
    '# א\n\n## ב\n\n### ג\n\n#### ד\n\n##### ה\n\n###### ו\n'
  );
  check('H1 עד H4 נשארות כותרות',
    ['<h1>א</h1>', '<h2>ב</h2>', '<h3>ג</h3>', '<h4>ד</h4>'].every((h) => html.includes(h)), html);
  check('H5 היא פסקה עם הסולמיות, מסומנת ברמה שבה נכתבה',
    html.includes('<p data-md-heading-level="5">##### ה</p>') && !html.includes('<h5'), html);
  check('H6 היא פסקה עם הסולמיות, מסומנת ברמה שבה נכתבה',
    html.includes('<p data-md-heading-level="6">###### ו</p>') && !html.includes('<h6'), html);
}

console.log('הטקסט של הכותרת מפוענח כטקסט רגיל — הכלל רץ לפני פענוח השורה');
{
  const html = renderer(4).render('##### **מודגש** ו-`קוד`\n');
  check('הדגשה וקוד בשורה מרונדרים בתוך הפסקה',
    html.trim() === '<p data-md-heading-level="5">##### <strong>מודגש</strong> ו-<code>קוד</code></p>', html);
}

console.log('כותרת ריקה');
{
  const html = renderer(4).render('#####\n');
  check('נשארת הסולמיות לבדה', html.trim() === '<p data-md-heading-level="5">#####</p>', html);
}

console.log('מפת השורות נשמרת — data-source-line של תצוגת המסמך נגזר ממנה');
{
  const tokens = renderer(4).parse('# א\n\n##### ה\n', {});
  const open = tokens.find((t) => t.type === 'paragraph_open');
  check('לפסקה שנוצרה יש את השורה של הכותרת', open && JSON.stringify(open.map) === '[2,3]', open && open.map);
  check('אין טוקן כותרת ברמה 5', !tokens.some((t) => t.type === 'heading_open' && t.tag === 'h5'));
}

console.log('מגבלה אחרת חלה בדיוק כמו שנמסרה');
{
  const html = renderer(2).render('## ב\n\n### ג\n');
  check('עם מגבלה 2, H3 היא פסקה', html.includes('<h2>ב</h2>') && html.includes('<p data-md-heading-level="3">### ג</p>'), html);
  const all = renderer(6).render('###### ו\n');
  check('עם מגבלה 6, H6 נשארת כותרת', all.includes('<h6>ו</h6>'), all);
}

console.log('הפסקה נשארת יעד לעוגן מפורש — החוזה עם md-anchors.js');
{
  // ``applyExplicitAnchors`` מחיל עוגן על היעד לפי האינדקס שהחילוץ סופר: כותרות, ופסקאות שהיו כותרות. השם של
  // הסימון כתוב בשני הקבצים, ולכן נבדק שהוא אותו שם.
  const MdAnchors = loadMdAnchors();
  check('ANCHOR_TARGETS ב-md-anchors.js מחפש את הסימון של התוסף',
    MdAnchors.ANCHOR_TARGETS.split(',').map((t) => t.trim()).includes(`[${MdHeadingLevel.MARKER_ATTRIBUTE}]`),
    MdAnchors.ANCHOR_TARGETS);

  // מקצה לקצה: חילוץ, רינדור עם התוסף, והיעדים ב-HTML לפי הסדר — כמו ש-``querySelectorAll`` מחזיר אותם.
  const src = '# ראשית\n\n<a id="before5"></a>\n##### עמוקה\n\n###### שישית <a id="inline6"></a>\n\n## יעד <a id="after"></a>\n';
  const extracted = MdAnchors.extractExplicitAnchors(src);
  const html = renderer(MdHeadingLevel.DOCUMENT_MAX_LEVEL).render(extracted.source);
  const targets = [...html.matchAll(/<(h[1-6])>([^<]*)<\/h[1-6]>|<p data-md-heading-level="\d">([^<]*)<\/p>/g)]
    .map((m) => (m[2] !== undefined ? m[2] : m[3]).trim());
  const landing = {};
  extracted.anchors.forEach((a) => a.ids.forEach((id) => { landing[id] = targets[a.headingIndex]; }));
  check('עוגן בשורה שלפני H5 נוחת על הפסקה שלה', landing.before5 === '##### עמוקה', { landing, targets });
  check('עוגן בתוך שורת H6 נוחת על הפסקה שלה', landing.inline6 === '###### שישית', { landing, targets });
  check('עוגן של הכותרת שאחריהן נוחת עליה', landing.after === 'יעד', { landing, targets });
  check('התגית לא נשארת בטקסט', html.indexOf('&lt;a') === -1 && html.indexOf('<a ') === -1, html);
}

console.log('מגבלה חסרה או שגויה — חריגה, ולא renderer שהופך כל כותרת לפסקה');
{
  [undefined, 0, 7, 4.5, '4', null].forEach((value) => {
    let threw = false;
    try {
      new MarkdownIt().use(MdHeadingLevel.plugin, { maxLevel: value });
    } catch (_) {
      threw = true;
    }
    check(`maxLevel=${JSON.stringify(value)} זורק`, threw);
  });
  let threw = false;
  try {
    new MarkdownIt().use(MdHeadingLevel.plugin);
  } catch (_) {
    threw = true;
  }
  check('בלי אפשרויות בכלל — זורק', threw);
}

console.log(`\n${passed} עברו, ${failed} נכשלו`);
if (failed) process.exit(1);
