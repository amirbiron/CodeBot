'use strict';
// בדיקות ל-``highlightInto`` שב-``webapp/static/js/notes_search.js``.
//
// **הפונקציה נטענת מהמקור, ולא משוכפלת כאן.** הקובץ הוא IIFE שנתלה על
// אלמנטים בעמוד, ולכן הוא מורץ בתוך sandbox של ``vm`` עם DOM מינימלי —
// ואז הפונקציה נמשכת מתוכו. העתקה של גוף הפונקציה לכאן הייתה בודקת את
// ההעתק, וזה בדיוק מה ש-``repo-history.test.js`` עושה והוחרג בגללו ב-CI.
//
// ה-DOM כאן הוא **צמתים אמיתיים בזעיר אנפין**: ``appendChild``,
// ``textContent`` ו-``createElement``. זה מספיק כי הפונקציה הנבדקת אינה
// נוגעת בכלום מעבר להם — ובדיוק בגלל זה. אילו היא הייתה משרשרת מחרוזות
// HTML, DOM כזה לא היה יכול לבדוק אותה, וזו עוד סיבה שהיא לא.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(
  path.join(__dirname, '..', 'webapp', 'static', 'js', 'notes_search.js'), 'utf8');

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(actual, expected, msg) {
  const a = JSON.stringify(actual), b = JSON.stringify(expected);
  if (a !== b) { throw new Error(`${msg || ''}: ${a} !== ${b}`); }
}

// ---------------------------------------------------------------------------
// DOM זעיר
// ---------------------------------------------------------------------------

class Node {
  constructor(tag) { this.tagName = tag; this.children = []; this.className = ''; }
  appendChild(c) { this.children.push(c); return c; }
  set textContent(v) { this.children = [{ tagName: '#text', text: String(v) }]; }
  get textContent() { return this.children.map(c => c.tagName === '#text' ? c.text : c.textContent).join(''); }
}

function makeDocument() {
  return {
    createElement: (tag) => new Node(tag.toUpperCase()),
    createTextNode: (text) => ({ tagName: '#text', text: String(text) }),
    createDocumentFragment: () => new Node('#fragment'),
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
  };
}

/** מחלץ את ``highlightInto`` מתוך הקובץ האמיתי, בלי להעתיק את גופה. */
function loadHighlight() {
  const doc = makeDocument();
  const sandbox = {
    document: doc,
    window: { location: { search: '' }, history: { replaceState() {} } },
    URLSearchParams,
    CSS: { escape: (s) => String(s) },
    fetch: () => Promise.resolve({ json: () => Promise.resolve({}) }),
    console,
    __exported: null,
  };
  sandbox.window.document = doc;
  // הקובץ מחזיר מוקדם כשהאלמנטים אינם קיימים (``if (!form ...) return``),
  // ולכן הוא נטען כאן כפונקציה שמחזירה את מה שהוגדר בתוכה. המקור נשאר
  // בדיוק כפי שהוא — רק עטוף.
  const wrapped = SRC.replace(
    'if (!form || !input || !list) { return; }',
    'if (!form || !input || !list) { __exported = { highlightInto: highlightInto, escapeRegex: escapeRegex }; return; }'
  );
  if (wrapped === SRC) { throw new Error('נקודת החילוץ לא נמצאה — הקובץ השתנה'); }
  vm.createContext(sandbox);
  vm.runInContext(wrapped, sandbox);
  if (!sandbox.__exported) { throw new Error('הפונקציות לא נחשפו'); }
  return sandbox;
}

const { highlightInto } = loadHighlight().__exported;

function run(text, query) {
  const box = new Node('SPAN');
  const hits = highlightInto(box, text, query);
  return { hits, box, marks: box.children.filter(c => c.tagName === 'MARK') };
}

// ---------------------------------------------------------------------------

check('מסמן כל מופע ומחזיר את מספרם', () => {
  const r = run('פתק ועוד פתק ושוב פתק', 'פתק');
  eq(r.hits, 3, 'שלושה מופעים');
  eq(r.marks.length, 3, 'שלושה <mark>');
  eq(r.box.textContent, 'פתק ועוד פתק ושוב פתק', 'הטקסט נשמר במלואו');
});

check('אפס מופעים מדווח כאפס — וזה מה שמדליק את הרמז', () => {
  // **ערך ההחזרה אינו קישוט.** הוא מה שקובע אם מוצג "המילה מופיעה בהמשך
  // הפתק", והמקרה הזה הוא הנפוץ: גוף הפתק הממוצע ארוך פי כמה מ-200 התווים
  // שמוצגים, ולכן פתק שנמצא בזכות מילה מאוחרת מגיע לכאן בלי אף מופע.
  const r = run('תצוגה מקדימה שאין בה כלום', 'מיגרציה');
  eq(r.hits, 0, 'אין מופעים');
  eq(r.marks.length, 0, 'ואין סימון');
  eq(r.box.textContent, 'תצוגה מקדימה שאין בה כלום', 'והטקסט עדיין מוצג');
});

check('חסר רישיות, כמו ה-$options: "i" בשרת', () => {
  const r = run('Config ו-CONFIG ו-config', 'config');
  eq(r.hits, 3, 'שלושתם');
});

check('תווי רג\'קס במחט הם ליטרליים', () => {
  // בלי בריחה, ``config.py`` היה תופס גם ``configXpy`` — כלומר הדגשה על
  // טקסט שהשרת כלל לא התאים.
  eq(run('ראו config.py', 'config.py').hits, 1, 'הליטרל נתפס');
  eq(run('ראו configXpy', 'config.py').hits, 0, 'והנקודה אינה תו כללי');
  eq(run('הביטוי a( נשבר', 'a(').hits, 1, 'סוגר פתוח אינו מפיל');
  eq(run('a+b', 'a+b').hits, 1, 'פלוס הוא פלוס');
});

check('HTML בתוכן נשאר טקסט, ולא הופך לאלמנט', () => {
  // הצומת היחיד שנוצר הוא ``<mark>`` שאנחנו יצרנו. כל השאר צמתי טקסט —
  // ולכן ``<img onerror=…>`` אינו יכול לרוץ. זה ``bugbot-rules/xss-innerhtml``.
  const payload = '<img src=x onerror="alert(1)"> מיגרציה "ציטוט" & עוד';
  const r = run(payload, 'מיגרציה');
  const tags = r.box.children.map(c => c.tagName);
  eq(tags.filter(t => t !== '#text' && t !== 'MARK').length, 0, 'לא נוצר שום אלמנט זר');
  eq(r.box.textContent, payload, 'כולל המרכאות והאמפרסנד, בדיוק כפי שהגיעו');
});

check('מחט ריקה מציגה את הטקסט בלי לסמן דבר', () => {
  const r = run('טקסט כלשהו', '');
  eq(r.hits, 0, 'אין מופעים');
  eq(r.box.textContent, 'טקסט כלשהו', 'והטקסט שלם');
});

check('טקסט ריק אינו מפיל', () => {
  eq(run('', 'מיגרציה').hits, 0, 'אפס');
  eq(run(null, 'מיגרציה').hits, 0, 'גם null');
});

check('מופע בתחילת המחרוזת ובסופה', () => {
  const r = run('פתק באמצע פתק', 'פתק');
  eq(r.hits, 2, 'שניים');
  eq(r.box.children.map(c => c.tagName), ['MARK', '#text', 'MARK'], 'בלי צומת ריק בהתחלה');
});

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
