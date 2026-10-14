'use strict';
/**
 * בדיקות ל-``webapp/static/js/utils/relative-time.js`` — זמן יחסי בצד הלקוח.
 *
 * הרצה:  node tests/relative-time.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * הקובץ הנבדק נטען כמו בדפדפן — script קלאסי שמגדיר ``window.RelativeTime`` — כמו
 * ``size-format.test.js``.
 *
 * **המחרוזות כאן נמדדו, ולא נכתבו מהזיכרון:** אותן תוצאות בכרומיום 141 ובנוד 22
 * (ICU 77.1, ‏CLDR 47), אוקטובר 2026. הן תלויות בנתוני ה-CLDR של סביבת הריצה, ולכן
 * טסט שנופל אחרי שדרוג נוד בלי שום שינוי קוד אומר ש-CLDR שינה ניסוח — והבחירה
 * באפשרויות (``numeric``, ``style`` לכל יחידה) צריכה להימדד מחדש, לא הטסט להשתתק.
 *
 * **הצורה המקוצרת אינה מקובעת במחרוזת**, ובכוונה: היא נבדלת בין המנועים כבר היום —
 * שעה אחת היא "שעה" בכרומיום 141 ו-"1 שעה" בנוד 22. מה שנבדק בה הוא החיווט: דקות
 * ושעות עוברות דרך יחידה בלי "לפני", ויום ומעלה זהים לצורה הרגילה.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const MODULE_PATH = path.join(ROOT, 'webapp', 'static', 'js', 'utils', 'relative-time.js');

function loadRelativeTime() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox.window.RelativeTime;
}

const RelativeTime = loadRelativeTime();

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

const SEC = 1000, MIN = 60 * SEC, HOUR = 60 * MIN, DAY = 24 * HOUR;
const NOW = Date.UTC(2026, 9, 13, 12, 0, 0);
/** הזמן שקרה ``ago`` אלפיות שנייה לפני ``NOW``, כמחרוזת ISO — כמו שהשרת שולח. */
const before = (ago) => new Date(NOW - ago).toISOString();
const fmt = (ago, opts) => RelativeTime.format(before(ago), Object.assign({ now: NOW }, opts || {}));

// ── הערכים שהעיצוב מציג ─────────────────────────────────────────────────────
[
  [20 * MIN, 'לפני 20 דק׳', 'העיצוב: "לפני 20 דק׳"'],
  [40 * MIN, 'לפני 40 דק׳', 'העיצוב: "לפני 40 דק׳"'],
  [61 * MIN, 'לפני שעה', 'יחיד בלי "1" — העותקים הקודמים אמרו "לפני 1 שעות"'],
  [2 * HOUR, 'לפני שעתיים', 'זוגי'],
  [30 * HOUR, 'אתמול', 'העיצוב: "אתמול"'],
  // ``numeric: 'auto'`` היה נותן כאן "שלשום" — לכן ``always``.
  [2 * DAY + HOUR, 'לפני יומיים', 'העיצוב: "לפני יומיים"'],
  // ``style: 'short'`` היה נותן כאן "לפני שב׳" — לכן שבועות בסגנון הארוך.
  [8 * DAY, 'לפני שבוע', 'שבוע אחד בסגנון הארוך'],
  [40 * DAY, 'לפני חודש', 'חודש אחד'],
  [400 * DAY, 'לפני שנה', 'שנה אחת'],
].forEach(([ago, expected, what]) => {
  check(`${what} (${ago}ms)`, () => eq(fmt(ago), expected, what));
});

// ── הספים: אותם ספים כמו ב-``repo-history.js`` לפני האיחוד ────────────────────
check('פחות מדקה — "עכשיו", ולא "לפני 30 שנ׳"', () => {
  const nowWord = new Intl.RelativeTimeFormat('he', { numeric: 'auto' }).format(0, 'second');
  eq(fmt(30 * SEC), nowWord);
  eq(fmt(0), nowWord);
});
check('בדיוק דקה — כבר דקות', () => eq(fmt(MIN), 'לפני דקה'));
check('59 דקות — עדיין דקות; 60 — כבר שעה', () => {
  eq(fmt(59 * MIN), 'לפני 59 דק׳');
  eq(fmt(60 * MIN), 'לפני שעה');
});
check('23 שעות — עדיין שעות; 24 — כבר יום', () => {
  eq(fmt(23 * HOUR), 'לפני 23 שע׳');
  eq(fmt(24 * HOUR), 'אתמול');
});
check('6 ימים — עדיין ימים; 7 — כבר שבוע', () => {
  eq(fmt(6 * DAY), 'לפני 6 ימים');
  eq(fmt(7 * DAY), 'לפני שבוע');
});
check('29 יום — עדיין שבועות; 30 — כבר חודש', () => {
  eq(fmt(29 * DAY), 'לפני 4 שבועות');
  eq(fmt(30 * DAY), 'לפני חודש');
});
check('364 יום — עדיין חודשים; 365 — כבר שנה', () => {
  eq(fmt(364 * DAY), 'לפני 12 חודשים');
  eq(fmt(365 * DAY), 'לפני שנה');
});

// ── זמן בעתיד: השעון של המכשיר אינו השעון של השרת ─────────────────────────────
check('זמן בעתיד הוא "עכשיו", ולא "בעוד 5 שנ׳"', () => {
  eq(fmt(-5 * SEC), fmt(0));
  eq(fmt(-3 * HOUR), fmt(0), 'גם הרבה בעתיד');
});

// ── הקלט: מחרוזת ISO עם היסט, או ``Date`` — וכל השאר אינו זמן ─────────────────
check('מחרוזת עם היסט מפורש נקראת לפי ההיסט', () => {
  // 14:40 בהיסט +03:00 הוא 11:40 UTC — עשרים דקות לפני NOW (12:00 UTC). קריאה
  // כשעון מקומי, או התעלמות מההיסט, הייתה מזיזה את זה בשעות.
  eq(RelativeTime.format('2026-10-13T14:40:00+03:00', { now: NOW }), 'לפני 20 דק׳');
  eq(RelativeTime.format('2026-10-13T11:40:00Z', { now: NOW }), 'לפני 20 דק׳');
});
check('Date מתקבל כמו מחרוזת', () => {
  eq(RelativeTime.format(new Date(NOW - 20 * MIN), { now: NOW }), 'לפני 20 דק׳');
});
check('ערך שאינו זמן ← מחרוזת ריקה, ולא "Invalid Date" או חריגה', () => {
  [undefined, null, '', 'not a date', 1760356800, {}, [], true, new Date(NaN)].forEach((v) => {
    eq(RelativeTime.format(v, { now: NOW }), '', `קלט ${String(v)}`);
  });
});
check('בלי now — נמדד מול השעון עכשיו', () => {
  eq(RelativeTime.format(new Date(Date.now() - 20 * MIN)), 'לפני 20 דק׳');
});

// ── הצורה המקוצרת (חלונית צרה) ────────────────────────────────────────────────
check('דקות ושעות — יחידה בלי "לפני"', () => {
  const unit = (u, n) => new Intl.NumberFormat('he', { style: 'unit', unit: u, unitDisplay: 'short' }).format(n);
  eq(fmt(20 * MIN, { compact: true }), unit('minute', 20));
  eq(fmt(3 * HOUR, { compact: true }), unit('hour', 3));
  ok(!fmt(20 * MIN, { compact: true }).includes('לפני'), 'הצורה המקוצרת אינה אומרת "לפני"');
});
check('יום ומעלה — זהה לצורה הרגילה', () => {
  eq(fmt(30 * HOUR, { compact: true }), fmt(30 * HOUR));
  eq(fmt(2 * DAY + HOUR, { compact: true }), 'לפני יומיים');
  eq(fmt(8 * DAY, { compact: true }), 'לפני שבוע');
});
check('פחות מדקה — "עכשיו" גם בצורה המקוצרת', () => eq(fmt(10 * SEC, { compact: true }), fmt(0)));

// ── הממשק ─────────────────────────────────────────────────────────────────────
check('האובייקט המיוצא מוקפא — אי אפשר להחליף את format מבחוץ', () => {
  ok(Object.isFrozen(RelativeTime), 'RelativeTime אינו מוקפא');
});

// ── R6: אין עותק שני ────────────────────────────────────────────────────────────
/** כל קבצי ה-JS וה-HTML של הלקוח, בלי באנדלים ומוקטנים. */
function clientFiles() {
  const out = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) { walk(full); continue; }
      if (!/\.(js|html)$/.test(entry.name) || /\.(bundle|min)\.js$/.test(entry.name)) continue;
      out.push(full);
    }
  };
  walk(path.join(ROOT, 'webapp', 'static', 'js'));
  walk(path.join(ROOT, 'webapp', 'templates'));
  return out;
}

check('אין זמן יחסי שנכתב ביד בצד הלקוח ("לפני ${...}")', () => {
  // שני העותקים שהיו — ``formatDate`` ב-``base.html`` ו-``formatRelativeDate``
  // ב-``repo-history.js`` — נכתבו בדיוק בצורה הזו, ונבדלו זה מזה.
  const offenders = clientFiles()
    .filter((f) => /לפני \$\{/.test(fs.readFileSync(f, 'utf8')))
    .map((f) => path.relative(ROOT, f));
  eq(offenders.join(', '), '', 'קבצים עם זמן יחסי משלהם');
});
check('שני הצרכנים הקודמים עוברים דרך המודול', () => {
  const base = fs.readFileSync(path.join(ROOT, 'webapp', 'templates', 'base.html'), 'utf8');
  const history = fs.readFileSync(path.join(ROOT, 'webapp', 'static', 'js', 'repo-history.js'), 'utf8');
  ok(/function formatDate\([^)]*\)\s*\{\s*return window\.RelativeTime\.format\(/.test(base), 'base.html');
  ok(/window\.RelativeTime\.format\(new Date\(timestamp \* 1000\)\)/.test(history), 'repo-history.js');
});

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
