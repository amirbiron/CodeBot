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
 * **המחרוזות כתובות במודול, ולכן הטסט זהה בכל גרסת נוד.** עד אוקטובר 2026 המודול
 * לקח את הניסוח מ-``Intl.RelativeTimeFormat``, והטסט עבר בנוד 22 (CLDR 47) ונפל
 * ב-CI על נוד 24 (CLDR 48): "לפני שע׳ (1)" במקום "לפני שעה", "לפני יום אחד (1)"
 * במקום "אתמול". אותו פער היה מגיע למשתמשים, לפי גרסת הדפדפן. הבדיקה "בלי ``Intl``,
 * ועם ``Intl`` שמחזיר זבל" למטה נועלת את זה: התוצאה אינה תלויה בנתוני המנוע.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const MODULE_PATH = path.join(ROOT, 'webapp', 'static', 'js', 'utils', 'relative-time.js');

/** ``extra`` — גלובלים נוספים ל-sandbox, למשל ``Intl`` חלופי. */
function loadRelativeTime(extra) {
  const sandbox = Object.assign({ window: {} }, extra || {});
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
  // זוגי בכל יחידה, חוץ מדקות — שם "2 דק׳", כמו רבים.
  [2 * MIN, 'לפני 2 דק׳', 'שתי דקות'],
  [15 * DAY, 'לפני שבועיים', 'שבועיים'],
  [61 * DAY, 'לפני חודשיים', 'חודשיים'],
  [731 * DAY, 'לפני שנתיים', 'שנתיים'],
  // ורבים, עם המספר.
  [3 * DAY, 'לפני 3 ימים', '3 ימים'],
  [22 * DAY, 'לפני 3 שבועות', '3 שבועות'],
  [95 * DAY, 'לפני 3 חודשים', '3 חודשים'],
  [5 * 365 * DAY, 'לפני 5 שנים', '5 שנים'],
].forEach(([ago, expected, what]) => {
  check(`${what} (${ago}ms)`, () => eq(fmt(ago), expected, what));
});

// ── הספים: אותם ספים כמו ב-``repo-history.js`` לפני האיחוד ────────────────────
check('פחות מדקה — "עכשיו", ולא "לפני 30 שנ׳"', () => {
  eq(fmt(30 * SEC), 'עכשיו');
  eq(fmt(0), 'עכשיו');
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
check('דקות ושעות — אותו טקסט בלי "לפני"', () => {
  eq(fmt(20 * MIN, { compact: true }), '20 דק׳');
  eq(fmt(MIN, { compact: true }), 'דקה');
  eq(fmt(61 * MIN, { compact: true }), 'שעה');
  eq(fmt(2 * HOUR, { compact: true }), 'שעתיים');
  eq(fmt(3 * HOUR, { compact: true }), '3 שע׳');
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

// ── הטקסט אינו תלוי בנתוני השפה של המנוע ─────────────────────────────────────
check('בלי Intl, ועם Intl שמחזיר זבל — אותו טקסט בדיוק', () => {
  // כך נראה CLDR 48 (נוד 24) מול המודול הקודם, שלקח את הניסוח מ-``Intl``: "(1)"
  // אחרי היחיד. דפדפן חדש או ישן אינו אמור לשנות מילה במה שמוצג.
  const garbage = function () { return { format: (n) => `זבל (${Math.abs(Number(n)) || 0})` }; };
  const hostileIntl = { RelativeTimeFormat: garbage, NumberFormat: garbage, PluralRules: garbage };
  const variants = [
    ['Intl שמחזיר זבל', loadRelativeTime({ Intl: hostileIntl })],
    ['בלי Intl', loadRelativeTime({ Intl: undefined })],
  ];
  const samples = [10 * SEC, MIN, 20 * MIN, 61 * MIN, 2 * HOUR, 30 * HOUR, 2 * DAY + HOUR, 8 * DAY, 40 * DAY, 400 * DAY];
  for (const [label, other] of variants) {
    for (const ago of samples) {
      for (const compact of [false, true]) {
        const opts = { now: NOW, compact };
        eq(other.format(before(ago), opts), RelativeTime.format(before(ago), opts), `${label}, ${ago}ms, compact=${compact}`);
      }
    }
  }
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
