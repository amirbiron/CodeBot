'use strict';
// בדיקות ל-``webapp/static/js/repo-notes.js`` — הדבק בין דפדפן הריפו
// למנהל הפתקים. ההתקנה: sandbox של vm עם DOM מינימלי ו-StickyNotesManager
// מזויף, כמו ב-``sticky-notes-target.test.js``. הבדיקה המרכזית היא שמעברי
// יעד מהירים אינם משאירים ``current``/manager במצב מיושן — ה-P1 שהריוויו
// סימן.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'repo-notes.js');

let passed = 0, failed = 0;
const pending = [];
function check(name, fn) {
  try {
    const out = fn();
    if (out && typeof out.then === 'function') {
      pending.push(out.then(() => { passed += 1; },
        (e) => { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }));
    } else { passed += 1; }
  } catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}
const tick = () => new Promise((r) => setTimeout(r, 0));

function makeSandbox() {
  const store = {};
  const listeners = {};
  const button = { style: {}, classList: { toggle() {}, add() {}, remove() {} },
                   setAttribute() {}, addEventListener() {} };
  const host = { style: {}, querySelector: () => null, appendChild() {} };
  const repoHolder = { dataset: { repo: 'CodeBot' } };

  // רישום כל בנייה של מנהל, וכמה מהם פורקו
  const built = [];
  class FakeManager {
    constructor(opts) { this.opts = opts; this.destroyed = false; built.push(this); }
    async destroy() { this.destroyed = true; }
  }

  const sandbox = {
    console,
    __built: built,
    document: {
      addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
      dispatch(type, detail) { (listeners[type] || []).forEach((fn) => fn({ detail })); },
      getElementById(id) {
        if (id === 'code-viewer-container') return host;
        if (id === 'current-repo-name') return repoHolder;
        if (id === 'repo-notes-toggle') return button;
        return null;
      },
    },
    window: {
      StickyNotesManager: FakeManager,
      getComputedStyle: () => ({ position: 'relative' }),
      localStorage: {
        getItem: (k) => (k in store ? store[k] : null),
        setItem: (k, v) => { store[k] = String(v); },
        removeItem: (k) => { delete store[k]; },
      },
    },
    setTimeout, clearTimeout,
  };
  sandbox.window.localStorage = sandbox.window.localStorage;
  // repo-notes.js פונה ל-``window.localStorage`` וגם ל-``localStorage`` הגלובלי
  sandbox.localStorage = sandbox.window.localStorage;
  sandbox.CustomEvent = function (type, init) { return { type, detail: (init || {}).detail }; };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox;
}

// -- מעבר יעד בסיסי --

check('אירוע file-loaded מרכיב מנהל כשההעדפה דלוקה', async () => {
  const sb = makeSandbox();
  sb.window.localStorage.setItem('repo-notes:CodeBot:a.py', '1'); // דלוק
  sb.document.dispatch('repo:file-loaded', { repo: 'CodeBot', path: 'a.py' });
  await sb.window.repoNotes.settled();
  eq(sb.window.repoNotes.target().path, 'a.py', 'יעד — נתיב');
  // **הזהות היא הזוג, לא הנתיב.** בלי הבדיקה על ``repo`` היה אפשר לאבד
  // את שם הריפו לגמרי — היעד, המנהל וההעדפה — והחבילה כולה עוברת.
  eq(sb.window.repoNotes.target().repo, 'CodeBot', 'יעד — ריפו');
  eq(sb.window.repoNotes.hasManager(), true, 'מנהל הורכב');
  eq(sb.__built.length, 1, 'מנהל אחד נבנה');
  eq(sb.__built[0].opts.repo, 'CodeBot', 'הריפו הועבר למנהל');
  eq(sb.__built[0].opts.path, 'a.py', 'והנתיב איתו');
});

check('אותו נתיב בשני ריפואים אינו אותו יעד', async () => {
  // ההעדפה נשמרת תחת ``repo-notes:<repo>:<path>``, ולכן קובץ בשם זהה בשני
  // ריפואים חייב להישאר שני מצבים נפרדים. נופל אם המפתח (או היעד) יאבד
  // את שם הריפו — ואז הדלקה בריפו אחד הייתה מדליקה גם בשני.
  const sb = makeSandbox();
  sb.window.localStorage.setItem('repo-notes:CodeBot:shared.py', '1');

  sb.document.dispatch('repo:file-loaded', { repo: 'OtherRepo', path: 'shared.py' });
  await sb.window.repoNotes.settled();
  eq(sb.window.repoNotes.target().repo, 'OtherRepo', 'הריפו השני');
  eq(sb.window.repoNotes.isEnabled(), false, 'ההעדפה של CodeBot לא זלגה');
  eq(sb.window.repoNotes.hasManager(), false, 'ולכן אין מנהל');

  sb.document.dispatch('repo:file-loaded', { repo: 'CodeBot', path: 'shared.py' });
  await sb.window.repoNotes.settled();
  eq(sb.window.repoNotes.target().repo, 'CodeBot', 'חזרה לריפו הראשון');
  eq(sb.window.repoNotes.isEnabled(), true, 'ושם ההעדפה כן דלוקה');
  eq(sb.__built.length, 1, 'רק הריפו עם ההעדפה בנה מנהל');
  eq(sb.__built[0].opts.repo, 'CodeBot', 'והוא נושא את הריפו הנכון');
});

check('קובץ בלי העדפה שמורה — כבוי, בלי מנהל', async () => {
  const sb = makeSandbox();
  sb.document.dispatch('repo:file-loaded', { repo: 'CodeBot', path: 'b.py' });
  await sb.window.repoNotes.settled();
  eq(sb.window.repoNotes.isEnabled(), false, 'כבוי');
  eq(sb.window.repoNotes.hasManager(), false, 'אין מנהל');
});

check('setEnabled שומר העדפה פר-קובץ — ומחיל אותה בפועל', async () => {
  // ההעדפה היא רק החצי השני. ``applyEnabled`` גם מרכיב מנהל בהדלקה וגם
  // מפרק אותו בכיבוי, ובלי הבדיקות האלה רגרסיה שמפסיקה להרכיב (או משאירה
  // מנהל מת חי) הייתה עוברת: ה-localStorage היה נראה נכון והמסך לא.
  const sb = makeSandbox();
  sb.document.dispatch('repo:file-loaded', { repo: 'CodeBot', path: 'c.py' });
  await sb.window.repoNotes.settled();
  eq(sb.window.repoNotes.hasManager(), false, 'לפני ההדלקה אין מנהל');

  await sb.window.repoNotes.setEnabled(true);
  eq(sb.window.localStorage.getItem('repo-notes:CodeBot:c.py'), '1', 'נשמר דלוק');
  eq(sb.window.repoNotes.isEnabled(), true, 'המצב דלוק');
  eq(sb.window.repoNotes.hasManager(), true, 'ומנהל הורכב');
  eq(sb.__built.length, 1, 'מנהל אחד');

  await sb.window.repoNotes.setEnabled(false);
  eq(sb.window.localStorage.getItem('repo-notes:CodeBot:c.py'), null, 'כיבוי מוחק');
  eq(sb.window.repoNotes.isEnabled(), false, 'המצב כבוי');
  eq(sb.window.repoNotes.hasManager(), false, 'והמנהל פורק');
  eq(sb.__built[0].destroyed, true, 'הפירוק באמת רץ');
});

// -- ה-P1: מעברים מהירים לא משאירים מצב מיושן --

check('קובץ שדילגו עליו כלל אינו נבנה', async () => {
  // המשתמש עבר A→B מהר. ה-generation guard מבטיח שמעבר A, שכבר נעקף,
  // לא ירכיב מנהל בכלל — לא רק שיתפרק אחר כך. בלי ה-guard, A נבנה
  // ומיד פורק: עבודה מיותרת, בקשת רשת מיותרת, והבהוב UI.
  //
  // נופל אם ``applyTarget`` לא בודק ``myGen !== generation``.
  const sb = makeSandbox();
  sb.window.localStorage.setItem('repo-notes:CodeBot:A.py', '1');
  sb.window.localStorage.setItem('repo-notes:CodeBot:B.py', '1');
  sb.document.dispatch('repo:file-loaded', { repo: 'CodeBot', path: 'A.py' });
  sb.document.dispatch('repo:file-loaded', { repo: 'CodeBot', path: 'B.py' });
  await sb.window.repoNotes.settled();

  eq(sb.window.repoNotes.target().path, 'B.py', 'התייצב על האחרון');
  eq(sb.window.repoNotes.hasManager(), true, 'יש מנהל חי');
  // **רק B נבנה** — A נעקף לפני ההרכבה.
  eq(sb.__built.length, 1, 'מנהל אחד בלבד נבנה (A דולג)');
  eq(sb.__built[0].opts.path, 'B.py', 'והוא של הקובץ האחרון');
});

check('שרשרת המעברים מונעת interleaving כשהפירוק איטי', async () => {
  // הפירוק ממתין ל-flush; בלי סדרור, ``current`` של מעבר איטי היה נדרס
  // אחרי שמעבר מאוחר כבר התייצב. השרשרת מריצה כל מעבר עד הסוף לפני הבא.
  //
  // נופל אם ``enqueue`` מריץ במקביל במקום לסדר בשרשרת.
  const sb = makeSandbox();
  // מנהל עם פירוק איטי — מכריח את החלון שבו interleaving היה קורה
  const order = [];
  sb.window.StickyNotesManager = class {
    constructor(opts) {
      this.opts = opts; this.destroyed = false;
      sb.__built.push(this); order.push('mount:' + opts.path);
    }
    async destroy() { await new Promise((r) => setTimeout(r, 8)); this.destroyed = true; order.push('destroy:' + this.opts.path); }
  };
  sb.window.localStorage.setItem('repo-notes:CodeBot:X.py', '1');
  sb.document.dispatch('repo:file-loaded', { repo: 'CodeBot', path: 'X.py' });
  await sb.window.repoNotes.settled();               // X מורכב
  sb.window.localStorage.setItem('repo-notes:CodeBot:Y.py', '1');
  sb.window.localStorage.setItem('repo-notes:CodeBot:Z.py', '1');
  sb.document.dispatch('repo:file-loaded', { repo: 'CodeBot', path: 'Y.py' });
  sb.document.dispatch('repo:file-loaded', { repo: 'CodeBot', path: 'Z.py' });
  await sb.window.repoNotes.settled();

  eq(sb.window.repoNotes.target().path, 'Z.py', 'התייצב על Z');
  const live = sb.__built.filter((m) => !m.destroyed);
  eq(live.length, 1, 'מנהל חי אחד');
  eq(live[0].opts.path, 'Z.py', 'והוא Z');
  // **זו הטענה עצמה, ולא רק התוצאה הסופית:** הפירוק האיטי של X הסתיים
  // *לפני* ש-Z הורכב. בהרצה מקבילית ``mount:Z.py`` היה מקדים אותו, ואז שני
  // מנהלים היו חיים יחד על אותו קונטיינר — והתור של X היה מתנקז לתוכו.
  // (Y אינו מופיע כלל: הוא נעקף לפני ההרכבה, וזה בדיוק ה-generation guard.)
  eq(order.join(','), 'mount:X.py,destroy:X.py,mount:Z.py', 'סדר הפעולות');
});

check('מעבר למסך הפתיחה (path=null) מפרק ולא משאיר מנהל', async () => {
  const sb = makeSandbox();
  sb.window.localStorage.setItem('repo-notes:CodeBot:d.py', '1');
  sb.document.dispatch('repo:file-loaded', { repo: 'CodeBot', path: 'd.py' });
  await sb.window.repoNotes.settled();
  eq(sb.window.repoNotes.hasManager(), true, 'הורכב');
  sb.document.dispatch('repo:file-loaded', { repo: 'CodeBot', path: null });
  await sb.window.repoNotes.settled();
  eq(sb.window.repoNotes.hasManager(), false, 'פורק במסך הפתיחה');
  eq(sb.window.repoNotes.isEnabled(), false, 'כבוי');
});

(async () => {
  await Promise.all(pending);
  console.log(`\n${passed} עברו, ${failed} נכשלו`);
  process.exit(failed === 0 ? 0 : 1);
})();
