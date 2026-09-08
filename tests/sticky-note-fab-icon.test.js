'use strict';
// שומר טקסטואלי על האייקון של כפתור הפתק הצף.
//
// **מה הוחלף:** התו ``+`` שהיה תוכן הטקסט של ``.sticky-note-fab`` הוחלף
// באייקון SVG של שני פתקים עם תג "+", והעיגול הלבן שסביבו ירד. הכפתור
// מוגדר במקום אחד בלבד בכל הריפו (``_createFab`` ב-``sticky-notes.js``),
// ומשרת שלושה הקשרים: תצוגת Markdown, לוחות פתקים, ודפדפן הריפו.
//
// **מה נמדד בדפדפן** (Chromium מול שרת Flask אמיתי + MongoDB):
// בתצוגת Markdown ובלוח — svg יחיד, 7 צורות, מרונדר 46×46, ממורכז ב-0px,
// ולחיצה יוצרת פתק. ריצת בקרה על הקוד שלפני השינוי הפילה 13 טענות
// והשאירה את טענת "הלחיצה יוצרת פתק" ירוקה.
//
// **למה טסט טקסטואלי ולא מדידה:** Playwright אינו בתלויות הפרויקט, ולכן
// הארנס שמרים שרת ודפדפן לא ירוץ ב-CI. הטסט הזה לא מודד מחדש — הוא שומר
// על ההחלטות שהמדידה אישרה, ובראשן שתיים שקל לשבור בשקט:
// שם המחלקה שעליו ``destroy()`` נשען, והמרכוז שבלעדיו האייקון קופץ.

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const JS_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'sticky-notes.js');
const CSS_PATH = path.join(__dirname, '..', 'webapp', 'static', 'css', 'sticky-notes.css');
const JS = fs.readFileSync(JS_PATH, 'utf8');
const CSS = fs.readFileSync(CSS_PATH, 'utf8');

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed++; console.log(`  ✓ ${name}`); }
  catch (e) { failed++; console.error(`  ✗ ${name}\n    ${e.message}`); }
}
function ok(cond, msg) { if (!cond) throw new Error(msg); }

/** גוף הפונקציה ``name`` בתוך ``src``, לפי סוגריים מסולסלים מאוזנים. */
function bodyOf(src, name) {
  const i = src.indexOf(name);
  if (i === -1) return '';
  const open = src.indexOf('{', i);
  if (open === -1) return '';
  let depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (depth === 0) return src.slice(open + 1, j); }
  }
  return '';
}

// ---------------------------------------------------------------------------
// הטענות, ככלים שאפשר להריץ על כל טקסט — כדי שהמוטציות יריצו בדיוק אותן.
// ---------------------------------------------------------------------------

/** 1. הכפתור מקבל אייקון, ולא את התו ``+``. */
function assertIconNotPlusText(js) {
  const body = bodyOf(js, '_createFab(){');
  ok(body, 'לא נמצאה הפונקציה _createFab');
  ok(!/textContent\s*=\s*['"`]\+['"`]/.test(body),
    'הכפתור חזר להיות התו "+" בטקסט במקום אייקון');
  ok(/appendChild\(\s*buildFabIcon\(\s*\)\s*\)/.test(body),
    'ל-_createFab אין appendChild(buildFabIcon()) — האייקון לא מוכנס לכפתור');
}

/** 2. השם הנגיש. נמדד: בלי aria-label, get_by_role לא מצא את הכפתור בכלל. */
function assertAccessibleName(js) {
  const body = bodyOf(js, '_createFab(){');
  ok(/['"]aria-label['"]\s*:/.test(body),
    'לכפתור אין aria-label. כשהתוכן היה "+" השם הנגיש הגיע ממנו; ' +
    'עכשיו התוכן הוא svg עם aria-hidden, ובלי התווית לכפתור אין שם.');
  const icon = bodyOf(js, 'function buildFabIcon(');
  ok(/aria-hidden['"]\s*,\s*['"]true/.test(icon),
    'ל-svg אין aria-hidden="true" — קורא מסך יקריא אותו לצד התווית');
}

/** 3. נבנה ב-createElementNS ולא ב-innerHTML. */
function assertBuiltAsDom(js) {
  const icon = bodyOf(js, 'function buildFabIcon(');
  ok(icon, 'לא נמצאה הפונקציה buildFabIcon');
  ok(/createElementNS/.test(icon),
    'buildFabIcon לא משתמש ב-createElementNS');
  ok(!/innerHTML/.test(icon),
    'buildFabIcon חזר ל-innerHTML. language-icons.rst ממליץ על המסלול הנקי ' +
    'לכל קוד שממילא בונה DOM.');
}

/** 4. שבע צורות, ובלי בלוב המטא-דאטה. */
function assertSevenShapesNoMetadata(js) {
  const i = js.indexOf('const FAB_ICON_SHAPES');
  ok(i !== -1, 'לא נמצא FAB_ICON_SHAPES');
  const arr = js.slice(js.indexOf('[', i), js.indexOf('];', i));
  const shapes = (arr.match(/\['(rect|path|circle|line|polygon|ellipse)'/g) || []).length;
  ok(shapes === 7, `צריך 7 צורות באייקון, נמצאו ${shapes}`);
  // לא מחפשים את המילה "c2pa" — היא מופיעה בהערה שמסבירה מה הוסר, וחיפוש
  // כזה היה נכשל על התיעוד של עצמו. הנכס האמיתי הוא שאין בקובץ מחרוזת
  // בסיס-64 ארוכה: הבלוב שהוסר היה 7,684 תווים רצופים.
  const blob = /[A-Za-z0-9+/]{200,}={0,2}/.exec(js);
  ok(!blob,
    `חזרה לקובץ מחרוזת בסיס-64 באורך ${blob ? blob[0].length : 0} תווים. ` +
    'בלוק ה-<metadata> אינו מרונדר, והוא כ-7.5KB מול 583 בתים של ציור — ' +
    'בכל עמוד שטוען את הקובץ הזה.');
}

/** 5. העיגול ירד, והאייקון ממורכז. */
function assertNoCircleAndCentered(css) {
  const m = /\.sticky-note-fab\s*\{([^}]*)\}/.exec(css);
  ok(m, 'לא נמצא הכלל .sticky-note-fab');
  const body = m[1];
  ok(!/border-radius\s*:\s*50%/.test(body), 'חזר border-radius: 50% — העיגול חזר');
  ok(/background\s*:\s*none/.test(body), 'חזר רקע לכפתור');
  ok(/box-shadow\s*:\s*none/.test(body), 'חזר צל לכפתור');
  ok(/display\s*:\s*flex/.test(body),
    'ל-.sticky-note-fab אין display: flex. ה-"+" היה טקסט והתמרכז לבד; ' +
    'svg בלי מרכוז מפורש יושב לפי ה-baseline.');
  ok(/align-items\s*:\s*center/.test(body) && /justify-content\s*:\s*center/.test(body),
    'חסר מרכוז אנכי או אופקי');
}

/** 6. שם המחלקה משותף ל-_createFab ול-destroy — שני קבצים שקל להוציא מסנכרון. */
function assertClassNameContract(js, css) {
  ok(/createEl\('button',\s*'sticky-note-fab'/.test(js),
    '_createFab לא יוצר כפתור עם המחלקה sticky-note-fab');
  ok(/querySelector\('\.sticky-note-fab'\)/.test(js),
    'destroy() לא מחפש יותר את .sticky-note-fab — הכפתור יישאר אחרי כיבוי ' +
    'טוגל הפתקים בדפדפן הריפו ואחרי כל החלפת קובץ');
  ok(/\.sticky-note-fab/.test(css), 'ה-CSS לא מעצב את .sticky-note-fab');
}

console.log('כפתור הפתק הצף — האייקון:');
check('הכפתור מקבל אייקון ולא את התו "+"', () => assertIconNotPlusText(JS));
check('לכפתור יש שם נגיש, ול-svg יש aria-hidden', () => assertAccessibleName(JS));
check('האייקון נבנה ב-createElementNS ולא ב-innerHTML', () => assertBuiltAsDom(JS));
check('שבע צורות, בלי בלוק המטא-דאטה', () => assertSevenShapesNoMetadata(JS));
check('העיגול ירד והאייקון ממורכז', () => assertNoCircleAndCentered(CSS));
check('שם המחלקה משותף ל-_createFab, ל-destroy ול-CSS', () => assertClassNameContract(JS, CSS));

// ---------------------------------------------------------------------------
// מוטציות: כל טענה חייבת להיות מסוגלת ליפול. כל מוטציה מאמתת קודם
// שההחלפה באמת תפסה, ורק אז מריצה את הטענה ומצפה לכשל.
// ---------------------------------------------------------------------------

function mutate(src, find, replaceWith) {
  const count = src.split(find).length - 1;
  ok(count > 0, `המוטציה לא תפסה: "${find.slice(0, 50)}" לא נמצא`);
  const out = src.split(find).join(replaceWith);
  ok(out !== src, 'המוטציה לא שינתה את התוכן');
  return out;
}

function expectFails(name, mutated, fn) {
  let threw = false;
  try { fn(mutated); } catch (_) { threw = true; }
  check(name, () => ok(threw, 'הבדיקה עברה על קוד פגום — כלומר היא לא בודקת כלום'));
}

console.log('מוטציות (הבדיקות חייבות ליפול על קוד פגום):');

expectFails('חזרה ל-textContent = "+" מפילה את בדיקת האייקון',
  mutate(JS, 'btn.appendChild(buildFabIcon());', "btn.textContent = '+';"),
  assertIconNotPlusText);

expectFails('הסרת aria-label מפילה את בדיקת השם הנגיש',
  mutate(JS, "        'aria-label': 'הוסף פתק',\n", ''),
  assertAccessibleName);

expectFails('מעבר ל-innerHTML מפיל את בדיקת מסלול הבנייה',
  mutate(JS, 'const shape = document.createElementNS(SVG_NS, tag);',
             'const shape = null; svg.innerHTML += tag;'),
  assertBuiltAsDom);

expectFails('הסרת צורה מפילה את בדיקת שבע הצורות',
  mutate(JS, "    ['circle', { cx: '18.4', cy: '18.4', r: '5.1', fill: '#2DD4BF' }],\n", ''),
  assertSevenShapesNoMetadata);

expectFails('החזרת העיגול מפילה את בדיקת העיצוב',
  mutate(CSS, '  border: none; background: none; box-shadow: none; padding: 0;',
              '  border-radius: 50%; background: #fff; box-shadow: 0 8px 18px #0003;'),
  assertNoCircleAndCentered);

expectFails('הסרת display:flex מפילה את בדיקת המרכוז',
  mutate(CSS, '  display: flex; align-items: center; justify-content: center;', ''),
  assertNoCircleAndCentered);

expectFails('שינוי שם המחלקה ב-_createFab מפיל את בדיקת החוזה',
  mutate(JS, "createEl('button', 'sticky-note-fab'", "createEl('button', 'sticky-fab-v2'"),
  (js) => assertClassNameContract(js, CSS));

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
