/**
 * טסטים ל-webapp/static/js/md-anchors.js — עוגני HTML מפורשים במסמכי Markdown.
 *
 * הרצה:  node tests/md-anchors.test.js
 * (בריפו אין כרגע runner מוגדר ל-JS, ולכן הקובץ עצמאי ומחזיר קוד יציאה 1 בכישלון.)
 *
 * הקובץ הנבדק נטען כמו בדפדפן — script קלאסי שמגדיר window.MdAnchors — כי package.json
 * מוגדר "type": "module" ולכן require() רגיל לא היה עובד עליו.
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'md-anchors.js');

function loadMdAnchors() {
  const code = fs.readFileSync(MODULE_PATH, 'utf8');
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(code, sandbox);
  return sandbox.window.MdAnchors;
}

const { extractExplicitAnchors, sanitizeAnchorId } = loadMdAnchors();

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

console.log('עוגן בתוך שורת הכותרת');
{
  const r = extractExplicitAnchors('## 1. תקשורת <a id="communication"></a>');
  check('התגית הוסרה מטקסט הכותרת', r.source === '## 1. תקשורת', r.source);
  check('המזהה נאסף לכותרת הראשונה',
    JSON.stringify(r.anchors) === '[{"headingIndex":0,"ids":["communication"]}]', r.anchors);
}

console.log('עוגן בשורה נפרדת לפני הכותרת (דפוס GitHub)');
{
  const r = extractExplicitAnchors('<a name="intro"></a>\n## מבוא');
  check('שורת העוגן הוסרה', r.source === '## מבוא', r.source);
  check('העוגן שויך לכותרת שאחריו', r.anchors[0] && r.anchors[0].ids[0] === 'intro', r.anchors);
}

console.log('בלוק קוד — אין לגעת בתוכן');
{
  const src = '```html\n## לא כותרת <a id="nope"></a>\n```';
  const r = extractExplicitAnchors(src);
  check('המקור לא שונה', r.source === src, r.source);
  check('לא נאספו עוגנים', r.anchors.length === 0, r.anchors);
}

console.log('מסמך ללא עוגנים');
{
  const src = '# כותרת\n\nטקסט רגיל עם <b>לא-עוגן</b>.';
  const r = extractExplicitAnchors(src);
  check('המקור לא שונה', r.source === src, r.source);
  check('לא נאספו עוגנים', r.anchors.length === 0, r.anchors);
}

console.log('כמה עוגנים לאותה כותרת, כולל גרש בודד');
{
  const r = extractExplicitAnchors("## API <a id='api'></a><a name='rest'></a>");
  check('שני המזהים נאספו לפי הסדר',
    JSON.stringify(r.anchors[0].ids) === '["api","rest"]', r.anchors);
  check('הכותרת נוקתה', r.source === '## API', r.source);
}

console.log('אינדוקס כותרות');
{
  const r = extractExplicitAnchors('# A\n## B <a id="b"></a>\n### C');
  check('העוגן שויך לכותרת השנייה (index=1)', r.anchors[0].headingIndex === 1, r.anchors);
}

console.log('כותרות Setext — חייבות להיספר כדי שהאינדקס יתאים ל-h1..h6 בפועל');
{
  // markdown-it מייצר כאן h1 (Setext) ואז h2 (ATX) — העוגן שייך לכותרת index=1
  const r = extractExplicitAnchors('מבוא\n====\n\nטקסט.\n\n## תקשורת <a id="communication"></a>');
  check('העוגן שויך לכותרת השנייה', r.anchors[0] && r.anchors[0].headingIndex === 1, r.anchors);
  check('הכותרת נוקתה מהתגית', r.source.includes('## תקשורת') && !r.source.includes('<a id'), r.source);
}
{
  // עוגן בתוך שורת הטקסט של כותרת Setext עצמה
  const r = extractExplicitAnchors('תקשורת <a id="comm"></a>\n-------\n\nטקסט.');
  check('עוגן בכותרת Setext נאסף', r.anchors[0] && r.anchors[0].ids[0] === 'comm', r.anchors);
  check('index=0 לכותרת הראשונה', r.anchors[0].headingIndex === 0, r.anchors);
  check('שורת הטקסט נוקתה', r.source.split('\n')[0] === 'תקשורת', r.source);
}
{
  // עוגן בשורה נפרדת לפני כותרת Setext
  const r = extractExplicitAnchors('<a name="intro"></a>\nמבוא\n====');
  check('שויך לכותרת Setext', r.anchors[0] && r.anchors[0].ids[0] === 'intro', r.anchors);
  check('שורת העוגן הוסרה', r.source === 'מבוא\n====', r.source);
}
{
  // ערבוב: Setext, ATX, Setext — שלוש כותרות, העוגן על השלישית
  const r = extractExplicitAnchors('A\n===\n\n## B\n\nC <a id="c"></a>\n---');
  check('שלוש כותרות — העוגן על index=2', r.anchors[0].headingIndex === 2, r.anchors);
}
{
  // setext=false (כש-lheading מנוטרל) — לא סופרים כותרות Setext
  const r = extractExplicitAnchors('מבוא\n====\n\n## תקשורת <a id="x"></a>', { setext: false });
  check('בלי Setext האינדקס הוא 0', r.anchors[0].headingIndex === 0, r.anchors);
}

console.log('Setext — הימנעות מזיהוי שגוי');
{
  // "---" אחרי שורה ריקה הוא קו מפריד (hr), לא כותרת
  const r = extractExplicitAnchors('טקסט.\n\n---\n\n## כותרת <a id="k"></a>');
  check('hr לא נספר ככותרת', r.anchors[0].headingIndex === 0, r.anchors);
}
{
  // שורת הפרדה של טבלה אינה קו תחתון של Setext
  const r = extractExplicitAnchors('| a | b |\n|---|---|\n| 1 | 2 |\n\n## כותרת <a id="t"></a>');
  check('טבלה לא נספרת ככותרת', r.anchors[0].headingIndex === 0, r.anchors);
}
{
  // פריט רשימה שאחריו --- אינו כותרת Setext
  const r = extractExplicitAnchors('- פריט\n---\n\n## כותרת <a id="l"></a>');
  check('פריט רשימה לא נספר ככותרת', r.anchors[0].headingIndex === 0, r.anchors);
}

console.log('סניטציה של מזהה');
{
  check('סולמית מובילה מוסרת', sanitizeAnchorId('#intro') === 'intro');
  check('רווחים וגרשיים מוסרים', sanitizeAnchorId('  my id  ') === 'myid');
  check('גרשיים מסולסלים מוסרים', sanitizeAnchorId('“x”') === 'x');
  check('ערך ריק מוחזר כמחרוזת ריקה', sanitizeAnchorId(null) === '');
}

// ---- applyExplicitAnchors: נבדק מול DOM מינימלי מדומה (אין jsdom בריפו) ----

function makeFakeDom(headingCount) {
  const byId = new Map();
  const doc = {
    getElementById: (id) => byId.get(id) || null,
    createElement: () => ({
      className: '',
      _id: '',
      attrs: {},
      get id() { return this._id; },
      set id(v) { this._id = v; if (v) byId.set(v, this); },
      setAttribute(k, v) { this.attrs[k] = v; },
    }),
  };
  const inserted = [];  // [{beforeIndex, id}]
  const headings = [];
  for (let i = 0; i < headingCount; i++) {
    const h = {
      index: i,
      ownerDocument: doc,
      parentNode: {
        insertBefore: (node, ref) => { inserted.push({ beforeIndex: ref.index, id: node.id }); },
      },
    };
    headings.push(h);
  }
  const container = { querySelectorAll: () => headings };
  return { container, inserted, doc };
}

console.log('applyExplicitAnchors — הוספת יעדי עוגן ל-DOM');
{
  const { applyExplicitAnchors } = loadMdAnchors();
  const { container, inserted } = makeFakeDom(3);
  const count = applyExplicitAnchors(container, [
    { headingIndex: 1, ids: ['communication'] },
    { headingIndex: 2, ids: ['api', 'rest'] },
  ]);
  check('הוחלו שלושה עוגנים', count === 3, count);
  check('העוגן הוכנס לפני הכותרת הנכונה',
    inserted[0].beforeIndex === 1 && inserted[0].id === 'communication', inserted);
  check('שני עוגנים לאותה כותרת', inserted.length === 3 && inserted[2].id === 'rest', inserted);
}

console.log('applyExplicitAnchors — לא דורס מזהה תפוס');
{
  const { applyExplicitAnchors } = loadMdAnchors();
  const { container, inserted, doc } = makeFakeDom(2);
  doc.getElementById = (id) => (id === 'taken' ? {} : null);
  const count = applyExplicitAnchors(container, [{ headingIndex: 0, ids: ['taken'] }]);
  check('מזהה קיים לא נדרס', count === 0 && inserted.length === 0, inserted);
}

console.log('applyExplicitAnchors — קלט ריק לא מפיל');
{
  const { applyExplicitAnchors } = loadMdAnchors();
  check('null container', applyExplicitAnchors(null, [{ headingIndex: 0, ids: ['x'] }]) === 0);
  check('רשימה ריקה', applyExplicitAnchors(makeFakeDom(1).container, []) === 0);
}

console.log('\nסה"כ: ' + passed + ' עברו, ' + failed + ' נכשלו');
process.exit(failed === 0 ? 0 : 1);
