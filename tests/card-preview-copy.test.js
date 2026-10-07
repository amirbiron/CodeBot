'use strict';
/**
 * בדיקות לכפתור "העתק" בתצוגה המקדימה של כרטיס — ``copyPreviewCode`` שב-
 * ``webapp/static/js/card-preview.js``.
 *
 * הרצה:  node tests/card-preview-copy.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * הקובץ נטען כמו בדפדפן — script קלאסי שמגדיר ``window.cardPreview`` — בתוך ``vm``,
 * עם ``fetch``, לוח ו-``ClipboardItem`` מדומים.
 *
 * **מה הבדיקות האלה כן מוכיחות, וזה מה שהן מוסיפות על בדיקת הדפדפן:** שהכתיבה
 * ללוח נפתחת **בתוך** הלחיצה, לפני שהשרת ענה. ספארי ופיירפוקס דוחים כתיבה שמגיעה
 * אחרי המתנה, וכרומיום — היחיד שרץ ב-``tests/test_card_preview_copy_browser.py`` —
 * אינו יכול להראות את זה, כי שם ההרשאה מאושרת לבדיקה ופוטרת מהדרישה. ובנוסף: מה
 * נכתב, לאיזו כתובת יצאה הבקשה, ומה המשתמש רואה בכל כשל.
 *
 * **ומה לא:** שהדפדפן באמת מקבל את הכתיבה ושהלוח מכיל את הקובץ. את זה מוכיחה
 * בדיקת הדפדפן.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCRIPT = fs.readFileSync(
  path.join(__dirname, '..', 'webapp', 'static', 'js', 'card-preview.js'), 'utf8');

let passed = 0, failed = 0;
async function check(name, fn) {
  try { await fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(actual, expected, what) {
  if (actual !== expected) {
    throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(expected)}, קיבלתי ${JSON.stringify(actual)}`);
  }
}
function ok(value, what) { if (!value) throw new Error(what || 'ציפיתי לאמת'); }

/** ממתין שכל ההבטחות התלויות יתיישבו — ``setImmediate`` רץ אחרי תור ה-microtasks. */
const settle = () => new Promise((resolve) => setImmediate(resolve));
async function settleAll() { for (let i = 0; i < 10; i += 1) await settle(); }

/** תשובת ``fetch`` מדומה — רק מה שהקוד קורא ממנה. */
function response(status, body) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => {
      if (typeof body === 'string') throw new SyntaxError('Unexpected token < in JSON');
      return body;
    },
  };
}

/** כפתור מדומה, עם מה ש-``copyPreviewCode`` נוגע בו. */
function makeButton() {
  const attrs = {};
  const classes = new Set();
  return {
    disabled: false,
    innerHTML: '<i class="fas fa-copy"></i> <span class="btn-text">העתק</span>',
    setAttribute: (k, v) => { attrs[k] = String(v); },
    removeAttribute: (k) => { delete attrs[k]; },
    getAttribute: (k) => (k in attrs ? attrs[k] : null),
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) },
  };
}

/**
 * טוען את הסקריפט לסביבה חדשה.
 *
 * ``reply`` — מה ``fetch`` מחזיר (או זורק). ``clipboardItem: false`` — דפדפן בלי
 * ``ClipboardItem``. ``writeRejects`` — הלוח דוחה את הכתיבה.
 *
 * ``write`` המדומה מתנהג כמו במפרט (W3C Clipboard API): הוא מחכה להבטחה שבתוך
 * ה-``ClipboardItem``, ונדחה ב-``NotAllowedError`` כשהיא נדחית.
 */
function load({ reply, clipboardItem = true, writeRejects = false, secure = true } = {}) {
  const log = { fetches: [], writeCalls: 0, writeTextCalls: 0, written: [], alerts: [], timers: [] };
  let resolveFetch = null;
  const sandbox = {
    console: { log() {}, warn() {}, error() {} },
    setTimeout: (fn, ms) => { log.timers.push(ms); return 0; },
    clearTimeout() {},
    Blob,
    AbortSignal,
    AbortController,
    isSecureContext: secure,
    location: { href: '', pathname: '/files', search: '', hash: '' },
    alert: (m) => { log.alerts.push(m); },
    document: {
      addEventListener() {},
      querySelector() { return null; },
      getElementById() { return null; },
      createElement() { return {}; },
      head: { appendChild() {} },
    },
    fetch: (url, opts) => {
      log.fetches.push({ url, opts });
      if (reply === 'pending') return new Promise((r) => { resolveFetch = r; });
      if (reply instanceof Error) return Promise.reject(reply);
      return Promise.resolve(reply);
    },
    navigator: {
      clipboard: {
        write: (items) => {
          log.writeCalls += 1;
          return (async () => {
            let blob;
            try {
              blob = await items[0].items['text/plain'];
            } catch (_e) {
              const err = new Error('NotAllowedError'); err.name = 'NotAllowedError'; throw err;
            }
            if (writeRejects) { const err = new Error('denied'); err.name = 'NotAllowedError'; throw err; }
            log.written.push(await blob.text());
          })();
        },
        writeText: async (text) => {
          log.writeTextCalls += 1;
          if (writeRejects) { const err = new Error('denied'); err.name = 'NotAllowedError'; throw err; }
          log.written.push(text);
        },
      },
    },
  };
  if (clipboardItem) {
    sandbox.ClipboardItem = class ClipboardItem { constructor(items) { this.items = items; } };
  }
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SCRIPT, sandbox);
  return { cp: sandbox.window.cardPreview, log, sandbox, release: (r) => resolveFetch(r) };
}

const FILE_ID = '0123456789abcdef01230002';
const CODE = '    first = 1\r\nשורה = 2\n' + 'x\n'.repeat(40) + '\n\n';

await check('הכתיבה ללוח נפתחת בתוך הלחיצה, לפני שהשרת ענה', async () => {
  const h = load({ reply: 'pending' });
  const btn = makeButton();
  h.cp.copyPreviewCode(btn, FILE_ID);
  // סינכרוני, באותה לחיצה: הבקשה יצאה והכתיבה כבר נקראה, והשרת עוד לא ענה.
  eq(h.log.fetches.length, 1, 'מספר הבקשות');
  eq(h.log.writeCalls, 1, 'write לא נקרא בתוך הלחיצה');
  eq(btn.disabled, true, 'הכפתור לא הושבת בזמן ההמתנה');
  h.release(response(200, { ok: true, code: CODE, version: 3 }));
  await settleAll();
  eq(h.log.written.length, 1, 'מספר הכתיבות');
  eq(h.log.written[0], CODE, 'מה שנכתב ללוח');
});

await check('הבקשה היא לגרסה העדכנית, בלי מטמון ועם תקרת זמן', async () => {
  const h = load({ reply: response(200, { ok: true, code: CODE, version: 3 }) });
  h.cp.copyPreviewCode(makeButton(), FILE_ID);
  await settleAll();
  const { url, opts } = h.log.fetches[0];
  eq(url, `/api/file/${FILE_ID}/content`, 'הכתובת');
  eq(opts.cache, 'no-store', 'מדיניות המטמון');
  ok(opts.signal, 'אין סיגנל עם תקרת זמן');
});

await check('אחרי ההעתקה הכפתור אומר איזו גרסה הועתקה, ומשתחרר', async () => {
  const h = load({ reply: response(200, { ok: true, code: CODE, version: 3 }) });
  const btn = makeButton();
  h.cp.copyPreviewCode(btn, FILE_ID);
  await settleAll();
  ok(btn.innerHTML.includes('הועתקה גרסה 3'), btn.innerHTML);
  eq(btn.disabled, false, 'הכפתור נשאר מושבת');
  eq(btn.getAttribute('aria-busy'), null, 'aria-busy נשאר');
  eq(h.log.alerts.length, 0, 'הודעות');
});

await check('קובץ גדול, בלי גרסה: "הועתק!" בלי מספר', async () => {
  const h = load({ reply: response(200, { ok: true, code: CODE, version: null }) });
  const btn = makeButton();
  h.cp.copyPreviewCode(btn, FILE_ID);
  await settleAll();
  ok(btn.innerHTML.includes('הועתק!') && !btn.innerHTML.includes('גרסה'), btn.innerHTML);
});

await check('בלי ClipboardItem: writeText עם הקובץ כולו, אחרי שהתוכן הגיע', async () => {
  const h = load({ reply: response(200, { ok: true, code: CODE, version: 3 }), clipboardItem: false });
  h.cp.copyPreviewCode(makeButton(), FILE_ID);
  await settleAll();
  eq(h.log.writeCalls, 0, 'write');
  eq(h.log.writeTextCalls, 1, 'writeText');
  eq(h.log.written[0], CODE, 'מה שנכתב ללוח');
});

for (const [error, message] of [
  ['in_recycle_bin', 'הקובץ נמצא בסל המיחזור'],
  ['not_found', 'הקובץ לא נמצא — ייתכן שנמחק או ששמו שונה'],
  ['service_unavailable', 'אין כרגע חיבור למסד הנתונים — נסו שוב בעוד רגע'],
  ['db_error', 'שגיאה בקריאת הקובץ מהשרת — נסו שוב'],
]) {
  await check(`שגיאת שרת "${error}": הודעה ברורה, שום דבר לא נכתב, והכפתור חוזר`, async () => {
    const status = error === 'service_unavailable' ? 503 : (error === 'db_error' ? 500 : 404);
    const h = load({ reply: response(status, { ok: false, error }) });
    const btn = makeButton();
    const original = btn.innerHTML;
    h.cp.copyPreviewCode(btn, FILE_ID);
    await settleAll();
    eq(h.log.alerts.length, 1, 'מספר ההודעות');
    eq(h.log.alerts[0], message, 'ההודעה');
    eq(h.log.written.length, 0, 'נכתב ללוח');
    eq(btn.innerHTML, original, 'הכפתור לא חזר למצבו');
    eq(btn.disabled, false, 'הכפתור נשאר מושבת');
  });
}

await check('הלוח סירב: הודעה, ולא "הועתק"', async () => {
  const h = load({ reply: response(200, { ok: true, code: CODE, version: 3 }), writeRejects: true });
  const btn = makeButton();
  h.cp.copyPreviewCode(btn, FILE_ID);
  await settleAll();
  eq(h.log.alerts[0], 'הדפדפן לא אישר להעתיק ללוח — נסו שוב', 'ההודעה');
  ok(!btn.innerHTML.includes('הועתק'), btn.innerHTML);
});

for (const [label, body] of [
  ['גוף שאינו JSON', '<html>proxy error</html>'],
  ['בלי ok', { code: CODE }],
  ['code שאינו מחרוזת', { ok: true, code: 42 }],
]) {
  await check(`תשובה לא צפויה (${label}): הודעה, ושום דבר לא נכתב`, async () => {
    const h = load({ reply: response(200, body) });
    h.cp.copyPreviewCode(makeButton(), FILE_ID);
    await settleAll();
    eq(h.log.alerts[0], 'התקבלה מהשרת תשובה לא צפויה — נסו שוב', 'ההודעה');
    eq(h.log.written.length, 0, 'נכתב ללוח');
  });
}

await check('פקיעת תקרת הזמן מוצגת כ"לא ענה בזמן"', async () => {
  const timeout = new Error('signal timed out'); timeout.name = 'TimeoutError';
  const h = load({ reply: timeout });
  h.cp.copyPreviewCode(makeButton(), FILE_ID);
  await settleAll();
  eq(h.log.alerts[0], 'השרת לא ענה בזמן — נסו שוב', 'ההודעה');
});

await check('ההתחברות פגה: עוברים לדף ההתחברות, בלי הודעה', async () => {
  const h = load({ reply: response(401, { error: 'נדרש להתחבר' }) });
  h.cp.copyPreviewCode(makeButton(), FILE_ID);
  await settleAll();
  ok(h.sandbox.location.href.startsWith('/login?next='), h.sandbox.location.href);
  eq(h.log.alerts.length, 0, 'הודעות');
});

await check('דף שאינו בהקשר מאובטח: הודעה, ובלי בקשה', async () => {
  const h = load({ reply: response(200, { ok: true, code: CODE, version: 3 }), secure: false });
  h.cp.copyPreviewCode(makeButton(), FILE_ID);
  await settleAll();
  eq(h.log.fetches.length, 0, 'בקשות');
  eq(h.log.alerts[0], 'הדפדפן לא מאפשר העתקה ללוח בדף הזה', 'ההודעה');
});

await check('לחיצה נוספת בזמן שההעתקה רצה אינה שולחת בקשה נוספת', async () => {
  const h = load({ reply: 'pending' });
  const btn = makeButton();
  h.cp.copyPreviewCode(btn, FILE_ID);
  h.cp.copyPreviewCode(btn, FILE_ID);
  eq(h.log.fetches.length, 1, 'מספר הבקשות');
  h.release(response(200, { ok: true, code: CODE, version: 3 }));
  await settleAll();
  eq(h.log.written.length, 1, 'מספר הכתיבות');
});

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
