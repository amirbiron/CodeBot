'use strict';
/**
 * בדיקות לשם קובץ בשורה עברית — ``webapp/static/js/utils/file-name.js`` (``window.FileName``): מתי שם מפורק לשם
 * ולסיומת (``parts``), איזה ``<bdi>`` נבנה ממנו (``element`` / ``fill``), ושהטבלאות של "עברית" ו"לטינית" מכסות את מה
 * ש-Node מכיר כאותיות בכתבים האלה.
 *
 * הרצה:  node tests/file-name.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * **מה הבדיקות האלה כן מוכיחות:** אילו שמות מפורקים ואילו נשארים כמו היום, שהפירוק מחזיר את הטקסט המקורי בדיוק, ושה-
 * ``<bdi>`` נושא את הטקסט כמו שהוא. **ומה לא:** שהשם באמת מוצג נכון על המסך — את זה מודד
 * ``tests/test_file_name_display_browser.py``; ושהתאום בפייתון מחליט אותו דבר — ``tests/test_file_name_display.py``.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const JS_DIR = path.join(__dirname, '..', 'webapp', 'static', 'js');
const MODULE_PATH = path.join(JS_DIR, 'utils', 'file-name.js');
const RTL_CODE_PATH = path.join(JS_DIR, 'utils', 'rtl-code.js');

// הקבצים הם scripts קלאסיים שמגדירים את עצמם על ``window`` — ``package.json`` מוגדר ``"type": "module"``, ולכן
// ``require()`` עליהם לא היה עובד.
function load(files, extra) {
  const sandbox = Object.assign({ window: {} }, extra || {});
  vm.createContext(sandbox);
  for (const file of files) vm.runInContext(fs.readFileSync(file, 'utf8'), sandbox);
  return sandbox;
}

const F = load([MODULE_PATH]).window.FileName;

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(actual, expected, what) {
  const a = JSON.stringify(actual), b = JSON.stringify(expected);
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${b}, קיבלתי ${a}`);
}

const parts = (s) => {
  const p = F.parts(s);
  return p ? [p.stem, p.extension] : null;
};

// ---------- מתי מפרקים ----------

check('שם שהחלק האחרון שלו לפני הסיומת לטיני — מפורק', () => {
  eq(parts('מדריך-תצוגת-Markdown-RTL.md'), ['מדריך-תצוגת-Markdown-RTL', 'md']);
  eq(parts('חילוץ-חיבור-וואטסאפ-myAgent.md'), ['חילוץ-חיבור-וואטסאפ-myAgent', 'md']);
  eq(parts('הצעת-דפוס-tagName-מול-SVG.md'), ['הצעת-דפוס-tagName-מול-SVG', 'md']);
});

check('שם שמתחיל באנגלית — מפורק לפי מה שלפני הסיומת, ולא לפי האות הראשונה', () => {
  eq(parts('Report-דוח-Q3.md'), ['Report-דוח-Q3', 'md']);
});

check('ספרה שצמודה לאות לטינית נחשבת חלק מהחלק הלטיני', () => {
  // ``Q3`` — הדפדפן מדביק את ``3`` ל-``Q``, ולכן גם את הנקודה. ספרות בלבד אחרי העברית אינן כאלה.
  eq(parts('דוח-Q3.json'), ['דוח-Q3', 'json']);
  eq(parts('אתר-התיעוד-RTL-דוח-שלב-1.md'), null, 'רק ספרה אחרי העברית — כבר מוצג נכון');
});

check('שם עם רווחים — מפורק כמו כל שם (שם קובץ אמיתי)', () => {
  eq(parts('המיפוי השלם בייבוא ערכת VS Code.md'), ['המיפוי השלם בייבוא ערכת VS Code', 'md']);
});

check('אות לטינית מחוץ ל-ASCII נחשבת לטינית, כמו לאלגוריתם הכיווניות', () => {
  eq(parts('תפריט-café.md'), ['תפריט-café', 'md']);
});

check('אות לטינית מחוץ ל-BMP (Latin Extended-F) נחשבת לטינית', () => {
  // U+10780 — נקודת קוד אחת שהיא שני תווים ב-UTF-16. ``parts`` עובר לפי נקודות קוד, כמו התאום בפייתון.
  eq(parts('דוח-\u{10780}.md'), ['דוח-\u{10780}', 'md']);
});

check('שם שנגמר בעברית — נשאר כמו היום', () => {
  eq(parts('ערכות.md'), null);
  eq(parts('הפניות-שלא-חלו.md'), null);
  eq(parts('pdf-עברי-ל-markdown-אפיון-גרסה-ראשונה.md'), null);
});

check('שם בלי עברית — נשאר גוש אחד משמאל לימין', () => {
  eq(parts('morass-Tech-theme.json'), null);
  eq(parts('archive.tar.gz'), null);
  eq(parts('foo()'), null);
  eq(parts('--flag'), null);
});

check('נקודה נוספת אחרי העברית — נשאר כמו היום', () => {
  eq(parts('דוח.tar.gz'), null);
  eq(parts('גרסה-1.2.md'), null);
  eq(parts('מדריך-RTL.v2.md'), null);
});

check('נתיב — נשאר כמו היום', () => {
  eq(parts('docs/מדריך/Guide-RTL.md'), null);
  eq(parts('docs/מדריך/קובץ.md'), null);
  eq(parts('תיקייה\\Guide-RTL.md'), null);
});

check('סיומת: אותיות או ספרות לטיניות, אחת עד עשר, בלי רווח, עד סוף הטקסט', () => {
  eq(parts('דוח-RTL.'), null, 'בלי סיומת');
  eq(parts('דוח-RTL.mdabcdefghi'), null, 'אחת-עשרה אותיות');
  eq(parts('דוח-RTL.mdabcdefgh'), ['דוח-RTL', 'mdabcdefgh'], 'עשר אותיות');
  eq(parts('דוח-RTL.m d'), null, 'רווח בסיומת');
  eq(parts('דוח-RTL.קובץ'), null, 'סיומת בעברית');
  eq(parts('דוח-RTL.7z'), ['דוח-RTL', '7z']);
  eq(parts('דוח-RTL.md\n'), null, 'שורה חדשה אחרי הסיומת — אין סיומת בסוף הטקסט');
});

check('משפט עברי שנגמר בשם עם נקודה — מפורק (זיהוי שגוי ידוע, שהוחלט לקבל)', () => {
  // מתועד בראש ``utils/file-name.js``: הדרישה לשם בלי רווחים הייתה פותרת את זה ושוברת שם אמיתי.
  eq(parts('התקינו את Node.js'), ['התקינו את Node', 'js']);
});

check('חיבור החלקים מחזיר את הטקסט המקורי בדיוק', () => {
  for (const s of ['מדריך-תצוגת-Markdown-RTL.md', 'Report-דוח-Q3.md', 'המיפוי השלם בייבוא ערכת VS Code.md']) {
    const p = F.parts(s);
    eq(`${p.stem}.${p.extension}`, s, s);
  }
});

check('קלט שאינו מחרוזת אינו מפיל', () => {
  eq(F.parts(null), null);
  eq(F.parts(undefined), null);
  eq(F.parts(42), null);
});

// ---------- ה-``<bdi>`` שנבנה ----------

// DOM מינימלי: מספיק כדי לראות איזה עץ ``element`` בונה, ולוודא שהטקסט נכנס רק כ-``textContent``.
function fakeDocument() {
  function text(value) { return { nodeType: 3, nodeValue: String(value) }; }
  function el(tag) {
    return {
      nodeType: 1,
      tagName: tag.toUpperCase(),
      attrs: {},
      childNodes: [],
      ownerDocument: null,
      setAttribute(k, v) { this.attrs[k] = String(v); },
      getAttribute(k) { return Object.prototype.hasOwnProperty.call(this.attrs, k) ? this.attrs[k] : null; },
      appendChild(c) { this.childNodes.push(c); return c; },
      get textContent() { return this.childNodes.map((c) => (c.nodeType === 3 ? c.nodeValue : c.textContent)).join(''); },
      set textContent(v) { this.childNodes = String(v) === '' ? [] : [text(v)]; },
      set innerHTML(_v) { throw new Error('innerHTML אסור על שמות'); },
    };
  }
  const doc = { createElement: (tag) => { const e = el(tag); e.ownerDocument = doc; return e; }, createTextNode: text };
  return doc;
}

// העץ כמחרוזת לבדיקה: תגיות, ``dir``, וטקסט כמו שהוא (בלי קידוד — אין כאן HTML אמיתי).
function shape(node) {
  if (node.nodeType === 3) return node.nodeValue;
  const dir = node.getAttribute('dir');
  return `<${node.tagName.toLowerCase()}${dir ? ` dir="${dir}"` : ''}>${node.childNodes.map(shape).join('')}</${node.tagName.toLowerCase()}>`;
}

check('שם שמפורק: <bdi dir="rtl"> עם השם והנקודה, והסיומת ב-<bdi> פנימי', () => {
  const doc = fakeDocument();
  eq(shape(F.element('מדריך-תצוגת-Markdown-RTL.md', doc)), '<bdi dir="rtl">מדריך-תצוגת-Markdown-RTL.<bdi>md</bdi></bdi>');
});

check('כל שם אחר: <bdi dir="auto"> — ``dir`` כתוב במפורש, ולא נשען על ברירת המחדל של bdi', () => {
  const doc = fakeDocument();
  eq(shape(F.element('ערכות.md', doc)), '<bdi dir="auto">ערכות.md</bdi>');
  eq(shape(F.element('_draft.md', doc)), '<bdi dir="auto">_draft.md</bdi>');
  eq(shape(F.element(null, doc)), '<bdi dir="auto"></bdi>');
});

check('הטקסט של ה-<bdi> הוא השם תו בתו — כך העתקה ו-``title`` מהטקסט נשארים נכונים', () => {
  const doc = fakeDocument();
  for (const s of ['מדריך-תצוגת-Markdown-RTL.md', 'Report-דוח-Q3.md', 'ערכות.md', '<b>&"x"</b>.md']) {
    eq(F.element(s, doc).textContent, s, s);
  }
});

check('fill מחליף את התוכן של האלמנט ב-<bdi> אחד, בלי innerHTML', () => {
  const doc = fakeDocument();
  const host = doc.createElement('h1');
  host.textContent = 'ישן';
  const returned = F.fill(host, 'Report-דוח-Q3.md');
  eq(returned === host, true, 'מחזיר את האלמנט');
  eq(host.childNodes.length, 1, 'ילד אחד');
  eq(shape(host), '<h1><bdi dir="rtl">Report-דוח-Q3.<bdi>md</bdi></bdi></h1>');
});

// ---------- הטבלאות מול ``\p{Script=…}`` ----------

function rangesOf(re) {
  const out = [];
  let start = -1;
  for (let c = 0; c <= 0x10FFFF; c++) {
    const ok = !(c >= 0xD800 && c <= 0xDFFF) && re.test(String.fromCodePoint(c));
    if (ok && start < 0) start = c;
    if (!ok && start >= 0) { out.push([start, c - 1]); start = -1; }
  }
  if (start >= 0) out.push([start, 0x10FFFF]);
  return out;
}
function inTable(table, c) { return table.some(([a, b]) => c >= a && c <= b); }
const hex = (n) => `0x${n.toString(16).toUpperCase().padStart(4, '0')}`;

// **כיוון אחד בלבד:** כל אות ש-Node הנוכחי מכיר כעברית או כלטינית נמצאת בטבלה. Node ישן יותר מכיר פחות אותיות,
// והבדיקה עוברת עליו; Node חדש שמכיר אות חדשה מפיל אותה, וההודעה מדפיסה את הטבלה המעודכנת להעתקה לשני המימושים.
for (const [name, re, table] of [
  ['HEBREW_LETTERS', /(?=\p{L})\p{Script=Hebrew}/u, F.HEBREW_LETTERS],
  ['LATIN_LETTERS', /(?=\p{L})\p{Script=Latin}/u, F.LATIN_LETTERS],
]) {
  check(`${name} מכסה כל אות ש-Node ${process.version} (יוניקוד ${process.versions.unicode}) מכיר בכתב הזה`, () => {
    const current = rangesOf(re);
    const missing = [];
    for (const [a, b] of current) for (let c = a; c <= b; c++) if (!inTable(table, c)) missing.push(hex(c));
    if (missing.length) {
      const fresh = current.map(([a, b]) => `[${hex(a)}, ${hex(b)}]`).join(', ');
      throw new Error(`חסרות ${missing.length} אותיות (${missing.slice(0, 10).join(', ')}…). הטבלה המעודכנת, ל-``${name}`` ב-utils/file-name.js וב-webapp/file_name_display.py: ${fresh}`);
    }
  });
}

check('הטבלאות ממוינות ולא חופפות (החיפוש הבינארי נשען על זה)', () => {
  for (const table of [F.HEBREW_LETTERS, F.LATIN_LETTERS]) {
    for (let i = 0; i < table.length; i++) {
      eq(table[i][0] <= table[i][1], true, `טווח ${i}`);
      if (i) eq(table[i - 1][1] < table[i][0], true, `טווח ${i} אחרי ${i - 1}`);
    }
  }
});

// ---------- מי עוד קורא את ההחלטה ----------

check('rtl-code.js קורא את הפירוק מ-FileName, ולא מחזיק עותק משלו', () => {
  const src = fs.readFileSync(RTL_CODE_PATH, 'utf8');
  eq(/Script=Hebrew|Script=Latin|\[A-Za-z0-9\]\{1,10\}/.test(src), false, 'אין ב-rtl-code.js עותק של ההחלטה');
  const sb = load([MODULE_PATH, RTL_CODE_PATH]);
  const doc = fakeDocument();
  const code = doc.createElement('code');
  sb.window.RtlCode.fillInlineCode(code, 'Report-דוח-Q3.md');
  eq(shape(code), '<code dir="rtl">Report-דוח-Q3.<bdi>md</bdi></code>', 'קוד בשורה מפורק דרך FileName.parts');
});

check('rtl-code.js בלי FileName: הקוד מוצג בלי פירוק, ואזהרה אחת בקונסול', () => {
  const warnings = [];
  const sb = load([RTL_CODE_PATH], { console: { warn: (m) => warnings.push(String(m)) } });
  const doc = fakeDocument();
  for (let i = 0; i < 2; i++) {
    const code = doc.createElement('code');
    sb.window.RtlCode.fillInlineCode(code, 'Report-דוח-Q3.md');
    eq(shape(code), '<code dir="auto">Report-דוח-Q3.md</code>');
  }
  eq(warnings.length, 1, 'אזהרה אחת');
});

console.log(`file names: ${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
