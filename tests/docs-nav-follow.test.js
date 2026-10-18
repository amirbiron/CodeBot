'use strict';
/**
 * בדיקות לשתי ההחלטות של התפריט שעוקב אחרי הסעיף שקוראים בו באתר התיעוד —
 * ``pickActive`` ו-``scrollDelta`` שב-``docs/_static/nav-follow.js``.
 *
 * הרצה:  node tests/docs-nav-follow.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * הקובץ נטען כמו בדפדפן — script קלאסי שמגדיר ``window.DocNavFollow`` — בתוך ``vm``,
 * עם ``document`` שעוד נטען, כך שהחיבור לעמוד לא רץ ונבדקות רק ההחלטות.
 *
 * **מה הבדיקות האלה מוכיחות:** איזה סעיף נבחר לפי מיקומי הכותרות, ובכמה התפריט נגלל
 * כדי שהפריט יהיה באמצע, או שהוא לא זז כשהפריט נראה. ובנוסף: שקו הקריאה זהה לזה של
 * תוכן העניינים הצף ב-WebApp (``webapp/templates/md_preview.html``), שההתנהגות הועתקה
 * ממנו. אלה שני עותקים בשני מקומות, ובלי הבדיקה הם היו נפרדים בשקט.
 *
 * **ומה לא:** שהסקריפט מחובר לתפריט האמיתי של הערכה, שרק התפריט נגלל ולא העמוד, ושהערכה
 * עצמה לא מזיזה את התפריט. את זה מוכיחה ``tests/test_docs_nav_follow_browser.py``, על
 * אתר שנבנה עם ``docs/conf.py`` — והיא רצה רק כשיש Chromium, כלומר לא ב-CI.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const SCRIPT = fs.readFileSync(path.join(ROOT, 'docs', '_static', 'nav-follow.js'), 'utf8');
const MD_PREVIEW = fs.readFileSync(path.join(ROOT, 'webapp', 'templates', 'md_preview.html'), 'utf8');

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(actual, expected, what) {
  if (actual !== expected) {
    throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(expected)}, קיבלתי ${JSON.stringify(actual)}`);
  }
}

function load() {
  const sandbox = {
    window: {},
    document: {
      readyState: 'loading',
      addEventListener() {},
      querySelector() { return null; },
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(SCRIPT, sandbox);
  return sandbox.window.DocNavFollow;
}

const nav = load();

// ── איזה סעיף מסומן ─────────────────────────────────────────────────────────

check('אף כותרת לא עברה את הקו (ראש העמוד): אין סעיף מסומן', () => {
  eq(nav.pickActive([150, 400, 900], 120), -1, 'האינדקס');
  eq(nav.pickActive([], 120), -1, 'בלי סעיפים');
});

check('הסעיף שהכותרת שלו עברה את הקו אחרונה, ולא הראשון שעבר', () => {
  eq(nav.pickActive([-2000, -400, 60, 300], 120), 2, 'האינדקס');
});

check('כותרת שנמצאת בדיוק על הקו כבר נחשבת נקראת', () => {
  eq(nav.pickActive([-500, 120, 121], 120), 1, 'האינדקס');
});

check('תת-סעיף שהתחיל מנצח את הסעיף שמעליו, גם כשההורה מופיע קודם ברשימה', () => {
  // ההורה (‎-900), תת-הסעיף שלו (‎-40), והסעיף הבא שעוד לא הגיע (500)
  eq(nav.pickActive([-900, -40, 500], 120), 1, 'האינדקס');
});

check('הבחירה לפי המיקום ולא לפי הסדר ברשימה', () => {
  eq(nav.pickActive([80, -300], 120), 0, 'האינדקס');
});

// ── קו הקריאה, ובסוף העמוד ──────────────────────────────────────────────────

const H = 600;
const BASE = H * nav.READ_LINE_RATIO;

check('ברוב העמוד הקו בחמישית העליונה, גם בעמוד שלא נגלל בכלל', () => {
  eq(nav.readLine(H, 5000, 0), BASE, 'בראש העמוד');
  eq(nav.readLine(H, 5000, 5000 - (H - BASE)), BASE, 'בתחילת הקטע האחרון');
  eq(nav.readLine(H, 0, 0), BASE, 'עמוד שנכנס במסך אחד');
});

check('בתחתית העמוד הקו בתחתית המסך: כל כותרת שעל המסך עברה אותו', () => {
  eq(nav.readLine(H, 5000, 5000), H, 'בתחתית');
  eq(nav.readLine(H, 5000, 5040), H, 'גלילת יתר (מגע) אינה מורידה אותו מתחת למסך');
});

check('בקטע האחרון הקו יורד בהדרגה, ולא קופץ', () => {
  const lines = [];
  for (let scrolled = 4400; scrolled <= 5000; scrolled += 20) lines.push(nav.readLine(H, 5000, scrolled));
  for (let i = 1; i < lines.length; i += 1) {
    eq(lines[i] >= lines[i - 1], true, `הקו עולה בצעד ${i}`);
    // הקטע האחרון ארוך בדיוק כמו המרחק שהקו יורד, ולכן 20 פיקסלים של גלילה מזיזים אותו 20 לכל היותר
    eq(lines[i] - lines[i - 1] <= 20 + 1e-9, true, `צעד ${i} אינו קפיצה`);
  }
});

check('כותרת בקטע האחרון של העמוד עוברת את הקו לפני שהגלילה נגמרת, ולפי הסדר', () => {
  // שלוש כותרות, 100, 300 ו-500 פיקסלים לפני סוף העמוד; הן לעולם לא מגיעות לחמישית העליונה
  const docHeight = 5000 + H;
  const headings = [docHeight - 500, docHeight - 300, docHeight - 100];
  const passedAt = headings.map((position) => {
    for (let scrolled = 0; scrolled <= 5000; scrolled += 1) {
      if (position - scrolled <= nav.readLine(H, 5000, scrolled)) return scrolled;
    }
    return null;
  });
  eq(passedAt.every((at) => at !== null && at <= 5000), true, `כולן עברו (${passedAt})`);
  eq(passedAt[0] < passedAt[1] && passedAt[1] < passedAt[2], true, `לפי הסדר (${passedAt})`);
});

check('בעמוד קצר הקטע האחרון הוא כל הגלילה: מתחילים בקו הרגיל ומגיעים לתחתית', () => {
  eq(nav.readLine(H, 100, 0), BASE, 'בראש העמוד');
  eq(nav.readLine(H, 100, 50), BASE + (H - BASE) / 2, 'באמצע');
  eq(nav.readLine(H, 100, 100), H, 'בתחתית');
});

// ── בכמה לגלול את התפריט ────────────────────────────────────────────────────

const BOX = { top: 100, bottom: 600, height: 500 };
const item = (top, height = 32) => ({ top, bottom: top + height, height });
const center = (r) => r.top + r.height / 2;
/** איפה הפריט יהיה אחרי שהתפריט נגלל ב-delta: התוכן זז למעלה באותו מרחק. */
const moved = (r, delta) => item(r.top - delta, r.height);

check('פריט שנראה בשלמותו: התפריט לא זז', () => {
  eq(nav.scrollDelta(item(300), BOX), null, 'באמצע');
  eq(nav.scrollDelta(item(100), BOX), null, 'צמוד לקצה העליון');
  eq(nav.scrollDelta(item(568), BOX), null, 'צמוד לקצה התחתון');
});

check('פריט מעל התפריט: נגלל כך שהפריט באמצע', () => {
  const r = item(40);
  const delta = nav.scrollDelta(r, BOX);
  eq(delta < 0, true, 'כיוון הגלילה (למעלה)');
  eq(center(moved(r, delta)), center(BOX), 'המרכז אחרי הגלילה');
});

check('פריט מתחת לתפריט: נגלל כך שהפריט באמצע', () => {
  const r = item(900);
  const delta = nav.scrollDelta(r, BOX);
  eq(delta > 0, true, 'כיוון הגלילה (למטה)');
  eq(center(moved(r, delta)), center(BOX), 'המרכז אחרי הגלילה');
});

check('פריט שחתוך בקצה נחשב יוצא מהתצוגה', () => {
  const r = item(590);
  eq(center(moved(r, nav.scrollDelta(r, BOX))), center(BOX), 'המרכז אחרי הגלילה');
});

check('פריט גבוה (כותרת שנשברה לשתי שורות) מגיע לאמצע גם הוא', () => {
  const r = item(-200, 50);
  eq(center(moved(r, nav.scrollDelta(r, BOX))), center(BOX), 'המרכז אחרי הגלילה');
});

// ── קו הקריאה זהה לזה של תוכן העניינים ב-WebApp ────────────────────────────

check('קו הקריאה הוא הקצה העליון של הרצועה ב-INTERSECTION_MARGIN של md_preview.html', () => {
  const found = MD_PREVIEW.match(/INTERSECTION_MARGIN:\s*'(-?\d+(?:\.\d+)?)%/);
  eq(Boolean(found), true, 'INTERSECTION_MARGIN נמצא ב-md_preview.html');
  // rootMargin שלילי מכווץ את אזור התצוגה מלמעלה: ‎-20% הוא קו בחמישית העליונה
  eq(Math.round(nav.READ_LINE_RATIO * 100), -Number(found[1]), 'האחוז מראש המסך');
});

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
