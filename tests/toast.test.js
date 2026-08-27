'use strict';
// בדיקות ל-``webapp/static/js/toast.js`` — טוסט החיווי של עמוד ההגדרות.
//
// **מה הבדיקות האלה כן מוכיחות:** את הלוגיקה — בריחה מ-HTML, רשימת ההיתר
// של הסוג, ההחלפה לפי מפתח, ביטול הטיימרים, וערוץ הכשל.
//
// **ומה לא:** שהטוסט באמת נראה ומונפש. DOM מזויף לא אוכף פריסה, מעברים או
// ערכות נושא. את זה מוכיחה רק הרצה בדפדפן אמיתי — ראו כלל 2 ב-
// ``claude-md-snippets/testing.md``.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(
  path.join(__dirname, '..', 'webapp', 'static', 'js', 'toast.js'), 'utf8');

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}
function ok(v, what) { if (!v) throw new Error(what || 'ציפיתי לאמת'); }

/** אלמנט מדומה — רק מה ש-``toast.js`` באמת נוגע בו. */
function mkEl() {
  const el = {
    id: '', className: '', textContent: '',
    attrs: {}, children: [], parentNode: null,
    // קריאתו היא שמכריחה reflow בקוד האמיתי; כאן רק סופרים.
    reads: 0,
    get offsetWidth() { el.reads += 1; return 1; },
    setAttribute: (k, v) => { el.attrs[k] = v; },
    appendChild: (c) => { c.parentNode = el; el.children.push(c); return c; },
    removeChild: (c) => {
      const i = el.children.indexOf(c);
      if (i >= 0) el.children.splice(i, 1);
      c.parentNode = null;
      return c;
    },
    classList: {
      add: (c) => { if (!el.className.split(' ').includes(c)) el.className += ' ' + c; },
      remove: (c) => {
        el.className = el.className.split(' ').filter((x) => x && x !== c).join(' ');
      },
      contains: (c) => el.className.split(' ').includes(c),
    },
  };
  return el;
}

/**
 * טוען את הסקריפט לסנדבוקס עם DOM וטיימרים נשלטים.
 * ``withBody: false`` מדמה קריאה לפני שה-``body`` קיים.
 */
function load({ withBody = true } = {}) {
  const body = withBody ? mkEl() : null;
  const byId = new Map();
  let now = 0, seq = 0;
  const timers = new Map();          // id ← { at, fn }

  const sandbox = {
    Object, String, Array, JSON, Error,
    document: {
      get body() { return body; },
      getElementById: (id) => byId.get(id) || null,
      createElement: () => mkEl(),
    },
    setTimeout: (fn, ms) => {
      const id = ++seq;
      timers.set(id, { at: now + ms, fn });
      return id;
    },
    clearTimeout: (id) => { timers.delete(id); },
  };
  vm.createContext(sandbox);
  sandbox.window = sandbox;
  vm.runInContext(SRC, sandbox);

  // הקונטיינר נרשם ב-``byId`` ברגע שנוצר, כמו ``document.getElementById``.
  const origAppend = body ? body.appendChild : null;
  if (body) {
    body.appendChild = (c) => { if (c.id) byId.set(c.id, c); return origAppend(c); };
  }

  return {
    toast: (...a) => sandbox.window.ckToast(...a),
    body,
    container: () => byId.get('ckToastContainer') || null,
    pending: () => timers.size,
    // שעון אירועים בדיד: ``now`` מתקדם **אל** כל טיימר לפי סדר, ולא קופץ
    // ואז מנקז. ההבדל אינו קוסמטי — טיימר שנקבע מתוך callback נמדד מזמן
    // הירי שלו, וקפיצה מראש הייתה דוחה אותו מעבר לחלון הנבדק.
    advance: (ms) => {
      const target = now + ms;
      for (;;) {
        let nextId = null, next = null;
        for (const [id, t] of timers) {
          if (t.at <= target && (next === null || t.at < next.at)) { nextId = id; next = t; }
        }
        if (next === null) { now = target; return; }
        now = next.at;
        timers.delete(nextId);
        next.fn();
      }
    },
  };
}

// ─── בריחה וולידציה ─────────────────────────────────────────────────────

check('ההודעה נכתבת כטקסט, לא כ-HTML', () => {
  // הקורא מעביר גם ``data.error`` מהשרת. ``bulk-actions.js:440`` מזריק
  // ערך כזה ל-``innerHTML``; כאן זה חייב להישאר טקסט. K4 בדפוסי הבאגים.
  const h = load();
  const evil = '<img src=x onerror=alert(1)>';
  h.toast(evil, 'error');
  const card = h.container().children[0];
  const msg = card.children[1];
  eq(msg.textContent, evil, 'ההודעה');
  eq(msg.children.length, 0, 'לא נוצרו צאצאים מההודעה');
});

check('סוג לא מוכר אינו נכנס לשם המחלקה', () => {
  // ``type`` משורשר לתוך ``className``. בלי רשימת היתר, ערך שרירותי
  // מזריק מחלקות.
  const h = load();
  h.toast('שלום', 'evil ck-toast--success');
  const card = h.container().children[0];
  eq(card.className.includes('ck-toast--info'), true, 'נפילה ל-info');
  eq(card.className.includes('evil'), false, 'הערך לא חלחל');
});

check('כל סוג מוכר מקבל את המחלקה ואת האייקון שלו', () => {
  const expect = { success: '✓', error: '✕', warning: '⚠', info: 'ℹ' };
  for (const [type, icon] of Object.entries(expect)) {
    const h = load();
    h.toast('טקסט', type);
    const card = h.container().children[0];
    eq(card.className.includes('ck-toast--' + type), true, `מחלקה ל-${type}`);
    eq(card.children[0].textContent, icon, `אייקון ל-${type}`);
  }
});

check('האייקון מוסתר מקורא מסך', () => {
  const h = load();
  h.toast('טקסט', 'success');
  eq(h.container().children[0].children[0].attrs['aria-hidden'], 'true', 'aria-hidden');
});

// ─── כניסה ──────────────────────────────────────────────────────────────

check('מאפיין הפריסה נקרא לפני הוספת מחלקת הכניסה', () => {
  // בלי הקריאה הזו אין reflow, הדפדפן מקבץ את שני הסגנונות, ואין ממה
  // להנפיש — הטוסט פשוט מופיע. זו הסיבה היחידה שהשורה קיימת.
  const h = load();
  h.toast('נשמר', 'success');
  const card = h.container().children[0];
  eq(card.reads > 0, true, 'offsetWidth נקרא');
  eq(card.classList.contains('is-shown'), true, 'מחלקת הכניסה');
});

check('הקונטיינר נוצר פעם אחת בלבד', () => {
  const h = load();
  h.toast('א', 'info');
  h.toast('ב', 'info');
  eq(h.body.children.length, 1, 'ילדי body');
  eq(h.container().children.length, 2, 'שני טוסטים באותו קונטיינר');
  eq(h.container().attrs['aria-live'], 'polite', 'aria-live');
});

// ─── מפתח והחלפה ────────────────────────────────────────────────────────

check('אותו מפתח מחליף במקום לערום', () => {
  // **זה הבאג שדווח.** בלי זה, שלוש שמירות ברצף מייצרות שלושה כרטיסים
  // זהים זה לצד זה.
  const h = load();
  h.toast('נשמר', 'success', { key: 'k' });
  const first = h.container().children[0];
  h.toast('נשמר', 'success', { key: 'k' });

  eq(h.container().children.length, 1, 'כרטיס אחד');
  eq(first.parentNode, null, 'הקודם נותק');
  eq(h.container().children[0] === first, false, 'זהו כרטיס חדש');
  eq(h.container().children[0].classList.contains('is-shown'), true, 'נכנס מחדש');
});

check('מפתחות שונים מצטברים', () => {
  const h = load();
  h.toast('א', 'info', { key: 'a' });
  h.toast('ב', 'info', { key: 'b' });
  eq(h.container().children.length, 2, 'שני כרטיסים');
});

check('בלי מפתח — מצטבר', () => {
  const h = load();
  h.toast('א', 'info');
  h.toast('ב', 'info');
  eq(h.container().children.length, 2, 'שני כרטיסים');
});

check('ההחלפה מבטלת את הטיימרים של הקודם', () => {
  // בלי ``clearTimeout``, כל שמירה משאירה טיימר תלוי על כרטיס מנותק.
  // בהחלפה מהירה חוזרת הם נערמים בלי גבול.
  const h = load();
  h.toast('נשמר', 'success', { key: 'k' });
  eq(h.pending(), 1, 'טיימר אחד אחרי הראשון');
  h.toast('נשמר', 'success', { key: 'k' });
  eq(h.pending(), 1, 'עדיין אחד אחרי ההחלפה — לא שניים');
});

check('טיימר של כרטיס שהוחלף אינו נוגע בחדש', () => {
  const h = load();
  h.toast('ראשון', 'success', { key: 'k' });
  h.advance(3900);                       // כמעט הגיע זמנו של הראשון
  h.toast('שני', 'success', { key: 'k' });
  h.advance(200);                        // הזמן שבו הראשון היה נעלם
  const card = h.container().children[0];
  eq(h.container().children.length, 1, 'הכרטיס עדיין שם');
  eq(card.classList.contains('is-shown'), true, 'ועדיין מוצג');
  eq(card.children[1].textContent, 'שני', 'וזה החדש');
});

// ─── היעלמות ────────────────────────────────────────────────────────────

check('נעלם מעצמו אחרי ברירת המחדל', () => {
  const h = load();
  h.toast('נשמר', 'success', { key: 'k' });
  h.advance(3999);
  eq(h.container().children.length, 1, 'לפני הזמן — עדיין שם');
  h.advance(1);
  eq(h.container().children[0].classList.contains('is-shown'), false, 'יציאה החלה');
  eq(h.container().children.length, 1, 'עדיין ב-DOM בזמן היציאה');
  h.advance(300);
  eq(h.container().children.length, 0, 'הוסר');
  eq(h.pending(), 0, 'לא נשארו טיימרים');
});

check('duration מותאם מכובד', () => {
  const h = load();
  h.toast('נשמר', 'success', { duration: 1000 });
  h.advance(1000);
  eq(h.container().children[0].classList.contains('is-shown'), false, 'יציאה מוקדמת');
});

check('אחרי היעלמות, מפתח זהה נפתח מחדש', () => {
  const h = load();
  h.toast('א', 'success', { key: 'k' });
  h.advance(4300);
  eq(h.container().children.length, 0, 'נוקה');
  h.toast('ב', 'success', { key: 'k' });
  eq(h.container().children.length, 1, 'נפתח מחדש');
  eq(h.container().children[0].classList.contains('is-shown'), true, 'ומוצג');
});

// ─── ערוץ הכשל ──────────────────────────────────────────────────────────

check('מחזירה true כשהוצגה', () => {
  const h = load();
  eq(h.toast('נשמר', 'success'), true, 'ערך ההחזרה');
});

check('מחזירה false כשאין body — ולא זורקת', () => {
  // הקורא בעמוד ההגדרות נשען על הערך הזה כדי ליפול לשורת הגיבוי. אם
  // הפונקציה הייתה מחזירה undefined בשקט, הודעת כשל שמירה הייתה נעלמת.
  const h = load({ withBody: false });
  eq(h.toast('השמירה נכשלה', 'error'), false, 'ערך ההחזרה');
});

check('הודעה ריקה או חסרה אינה מייצרת "undefined"', () => {
  const h = load();
  h.toast(undefined, 'info');
  eq(h.container().children[0].children[1].textContent, '', 'טקסט ריק');
});

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
