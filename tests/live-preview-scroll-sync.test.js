/**
 * טסטים לחשבון של webapp/static/js/live-preview-scroll-sync.js — ההתאמה בין שורה במקור לגובה בתצוגה, ונקודת הקריאה.
 *
 * הרצה:  node tests/live-preview-scroll-sync.test.js
 * (בריפו אין runner מוגדר ל-JS, ולכן הקובץ עצמאי ומחזיר קוד יציאה 1 בכישלון.)
 *
 * הקובץ נטען כמו בדפדפן — script קלאסי שמגדיר ``window.LivePreviewScrollSync``. כאן נבדק רק החשבון, בלי DOM. הגלילה
 * עצמה, מול CodeMirror ותצוגה אמיתיים, נבדקת ב-``tests/test_markdown_editor_browser.py`` וב-
 * ``tests/test_edit_page_frame_browser.py``.
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'live-preview-scroll-sync.js');

function load() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox.window.LivePreviewScrollSync;
}

const S = load();

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

const near = (a, b, eps = 1e-6) => Math.abs(a - b) <= eps;
const plain = (points) => JSON.stringify(points.map((p) => [p.line, p.y]));

console.log('הנקודות: ראש הגולל ושורה -1, הסוף ושורה lineCount + 1, ובכל שורה נקודה אחת — הגבוהה');
{
  // כותרת בשורות 0-1 (גובה 20 עד 60), ומיד אחריה, בלי שורה ריקה, כותרת בשורה 1-2 (80 עד 110); פסקה בשורות 3-5.
  const points = S.buildPoints([
    { start: 0, end: 1, top: 20, bottom: 60 },
    { start: 1, end: 2, top: 80, bottom: 110 },
    { start: 3, end: 5, top: 130, bottom: 200 },
  ], 6, 260);
  check('הנקודות כמצופה', plain(points) === '[[-1,0],[0,20],[1,80],[2,110],[3,130],[5,200],[7,260]]', plain(points));
  // התחתית של הכותרת הראשונה (שורה 1, גובה 60) נזרקה: אחרת השבר שלפני שורה 1 היה מתקרב ל-60, ובשורה 1 עצמה התצוגה
  // הייתה קופצת ל-80. זו הקפיצה של 20px שנמדדה בטקסט ההדגמה.
  check('בלי קפיצה בין שתי כותרות צמודות', near(S.lineToY(points, 1 - 1e-9), 80, 1e-4), S.lineToY(points, 1 - 1e-9));
  check('אמצע הכותרת הראשונה — באמצע המרווח שבין שני הראשים', near(S.lineToY(points, 0.5), 50), S.lineToY(points, 0.5));
}

console.log('ראש הגולל מול ראש הגולל, והסוף מול הסוף — גם כשהשורה הראשונה מתחת לריפוד');
{
  const points = S.buildPoints([{ start: 0, end: 2, top: 20, bottom: 60 }], 2, 100);
  check('שורה -1 (ראש הגולל בעורך) היא גובה 0', S.lineToY(points, -1) === 0, S.lineToY(points, -1));
  check('שורה 0 היא ראש הבלוק הראשון', S.lineToY(points, 0) === 20, S.lineToY(points, 0));
  check('שורה lineCount + 1 (סוף הגולל בעורך) היא סוף התוכן', S.lineToY(points, 3) === 100, S.lineToY(points, 3));
  check('גובה 0 בתצוגה הוא שורה -1', S.yToLine(points, 0) === -1, S.yToLine(points, 0));
  check('הסוף של התצוגה הוא שורה lineCount + 1', S.yToLine(points, 100) === 3, S.yToLine(points, 100));
  check('מעבר לקצוות — נצמד לקצה', S.lineToY(points, -5) === 0 && S.lineToY(points, 50) === 100);
}

console.log('בלוק שמוצג שלא לפי הסדר במקור נזרק, ושאר הנקודות נשארות');
{
  // הערת שוליים: כתובה בשורה 4, מוצגת בתחתית (900). בלי הסינון, כל הנקודות שאחריה היו "יורדות".
  const points = S.buildPoints([
    { start: 0, end: 2, top: 10, bottom: 50 },
    { start: 4, end: 5, top: 900, bottom: 940 },
    { start: 6, end: 8, top: 100, bottom: 150 },
    { start: 9, end: 11, top: 170, bottom: 220 },
  ], 12, 1000);
  check('הנקודות של הערת השוליים לא נשארו', !points.some((p) => p.y === 900 || p.y === 940), plain(points));
  check('הבלוקים שאחריה נשארו', points.some((p) => p.line === 6 && p.y === 100) && points.some((p) => p.line === 11 && p.y === 220), plain(points));
  const ys = points.map((p) => p.y);
  const lines = points.map((p) => p.line);
  check('הגובה לא יורד והשורות עולות', ys.every((y, i) => i === 0 || y >= ys[i - 1]) && lines.every((l, i) => i === 0 || l > lines[i - 1]), plain(points));
}

console.log('yToLine הוא ההפך של lineToY');
{
  const points = S.buildPoints([
    { start: 0, end: 3, top: 16, bottom: 96 },
    { start: 4, end: 10, top: 120, bottom: 600 },   // תרשים גבוה: 6 שורות, 480px
    { start: 11, end: 12, top: 630, bottom: 660 },
  ], 13, 700);
  let worst = 0;
  for (let x = -1; x <= 14; x += 0.125) {
    worst = Math.max(worst, Math.abs(S.yToLine(points, S.lineToY(points, x)) - x));
  }
  check('הלוך וחזור מחזיר את אותה שורה', worst < 1e-9, worst);
  check('אמצע התרשים במקור הוא אמצע התרשים בתצוגה', near(S.lineToY(points, 7), 360), S.lineToY(points, 7));
}

console.log('נקודת הקריאה: ראש החלון בהתחלה, התחתית בסוף');
{
  check('בהתחלה — 0', S.readingY(0, 800, 1000) === 0);
  check('בסוף — סוף התוכן', S.readingY(800, 800, 1000) === 1000);
  check('באמצע — לפי היחס', S.readingY(400, 800, 1000) === 500);
  check('בלי גלילה (תוכן קצר) — 0', S.readingY(0, 0, 150) === 0);
  check('ההפך: הגלילה לנקודת קריאה', S.scrollTopForReadingY(500, 800, 1000) === 400);
  check('ההפך נצמד לגבולות', S.scrollTopForReadingY(5000, 800, 1000) === 800 && S.scrollTopForReadingY(-20, 800, 1000) === 0);
}

console.log('הגלילה המקסימלית אינה שלילית כשהתוכן קצר מהחלון');
{
  check('תוכן 150 בחלון 400 — 0', S.maxScrollOf(150, 400) === 0);
  check('תוכן 1000 בחלון 400 — 600', S.maxScrollOf(1000, 400) === 600);
  check('בלי גלילה, ההפך מחזיר 0 ולא ערך שלילי', S.scrollTopForReadingY(300, S.maxScrollOf(150, 400), 150) === 0);
}

console.log('קלט פגום לא שובר את הנקודות');
{
  const points = S.buildPoints([null, { start: NaN, end: 2, top: 0, bottom: 1 }, { start: 2, end: 1, top: 40, bottom: 60 }, { start: 3, end: 4, top: 80, bottom: 70 }], 5, 120);
  check('בלוק בלי סוף תקין מקבל שורה אחת, והפגומים נזרקים', plain(points) === '[[-1,0],[2,40],[3,60],[6,120]]', plain(points));
  check('בלי נקודות — null', S.lineToY([], 3) === null && S.yToLine([], 3) === null);
}

console.log(`\n${passed} עברו, ${failed} נכשלו`);
if (failed) process.exit(1);
