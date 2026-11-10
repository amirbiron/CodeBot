/**
 * טסטים ל-webapp/static_build/mermaid-label-wrap-fix.mjs — התוסף שמתקן בבנייה את ההחלטה של Mermaid מתי לשבור
 * שורה בתווית (mermaid-js/mermaid#7794), ול-md_preview.bundle.js שנבנה איתו.
 *
 * הרצה:  node tests/md-preview-mermaid-label-wrap.test.js
 * (קובץ עצמאי שמריץ את הבדיקות בעצמו ויוצא בקוד 1 בכישלון: ``.github/workflows/ci.yml`` מריץ את
 *  ``tests/*.test.js`` בלולאה עם ``node "$f"``.)
 *
 * **מה נשמר כאן.** ``addHtmlSpan`` של Mermaid עובר למצב גלישה רק כשהמדידה של התווית שווה **בדיוק** לרוחב
 * הגלישה, ובכרומיום עם יחס פיקסלים שאינו שלם היא חוזרת עם שארית, והתווית נחתכת. התוסף מחליף את הבדיקה בבדיקה
 * עם סובלנות של פיקסל. ההסבר המלא — בראש קובץ התוסף; ההתנהגות בדפדפן נמדדת ב-
 * ``tests/test_mermaid_label_wrap_browser.py`` (שאינו רץ ב-CI, כי שם אין Chromium).
 *
 * **מה נבדק:**
 * - התוסף מחליף את הבדיקה ב-Mermaid שבריפו (``node_modules`` שמור בגיט, ולכן זה רץ גם ב-CI). ביום ששדרוג של
 *   Mermaid ישנה את הנוסח, הטסט הזה נופל — לא הפרודקשן.
 * - הבאנדל שבריפו נבנה עם התוסף. הבאנדל נבנה ביד (``npm run build-md``) ונשמר בגיט, ובלי הבדיקה הזו בנייה בלי
 *   התוסף, או תיקון בלי בנייה, היו עוברות בשקט.
 * - מסלולי הכשל: הנוסח לא נמצא בתוך ``addHtmlSpan`` — **גם כשאותו נוסח בדיוק יושב בפונקציה אחרת באותו קובץ**;
 *   ל-``addHtmlSpan`` אין הסוף המוכר; ואין בבנייה קובץ שמגדיר אותה. בכולם הבנייה נכשלת, עם הפניה לאישו. אלה רצים
 *   על מודולים מזויפים בתיקייה זמנית, כי בגרסה המותקנת המצבים האלה לא קורים.
 *
 * את ``addHtmlSpan`` מתוך הבאנדל קוראים ב-``locateAddHtmlSpan`` של התוסף, ולא בעותק כאן: אם הגבול שהתוסף מחפש בו
 * ישתנה, הטסט יקרא את אותו טווח.
 */
import fs from 'fs';
import os from 'os';
import path from 'path';
import { fileURLToPath } from 'url';
import { build } from 'esbuild';
import {
  locateAddHtmlSpan,
  mermaidLabelWrapFix,
  STRICT_WRAP_CHECK,
  TOLERANT_WRAP_CHECK,
} from '../webapp/static_build/mermaid-label-wrap-fix.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const BUNDLE_PATH = path.join(ROOT, 'webapp', 'static', 'js', 'md_preview.bundle.js');

let passed = 0;
let failed = 0;

async function check(name, fn) {
  try {
    await fn();
    passed += 1;
    console.log(`  ✓ ${name}`);
  } catch (err) {
    failed += 1;
    console.log(`  ✗ ${name}\n      ${err && err.message ? err.message : err}`);
  }
}

/** גוף ``addHtmlSpan`` מתוך קוד JS, ושם הפרמטר השלישי — רוחב הגלישה (esbuild משנה שמות, למשל ל-``width3``). */
function addHtmlSpanOf(code, where) {
  const located = locateAddHtmlSpan(code);
  if (located.error) throw new Error(`${where}: ${located.error}`);
  const body = code.slice(located.start, located.end);
  const params = body.slice(body.indexOf('(') + 1, body.indexOf(')')).split(',').map((p) => p.trim());
  return { body, widthParam: params[2] };
}

function escapeRegExp(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** הבדיקה עם הסובלנות, בשם הפרמטר שבקוד הנתון. */
function assertTolerantCheck(code, where) {
  const { body, widthParam } = addHtmlSpanOf(code, where);
  if (/bbox\.width\s*===/.test(body)) {
    throw new Error(`ב-${where} נשארה בדיקת השוויון המדויק: npm run build-md`);
  }
  const tolerant = new RegExp(`if \\(bbox\\.width >= ${escapeRegExp(widthParam)} - 1\\) \\{`);
  if (!tolerant.test(body)) {
    throw new Error(`ב-${where} אין "${TOLERANT_WRAP_CHECK}" (הפרמטר: ${widthParam})`);
  }
}

/** בנייה בזיכרון, בלי לכתוב קובץ. מחזיר את הפלט, או זורק את חריגת esbuild. */
async function bundle(entryPoint, absWorkingDir) {
  const result = await build({
    entryPoints: [entryPoint],
    absWorkingDir,
    bundle: true,
    format: 'iife',
    platform: 'browser',
    write: false,
    logLevel: 'silent',
    plugins: [mermaidLabelWrapFix()],
  });
  return result.outputFiles[0].text;
}

/** הבנייה נכשלת, ואחת השגיאות מזכירה את ``needle``. */
async function assertBuildFails(entryPoint, absWorkingDir, needle) {
  let error = null;
  try {
    await bundle(entryPoint, absWorkingDir);
  } catch (err) {
    error = err;
  }
  if (!error) throw new Error('הבנייה הצליחה, והיא הייתה צריכה להיכשל');
  const texts = (error.errors || []).map((e) => e.text);
  if (!texts.some((t) => t.includes(needle))) {
    throw new Error(`הבנייה נכשלה, אבל אף שגיאה אינה מזכירה "${needle}": ${JSON.stringify(texts)}`);
  }
}

/** תיקייה זמנית עם ``node_modules/mermaid/dist/<name>`` מזויף, ו-``entry.mjs`` שמייבא אותו. */
function fakeMermaid(name, source) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'mermaid-label-wrap-'));
  const dist = path.join(dir, 'node_modules', 'mermaid', 'dist');
  fs.mkdirSync(dist, { recursive: true });
  fs.writeFileSync(path.join(dist, name), source);
  fs.writeFileSync(path.join(dir, 'entry.mjs'), `import { addHtmlSpan } from './node_modules/mermaid/dist/${name}';\nwindow.f = addHtmlSpan;\n`);
  return dir;
}

/** מוחק רק תיקייה שנוצרה ב-``fakeMermaid`` — תחת ``os.tmpdir()``, ולפי הנתיב המוחלט שלה. */
function removeFake(dir) {
  const base = fs.realpathSync(os.tmpdir());
  const target = fs.realpathSync(dir);
  if (!target.startsWith(base + path.sep) || !path.basename(target).startsWith('mermaid-label-wrap-')) {
    throw new Error(`לא מוחק תיקייה מחוץ לתיקייה הזמנית: ${target}`);
  }
  fs.rmSync(target, { recursive: true, force: true });
}

console.log('mermaid-label-wrap-fix:');

await check('התוסף מחליף את בדיקת השוויון המדויק ב-Mermaid שבריפו', async () => {
  const entryDir = fs.mkdtempSync(path.join(os.tmpdir(), 'mermaid-label-wrap-'));
  try {
    // הייבוא מתוך הריפו, כמו ב-md-preview-entry.js; הקובץ הזמני רק מצביע עליו.
    fs.writeFileSync(path.join(entryDir, 'entry.mjs'), `import mermaid from ${JSON.stringify(path.join(ROOT, 'node_modules', 'mermaid', 'dist', 'mermaid.core.mjs'))};\nwindow.m = mermaid;\n`);
    const out = await bundle(path.join(entryDir, 'entry.mjs'), ROOT);
    assertTolerantCheck(out, 'בנייה של mermaid עם התוסף');
  } finally {
    removeFake(entryDir);
  }
});

await check('הבאנדל שבריפו (md_preview.bundle.js) נבנה עם התוסף', async () => {
  assertTolerantCheck(fs.readFileSync(BUNDLE_PATH, 'utf8'), 'md_preview.bundle.js');
});

await check('נוסח שהשתנה בקובץ של addHtmlSpan מפיל את הבנייה, עם הפניה לאישו', async () => {
  const changed = 'export async function addHtmlSpan(element, node, width) {\n' +
    '  const bbox = element.getBoundingClientRect();\n' +
    '  if (Math.abs(bbox.width - width) < 0.5) { return 1; }\n' +
    '  return 0;\n}\n__name(addHtmlSpan, "addHtmlSpan");\n';
  const dir = fakeMermaid('chunk-changed.mjs', changed);
  try {
    await assertBuildFails(path.join(dir, 'entry.mjs'), dir, 'mermaid-js/mermaid#7794');
  } finally {
    removeFake(dir);
  }
});

await check('נוסח שהשתנה בתוך addHtmlSpan מפיל את הבנייה גם כשהנוסח הישן נשאר בפונקציה אחרת באותו קובץ', async () => {
  // עד שהחיפוש הוגבל לגוף של addHtmlSpan, הבנייה הזו עברה: התוסף "תיקן" את otherHelper, ו-addHtmlSpan נשארה
  // עם הבדיקה שלה כמו שהיא.
  const elsewhere = 'function otherHelper(bbox, width) {\n' +
    `  ${STRICT_WRAP_CHECK} return "helper"; }\n` +
    '  return "";\n}\n__name(otherHelper, "otherHelper");\n' +
    'export async function addHtmlSpan(element, node, width) {\n' +
    '  const bbox = element.getBoundingClientRect();\n' +
    '  if (bbox.width === width + 0) { return otherHelper(bbox, width); }\n' +
    '  return 0;\n}\n__name(addHtmlSpan, "addHtmlSpan");\n';
  const dir = fakeMermaid('chunk-elsewhere.mjs', elsewhere);
  try {
    await assertBuildFails(path.join(dir, 'entry.mjs'), dir, 'בתוך addHtmlSpan');
    await assertBuildFails(path.join(dir, 'entry.mjs'), dir, 'mermaid-js/mermaid#7794');
  } finally {
    removeFake(dir);
  }
});

await check('addHtmlSpan בלי הסוף המוכר מפילה את הבנייה, עם הפניה לאישו', async () => {
  const noEnd = 'export async function addHtmlSpan(element, node, width) {\n' +
    '  const bbox = element.getBoundingClientRect();\n' +
    `  ${STRICT_WRAP_CHECK} return 1; }\n` +
    '  return 0;\n}\n';
  const dir = fakeMermaid('chunk-no-end.mjs', noEnd);
  try {
    await assertBuildFails(path.join(dir, 'entry.mjs'), dir, 'mermaid-js/mermaid#7794');
  } finally {
    removeFake(dir);
  }
});

await check('בנייה שאין בה קובץ שמגדיר את addHtmlSpan נכשלת, עם הפניה לאישו', async () => {
  const dir = fakeMermaid('other.mjs', 'export const addHtmlSpan = 1;\n');
  try {
    await assertBuildFails(path.join(dir, 'entry.mjs'), dir, 'mermaid-js/mermaid#7794');
  } finally {
    removeFake(dir);
  }
});

await check('בקרה: על הנוסח המדויק התוסף מחליף, ובלעדיו הבדיקה נשארת שוויון מדויק', async () => {
  const exact = 'export async function addHtmlSpan(element, node, width) {\n' +
    '  const bbox = element.getBoundingClientRect();\n' +
    `  ${STRICT_WRAP_CHECK} return 1; }\n` +
    '  return 0;\n}\n__name(addHtmlSpan, "addHtmlSpan");\n';
  const dir = fakeMermaid('chunk-exact.mjs', exact);
  try {
    assertTolerantCheck(await bundle(path.join(dir, 'entry.mjs'), dir), 'מודול מזויף עם הנוסח המדויק');
    const without = await build({
      entryPoints: [path.join(dir, 'entry.mjs')], absWorkingDir: dir, bundle: true, write: false, logLevel: 'silent',
    });
    const body = addHtmlSpanOf(without.outputFiles[0].text, 'בנייה בלי התוסף').body;
    if (!/bbox\.width === width/.test(body)) throw new Error('בלי התוסף הבדיקה הייתה צריכה להישאר ===');
  } finally {
    removeFake(dir);
  }
});

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
