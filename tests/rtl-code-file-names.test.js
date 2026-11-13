'use strict';
/**
 * בדיקות להחלטה מתי שם קובץ עברי מפורק לשם ולסיומת — ``fileNameParts`` ב-
 * ``webapp/static/js/utils/rtl-code.js``. שם שמפורק מוצג עם הסיומת מבודדת ב-``<bdi>``, בתוך אלמנט
 * ``dir="rtl"``, ולכן הסיומת יושבת בקצה השמאלי ולא באמצע השם.
 *
 * הרצה:  node tests/rtl-code-file-names.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * **מה הבדיקות האלה כן מוכיחות:** אילו שמות מפורקים ואילו נשארים כמו היום, ושהפירוק מחזיר את הטקסט
 * המקורי בדיוק כשמחברים אותו בחזרה. **ומה לא:** שהשם באמת מוצג נכון על המסך — את זה מודדים
 * ``tests/test_sticky_inline_code_dir_browser.py`` ו-``tests/test_md_auto_dir_browser.py``.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'utils', 'rtl-code.js');

// הקובץ הוא script קלאסי שמגדיר ``window.RtlCode`` — ``package.json`` מוגדר
// ``"type": "module"``, ולכן ``require()`` עליו לא היה עובד.
function loadRtlCode() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox.window.RtlCode;
}

const R = loadRtlCode();

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
  const p = R.fileNameParts(s);
  return p ? [p.stem, p.extension] : null;
};

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

check('סיומת: אותיות או ספרות לטיניות, אחת עד עשר, בלי רווח', () => {
  eq(parts('דוח-RTL.'), null, 'בלי סיומת');
  eq(parts('דוח-RTL.mdabcdefghi'), null, 'אחת-עשרה אותיות');
  eq(parts('דוח-RTL.mdabcdefgh'), ['דוח-RTL', 'mdabcdefgh'], 'עשר אותיות');
  eq(parts('דוח-RTL.m d'), null, 'רווח בסיומת');
  eq(parts('דוח-RTL.קובץ'), null, 'סיומת בעברית');
  eq(parts('דוח-RTL.7z'), ['דוח-RTL', '7z']);
});

check('משפט עברי שנגמר בשם עם נקודה — מפורק (זיהוי שגוי ידוע, שהוחלט לקבל)', () => {
  // מתועד ב-docblock של ``fileNameParts``: הדרישה לשם בלי רווחים הייתה פותרת את זה ושוברת שם אמיתי.
  eq(parts('התקינו את Node.js'), ['התקינו את Node', 'js']);
});

check('חיבור החלקים מחזיר את הטקסט המקורי בדיוק', () => {
  for (const s of ['מדריך-תצוגת-Markdown-RTL.md', 'Report-דוח-Q3.md', 'המיפוי השלם בייבוא ערכת VS Code.md']) {
    const p = R.fileNameParts(s);
    eq(`${p.stem}.${p.extension}`, s, s);
  }
});

check('קלט שאינו מחרוזת אינו מפיל', () => {
  eq(R.fileNameParts(null), null);
  eq(R.fileNameParts(undefined), null);
  eq(R.fileNameParts(42), null);
});

console.log(`rtl-code file names: ${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
