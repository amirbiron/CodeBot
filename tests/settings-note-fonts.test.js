'use strict';
// בדיקות על בורר גופן הפתקים שבעמוד ההגדרות.
//
// **למה קובץ חדש:** הלוגיקה חיה בסקריפט מוטבע ב-``settings.html``, ולא
// בקובץ ``.js``. עד כה אף בדיקה לא נגעה בעמוד ההגדרות כלל, ולכן שמירה
// שנכשלת, בחירה שלא הוחזרה, או בקשה ישנה שדורסת חדשה — כולן היו עוברות
// בשקט.
//
// החילוץ מעוגן בשמות מזהים ולא במספרי שורות: ``settings.html`` הוא מעל
// 4000 שורות ועם עשרות בלוקי ``<script>``, ולכן חיפוש ה-``<script>``
// הראשון (כמו ב-``board-handwriting.test.js``) היה תופס בלוק אחר לגמרי.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TEMPLATE = path.join(__dirname, '..', 'webapp', 'templates', 'settings.html');
const SRC = fs.readFileSync(TEMPLATE, 'utf8');

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
async function acheck(name, fn) {
  try { await fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}

/** מחלץ את ה-IIFE של גופן הפתקים לפי עוגני התחלה וסוף. */
function fontsScript() {
  const start = SRC.indexOf('// ── גופן הפתקים ──');
  if (start < 0) throw new Error('בלוק גופן הפתקים לא נמצא — העוגן השתנה');
  const end = SRC.indexOf('      })();', start);
  if (end < 0) throw new Error('סוף הבלוק לא נמצא — העוגן השתנה');
  return SRC.slice(start, end + '      })();'.length);
}

/** אלמנט ``<select>`` מדומה, עם מה שהקוד באמת נוגע בו. */
function mkSelect(surface, value) {
  const listeners = {};
  return {
    value,
    dataset: { surface },
    addEventListener: (t, fn) => { (listeners[t] = listeners[t] || []).push(fn); },
    __fire: async (t) => {
      for (const fn of (listeners[t] || [])) await fn();
    },
  };
}

/**
 * ``fetchImpl`` מקבל את גוף הבקשה המפורסר ומחזיר ``{ok, body}``.
 * ברירת המחדל: הצלחה.
 *
 * ``opts.toast`` — ``undefined``: טוסט שמצליח (המסלול הרגיל);
 * ``false``: טוסט שאינו מצליח להציג; ``null``: אין ``ckToast`` כלל.
 * שני האחרונים חייבים ליפול לשורת ההודעה, אחרת הודעת כשל שמירה נעלמת.
 */
function load(fetchImpl, opts = {}) {
  const sent = [];
  const msg = { textContent: '', style: { display: 'none', color: '' } };
  const selects = [
    mkSelect('repo', '0'),
    mkSelect('md', '0'),
    mkSelect('board', '0'),
  ];
  const scopeSel = mkSelect('__scope', 'global');

  const sandbox = {
    console: { error: () => {} },
    document: {
      getElementById: (id) => (id === 'noteFontsScopeSelect' ? scopeSel
                            : id === 'noteFontsMsg' ? msg : null),
      querySelectorAll: (sel) => (sel === '.note-font-select' ? selects : []),
    },
    Array, JSON, String, Promise, Error,
    fetch: async (url, opts) => {
      const body = JSON.parse(opts.body);
      sent.push(body);
      const out = fetchImpl ? await fetchImpl(body, sent.length) : { ok: true, body: { ok: true } };
      return {
        ok: out.ok !== false,
        status: out.status || (out.ok === false ? 500 : 200),
        json: async () => out.body,
      };
    },
  };
  const toasts = [];
  if (opts.toast !== null) {
    sandbox.ckToast = (message, type, o) => {
      toasts.push({ message, type, key: o && o.key });
      return opts.toast !== false;
    };
  }

  vm.createContext(sandbox);
  sandbox.window = sandbox;
  vm.runInContext(fontsScript(), sandbox);
  return { sent, msg, selects, scopeSel, toasts };
}

// ─── גוף הבקשה ──────────────────────────────────────────────────────────

await acheck('הבקשה נושאת את שלושת המשטחים ואת התחולה', async () => {
  const h = load();
  h.selects[1].value = '1';                 // md ← כתב יד
  await h.selects[1].__fire('change');

  eq(h.sent.length, 1, 'מספר בקשות');
  eq(JSON.stringify(h.sent[0].note_fonts),
     JSON.stringify({ repo: false, md: true, board: false }), 'note_fonts');
  eq(h.sent[0].note_fonts_scope, 'global', 'התחולה');
});

await acheck('הערכים בגוף הם בוליאנים, לא מחרוזות', async () => {
  // השרת דוחה כל דבר שאינו ``bool`` ב-400, ולכן ``"1"`` היה מפיל שמירה.
  const h = load();
  h.selects[0].value = '1';
  await h.selects[0].__fire('change');
  eq(typeof h.sent[0].note_fonts.repo, 'boolean', 'טיפוס');
  eq(h.sent[0].note_fonts.repo, true, 'ערך');
});

await acheck('שינוי התחולה שולח גם את הערכים', async () => {
  // מעבר מ-device ל-global חייב להעלות את המערך כולו ל-DB; שליחת
  // תחולה לבדה הייתה משאירה את ה-DB ריק ומאפסת בשקט את הכול.
  const h = load();
  h.selects[2].value = '1';
  await h.selects[2].__fire('change');
  h.scopeSel.value = 'device';
  await h.scopeSel.__fire('change');

  eq(h.sent.length, 2, 'מספר בקשות');
  eq(h.sent[1].note_fonts_scope, 'device', 'התחולה');
  eq(h.sent[1].note_fonts.board, true, 'הערך נשלח יחד');
});

// ─── כשל ────────────────────────────────────────────────────────────────

await acheck('כשל מחזיר את הבורר ומציג חיווי שגיאה', async () => {
  const h = load(async () => ({ ok: false, status: 500, body: null }));
  h.selects[1].value = '1';
  await h.selects[1].__fire('change');

  eq(h.selects[1].value, '0', 'הבורר הוחזר');
  eq(h.toasts.length, 1, 'מספר החיוויים');
  eq(h.toasts[0].type, 'error', 'סוג החיווי');
  eq(h.toasts[0].message.includes('נכשלה'), true, 'נוסח ההודעה');
});

await acheck('הצלחה מציגה אישור ואינה מחזירה כלום', async () => {
  const h = load();
  h.selects[0].value = '1';
  await h.selects[0].__fire('change');
  eq(h.selects[0].value, '1', 'הבורר נשאר');
  eq(h.toasts.length, 1, 'מספר החיוויים');
  eq(h.toasts[0].message, 'נשמר', 'ההודעה');
  eq(h.toasts[0].type, 'success', 'סוג החיווי');
});

await acheck('כשל מחזיר למצב האחרון שנשמר, לא לערך הקודם', async () => {
  let n = 0;
  const h = load(async () => { n += 1; return n === 1 ? { ok: true, body: { ok: true } }
                                                      : { ok: false, status: 500, body: null }; });
  h.selects[0].value = '1';
  await h.selects[0].__fire('change');        // נשמר בהצלחה
  h.selects[1].value = '1';
  await h.selects[1].__fire('change');        // נכשל

  eq(h.selects[0].value, '1', 'מה שנשמר נשאר');
  eq(h.selects[1].value, '0', 'מה שנכשל הוחזר');
});

// ─── המרוץ ──────────────────────────────────────────────────────────────

await acheck('שינויים מהירים — הבקשה האחרונה נושאת את המצב הסופי', async () => {
  // **זה הבאג שהתור מונע.** בלעדיו שתי הבקשות יוצאות במקביל, וזו שנוחתת
  // אחרונה — ולא זו שנבחרה אחרונה — קובעת מה יישמר.
  let release;
  const gate = new Promise((r) => { release = r; });
  let first = true;
  const h = load(async () => {
    if (first) { first = false; await gate; }
    return { ok: true, body: { ok: true } };
  });

  h.selects[0].value = '1';
  const p1 = h.selects[0].__fire('change');   // נתקעת בשער
  h.selects[1].value = '1';
  await h.selects[1].__fire('change');        // חייבת להמתין, לא לצאת במקביל

  eq(h.sent.length, 1, 'רק בקשה אחת באוויר');
  release();
  await p1;

  eq(h.sent.length, 2, 'הבקשה השנייה יצאה אחרי הראשונה');
  eq(JSON.stringify(h.sent[1].note_fonts),
     JSON.stringify({ repo: true, md: true, board: false }), 'המצב הסופי');
});

await acheck('רסט של שלושה שינויים מתכווץ לשתי בקשות', async () => {
  let release;
  const gate = new Promise((r) => { release = r; });
  let first = true;
  const h = load(async () => {
    if (first) { first = false; await gate; }
    return { ok: true, body: { ok: true } };
  });

  h.selects[0].value = '1';
  const p = h.selects[0].__fire('change');
  h.selects[1].value = '1';
  await h.selects[1].__fire('change');
  h.selects[2].value = '1';
  await h.selects[2].__fire('change');

  release();
  await p;
  eq(h.sent.length, 2, 'שתיים, לא שלוש');
  eq(h.sent[1].note_fonts.board, true, 'האחרונה נושאת את הכול');
});

await acheck('הצלחה ואז כשל באותו תור — ההחזרה תואמת את מה שנשמר', async () => {
  // **התרחיש שהריוויוור תיאר.** שינוי ראשון נשלח ומצליח; שינוי שני
  // נכנס לתור בזמן שהראשון באוויר, ונכשל. בלי עדכון ``lastSaved`` אחרי
  // **כל** שליחה מוצלחת, ההחזרה הייתה מחזירה את הבוררים למצב שלפני
  // שניהם — בעוד שהשרת כבר קיבל את הראשון. המסך היה סותר את השרת.
  let release;
  const gate = new Promise((r) => { release = r; });
  let n = 0;
  const h = load(async () => {
    n += 1;
    if (n === 1) { await gate; return { ok: true, body: { ok: true } }; }
    return { ok: false, status: 500, body: null };   // השנייה נכשלת
  });

  h.selects[0].value = '1';
  const p1 = h.selects[0].__fire('change');   // נשלחת, ממתינה בשער
  h.selects[1].value = '1';
  await h.selects[1].__fire('change');        // נכנסת לתור
  release();
  await p1;

  eq(h.sent.length, 2, 'שתי בקשות');
  eq(h.selects[0].value, '1', 'מה שהשרת קיבל נשאר על המסך');
  eq(h.selects[1].value, '0', 'מה שנכשל הוחזר');
  eq(h.toasts[h.toasts.length - 1].type, 'error', 'החיווי האחרון');
});

await acheck('הגוף שנשלח תואם ל-snapshot של אותו רגע', async () => {
  // אם הגוף היה נקרא מה-DOM בנפרד מה-snapshot, שינוי שקורה ביניהם היה
  // נשלח אבל לא נרשם כ"נשמר" — או ההפך.
  let release;
  const gate = new Promise((r) => { release = r; });
  let first = true;
  const h = load(async () => {
    if (first) { first = false; await gate; }
    return { ok: true, body: { ok: true } };
  });

  h.selects[0].value = '1';
  const p = h.selects[0].__fire('change');
  h.selects[2].value = '1';
  await h.selects[2].__fire('change');
  release();
  await p;

  eq(JSON.stringify(h.sent[0].note_fonts),
     JSON.stringify({ repo: true, md: false, board: false }), 'הראשונה');
  eq(JSON.stringify(h.sent[1].note_fonts),
     JSON.stringify({ repo: true, md: false, board: true }), 'השנייה');
});

// ─── החיווי ─────────────────────────────────────────────────────────────

await acheck('שתי שמירות מוצלחות מפיקות שני חיוויים', async () => {
  // **זה הבאג שדווח.** בגרסה הקודמת החיווי היה שורת סטטוס קבועה, ושמירה
  // שנייה כתבה בה את אותה מחרוזת בדיוק — אפס שינוי ב-DOM, ולכן אפס חיווי.
  // בדיקה על תוכן השורה הייתה עוברת גם על הקוד השבור; רק ספירת אירועים
  // מבחינה ביניהם.
  const h = load();
  h.selects[0].value = '1';
  await h.selects[0].__fire('change');
  h.selects[1].value = '1';
  await h.selects[1].__fire('change');

  eq(h.sent.length, 2, 'שתי בקשות');
  eq(h.toasts.length, 2, 'שני חיוויים — לא אחד');
  eq(h.toasts[1].message, 'נשמר', 'גם השני');
});

await acheck('כל החיוויים נושאים מפתח אחיד', async () => {
  // המפתח הוא מה שגורם לחיווי חדש להחליף את הקודם במקום להיערם לצידו.
  const h = load();
  h.selects[0].value = '1';
  await h.selects[0].__fire('change');
  h.scopeSel.value = 'device';
  await h.scopeSel.__fire('change');

  eq(h.toasts.length, 2, 'שני חיוויים');
  eq(h.toasts[0].key, 'note-fonts', 'מפתח ראשון');
  eq(h.toasts[1].key, 'note-fonts', 'מפתח שני');
});

await acheck('בלי ckToast — ההודעה נופלת לשורת הגיבוי', async () => {
  // ``toast.js`` נטען ב-``defer``. אם הוא לא הגיע, הודעת כשל שמירה
  // חייבת עדיין להגיע למשתמש.
  const h = load(async () => ({ ok: false, status: 500, body: null }), { toast: null });
  h.selects[1].value = '1';
  await h.selects[1].__fire('change');

  eq(h.msg.style.display, 'block', 'השורה מוצגת');
  eq(h.msg.textContent.includes('נכשלה'), true, 'נוסח ההודעה');
});

await acheck('ckToast שהחזירה false — נופלת לשורת הגיבוי', async () => {
  // ``ckToast`` מדווחת כשל בערך ההחזרה ולא בזריקה. קורא שמתעלם ממנו
  // מציג "הכול תקין" על חיווי שלא הוצג — K11 בדפוסי הבאגים.
  const h = load(async () => ({ ok: false, status: 500, body: null }), { toast: false });
  h.selects[1].value = '1';
  await h.selects[1].__fire('change');

  eq(h.toasts.length, 1, 'הטוסט נוסה');
  eq(h.msg.style.display, 'block', 'ובכל זאת השורה הוצגה');
  eq(h.msg.textContent.includes('נכשלה'), true, 'נוסח ההודעה');
});

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
