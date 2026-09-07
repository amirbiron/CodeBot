'use strict';
// בדיקות למתג "תצוגה מצומצמת" שבעמוד ההגדרות.
//
// **למה קובץ חדש ולא בדיקת פייתון:** הלוגיקה חיה בסקריפט מוטבע ב-
// ``settings.html``, ובדיקה בפייתון יכולה לאמת רק שהטקסט קיים בקובץ. מה
// שהמתג באמת עושה — גוף הבקשה שיוצא, ההודעה שמתעדכנת, והחזרת המתג למצבו
// הקודם בכשל — קורה בזמן ריצה, ואף אחד מהם לא נבדק אם רק מחפשים מחרוזות.
//
// אותו דפוס בדיוק כמו ``tests/settings-note-fonts.test.js`` על הבורר השכן:
// חילוץ הבלוק לפי עוגנים, ``vm`` עם DOM ו-``fetch`` מדומים, ואז ירי אירוע
// ``change`` אמיתי.
//
// **מה הבדיקות כאן לא מוכיחות:** שהמתג נראה ונלחץ בעמוד. DOM מזויף אינו
// אוכף פריסה. את זה מוכיחה רק הרצה בדפדפן.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TEMPLATE = path.join(__dirname, '..', 'webapp', 'templates', 'settings.html');
const SRC = fs.readFileSync(TEMPLATE, 'utf8');

const START_ANCHOR = '// ── תצוגה מצומצמת בעמוד הקבצים ──';
const END_ANCHOR = '      })();';

let passed = 0, failed = 0;
async function acheck(name, fn) {
  try { await fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}
function ok(v, what) { if (!v) throw new Error(what || 'ציפיתי לאמת'); }

/** מחלץ את ה-IIFE של המתג לפי עוגני התחלה וסוף.
 *
 * עיגון בשמות ולא במספרי שורות: ``settings.html`` הוא מעל 4000 שורות ועם
 * עשרות בלוקי ``<script>``, ומספר שורה היה מתיישן בשקט בעריכה הבאה.
 */
function toggleScript() {
  const start = SRC.indexOf(START_ANCHOR);
  if (start < 0) throw new Error('בלוק המתג לא נמצא — עוגן הפתיחה השתנה');
  const end = SRC.indexOf(END_ANCHOR, start);
  if (end < 0) throw new Error('סוף הבלוק לא נמצא — עוגן הסגירה השתנה');
  return SRC.slice(start, end + END_ANCHOR.length);
}

/** קלט מדומה, עם מה שהקוד באמת נוגע בו. */
function mkToggle(checked) {
  const listeners = {};
  return {
    checked,
    dataset: {},
    addEventListener: (t, fn) => { (listeners[t] = listeners[t] || []).push(fn); },
    __listenerCount: (t) => (listeners[t] || []).length,
    __fire: async (t) => { for (const fn of (listeners[t] || [])) await fn(); },
  };
}

/**
 * ``fetchImpl`` מקבל את גוף הבקשה המפורסר ומחזיר ``{ok, body}`` או זורק.
 * ברירת המחדל: הצלחה.
 *
 * ``opts.runs`` — כמה פעמים להריץ את הסקריפט. הבלוק ``extra_js`` של העמוד
 * מרונדר פעמיים בפועל, ולכן ``2`` הוא המצב האמיתי בדפדפן.
 */
function load(fetchImpl, opts = {}) {
  const sent = [];
  const toggle = mkToggle(opts.checked === true);
  const msg = { textContent: 'ברירת מחדל' };

  const sandbox = {
    console: { error: () => {} },
    JSON, String, Promise, Error,
    document: {
      getElementById: (id) => (id === 'filesCompactToggle' ? toggle
                            : id === 'filesCompactMsg' ? msg : null),
    },
    fetch: async (url, init) => {
      const body = JSON.parse(init.body);
      sent.push({ url, body });
      const out = fetchImpl ? await fetchImpl(body, sent.length) : { ok: true, body: { ok: true } };
      if (out.throws) throw new Error('network down');
      return {
        ok: out.ok !== false,
        status: out.status || 200,
        json: async () => out.body,
      };
    },
  };
  vm.createContext(sandbox);
  sandbox.window = sandbox;

  const script = toggleScript();
  for (let i = 0; i < (opts.runs || 1); i += 1) {
    vm.runInContext(script, sandbox);
  }
  return { toggle, msg, sent };
}

// ── מה שהמתג שולח ──────────────────────────────────────────────────────
await acheck('הדלקה שולחת את המפתח הנכון עם true', async () => {
  const h = load();
  h.toggle.checked = true;
  await h.toggle.__fire('change');

  eq(h.sent.length, 1, 'מספר הבקשות');
  eq(h.sent[0].url, '/api/ui_prefs', 'הנתיב');
  eq(JSON.stringify(h.sent[0].body), '{"files_compact_view":true}', 'גוף הבקשה');
  ok(h.msg.textContent.indexOf('מצומצמת') !== -1, `ההודעה: ${h.msg.textContent}`);
});

await acheck('כיבוי שולח false', async () => {
  const h = load(null, { checked: true });
  h.toggle.checked = false;
  await h.toggle.__fire('change');

  eq(JSON.stringify(h.sent[0].body), '{"files_compact_view":false}', 'גוף הבקשה');
  ok(h.msg.textContent.indexOf('מלאה') !== -1, `ההודעה: ${h.msg.textContent}`);
});

// ── כשל: המתג חוזר למצבו הקודם ─────────────────────────────────────────
//
// זה החלק שקל לשכוח. בלעדיו המתג נשאר במצב החדש בזמן שהשרת מחזיק את הישן,
// והמשתמש רואה הגדרה שאינה קיימת — ויגלה זאת רק בטעינה הבאה.
await acheck('שגיאת רשת מחזירה את המתג ואת ההודעה', async () => {
  const h = load(() => ({ throws: true }));
  h.toggle.checked = true;
  await h.toggle.__fire('change');

  eq(h.toggle.checked, false, 'המתג לא הוחזר למצבו הקודם');
  ok(h.msg.textContent.indexOf('נכשלה') !== -1, `ההודעה: ${h.msg.textContent}`);
});

await acheck('‏ok:false בגוף התשובה נחשב כשל, גם כשהסטטוס 200', async () => {
  // האנדפוינט מחזיר 200 עם ``ok:false`` בחלק ממסלולי הכשל. בדיקה לפי
  // הסטטוס בלבד הייתה מאשרת שמירה שלא קרתה.
  const h = load(() => ({ ok: true, status: 200, body: { ok: false, error: 'nope' } }));
  h.toggle.checked = true;
  await h.toggle.__fire('change');

  eq(h.toggle.checked, false, 'המתג נשאר דלוק למרות ok:false');
  ok(h.msg.textContent.indexOf('נכשלה') !== -1, `ההודעה: ${h.msg.textContent}`);
});

await acheck('‏400 מהשרת נחשב כשל', async () => {
  const h = load(() => ({ ok: false, status: 400, body: { ok: false, error: 'bad' } }));
  h.toggle.checked = true;
  await h.toggle.__fire('change');

  eq(h.toggle.checked, false, 'המתג נשאר דלוק למרות 400');
});

// ── חיווט יחיד למרות שהבלוק מרונדר פעמיים ──────────────────────────────
await acheck('הרצה כפולה של הסקריפט רושמת מאזין אחד', async () => {
  // הבלוק ``extra_js`` של ``settings.html`` מוצהר בתוך ``block content``,
  // ולכן Jinja מרנדר אותו פעמיים. נמדד בדפדפן: לחיצה אחת ייצרה שתי בקשות.
  // ``dataset.wired`` הוא מה שסוגר את זה — והבדיקה הזו נופלת בלעדיו.
  const h = load(null, { runs: 2 });
  eq(h.toggle.__listenerCount('change'), 1, 'מספר המאזינים');

  h.toggle.checked = true;
  await h.toggle.__fire('change');
  eq(h.sent.length, 1, 'לחיצה אחת שלחה יותר מבקשה אחת');
});

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
