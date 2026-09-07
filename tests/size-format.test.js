'use strict';
/**
 * בדיקות ל-``webapp/static/js/utils/size-format.js`` — עיצוב גדלי קבצים בצד הלקוח.
 *
 * הרצה:  node tests/size-format.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * הקובץ הנבדק נטען כמו בדפדפן — script קלאסי שמגדיר ``window.SizeFormat`` — כי
 * ``package.json`` מוגדר ``"type": "module"`` ולכן ``require()`` רגיל עליו לא
 * היה עובד.
 *
 * **מה הבדיקות האלה כן מוכיחות:** את סולם היחידות, את העיגול, את חיתוך ה-``.0``,
 * ואת נוכחות תווי הבידוד במחרוזת.
 *
 * **ומה לא:** שהערך באמת מצויר בסדר הנכון על המסך. ``vm`` אינו דפדפן ואינו מריץ
 * את אלגוריתם ה-bidi. את זה מוכיחה ``tests/test_size_format_bidi_browser.py``.
 * וגם לא שהוא מסכים עם צד השרת — את זה מוכיחה ``tests/test_file_size_display.py``.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(
  __dirname, '..', 'webapp', 'static', 'js', 'utils', 'size-format.js');

function loadSizeFormat() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox.window.SizeFormat;
}

const SizeFormat = loadSizeFormat();
const { formatFileSize, formatSizeNumber, LRI, PDI } = SizeFormat;

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(actual, expected, what) {
  if (actual !== expected) {
    throw new Error(
      `${what || ''} — ציפיתי ל-${JSON.stringify(expected)}, קיבלתי ${JSON.stringify(actual)}`);
  }
}
function ok(value, what) { if (!value) throw new Error(what || 'ציפיתי לאמת'); }

/** הערך בלי תווי הבידוד — כדי שהטבלאות למטה יישארו קריאות. */
function bare(bytes) {
  const text = formatFileSize(bytes);
  ok(text.startsWith(LRI) && text.endsWith(PDI), `חסר בידוד ב-${JSON.stringify(text)}`);
  return text.slice(LRI.length, text.length - PDI.length);
}

const KB = 1024, MB = 1024 * 1024, GB = 1024 * 1024 * 1024;

// ── סולם היחידות ───────────────────────────────────────────────────────────
[
  [0, '0 B'],
  [1, '1 B'],
  [582, '582 B'],
  [1023, '1023 B'],
  [KB, '1 KB'],
  [4 * KB, '4 KB'],
  [105 * KB, '105 KB'],
  [28569, '27.9 KB'],
  [MB, '1 MB'],
  // המימוש הישן של live-preview עצר כאן והציג "3584KB"
  [3.5 * MB, '3.5 MB'],
  // המימוש הישן של global_search עצר ב-MB והציג "2048 MB"
  [2 * GB, '2 GB'],
  // המימוש הישן של repo-browser עצר ב-GB והחזיר "3 undefined"
  [3 * 1024 * GB, '3 TB'],
  // מעל התקרה הערך גדל ואינו מקבל יחידה חדשה
  [3072 * 1024 * GB, '3072 TB'],
].forEach(([bytes, expected]) => {
  check(`formatFileSize(${bytes})`, () => eq(bare(bytes), expected, `${bytes} בתים`));
});

// ── עיגול וחיתוך ה-".0" ────────────────────────────────────────────────────
check('שלם אינו מקבל ".0"', () => {
  eq(formatSizeNumber(105), '105');
  eq(formatSizeNumber(0), '0');
});
check('שבר אמיתי נשמר', () => eq(formatSizeNumber(27.94), '27.9'));
check('חצי מדויק עולה — 1.25 ← 1.3, בדיוק כמו בפייתון', () => {
  eq(formatSizeNumber(1.25), '1.3');
  // 1280 בתים הם 1.25 KB בדיוק. זה הערך שחשף את הפער בין ``toFixed`` (חצי
  // כלפי מעלה) ל-``f"{:.1f}"`` של פייתון (חצי לזוגי), כשאותו קובץ הוצג
  // "1.3 KB" מהדפדפן ו-"1.2 KB" מהשרת.
  eq(bare(1280), '1.3 KB');
});
check('סימן שלילי נשמר', () => {
  eq(formatSizeNumber(-5), '-5');
  eq(formatSizeNumber(-0), '0');
});

// ── ערכים לא תקינים ────────────────────────────────────────────────────────
check('ערך חסר או לא-סופי נחשב 0, ולא "NaN undefined"', () => {
  eq(bare(NaN), '0 B');
  eq(bare(undefined), '0 B');
  eq(bare(null), '0 B');
  eq(bare(Infinity), '0 B');
});

// ── הבידוד ─────────────────────────────────────────────────────────────────
check('הערך עטוף ב-LRI/PDI', () => {
  const text = formatFileSize(105 * KB);
  eq(LRI.codePointAt(0), 0x2066, 'תו הפתיחה');
  eq(PDI.codePointAt(0), 0x2069, 'תו הסגירה');
  ok(text.startsWith(LRI), 'חסר תו פתיחה');
  ok(text.endsWith(PDI), 'חסר תו סגירה');
  // העטיפה אינה שוברת חיפוש תת-מחרוזת, שהוא מה שרוב הקוראים עושים
  ok(text.indexOf('105 KB') !== -1, 'הערך עצמו אינו נמצא במחרוזת');
});

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
