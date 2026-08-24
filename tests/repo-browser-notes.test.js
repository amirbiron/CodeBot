'use strict';
// בדיקות לתפר שבין ``webapp/static/js/repo-browser.js`` לפתקים: מי פולט את
// ``repo:file-loaded``, מתי, ועם איזה ריפו.
//
// **למה זה שווה בדיקה משלו:** טעינת קובץ אסינכרונית, ושתי לחיצות מהירות
// משאירות שתי טעינות באוויר. מי שנוחת אחרון — ולא מי שנבחר אחרון — היה
// קובע איזה מנהל פתקים מורכב, ועל איזה תוכן.
//
// ההתקנה: sandbox של vm עם DOM מינימלי. הקובץ עצמו נטען כמו שהוא, ורק
// הפונקציות הכבדות (CodeMirror, מארקדאון, ברדקראמבס) מוחלפות בפעולות ריקות
// אחרי הטעינה — הן הצהרות ``function`` בטופ-לבל, ולכן ניתנות להחלפה.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'repo-browser.js');
const SRC = fs.readFileSync(MODULE_PATH, 'utf8');

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
const delay = (ms) => new Promise((r) => setTimeout(r, ms));

function makeSandbox() {
  const el = () => ({
    style: {}, dataset: {}, innerHTML: '',
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    appendChild() {}, addEventListener() {}, removeEventListener() {},
    querySelector: () => null, querySelectorAll: () => [],
    setAttribute() {}, getAttribute: () => null, remove() {}, click() {}, focus() {}, blur() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }),
  });
  // האלמנט שמחזיק את שם הריפו — היחיד שהבדיקות משנות תוך כדי ריצה.
  const repoHolder = el();
  repoHolder.dataset.repo = 'CodeBot';
  const cache = new Map([['current-repo-name', repoHolder]]);

  const events = [];
  // ``fetch`` בשליטת הבדיקה: כל נתיב מקבל שער משלו, והבדיקה מחליטה מתי
  // (ואם) הוא נפתח. זה החלון שבו שתי טעינות חיות בו-זמנית.
  const gates = new Map();

  const sandbox = {
    // ``selectFile`` מדווח כשל טעינה ל-console בעצמו; בבדיקה שמזריקה כשל
    // בכוונה זה רעש, לא ממצא.
    console: { log: console.log, warn() {}, error() {} },
    __events: events,
    __repoHolder: repoHolder,
    __openGate(p, value) { (gates.get(p) || {}).resolve?.(value); },
    __failGate(p, err) { (gates.get(p) || {}).reject?.(err); },
    document: {
      body: el(), documentElement: el(),
      getElementById(id) {
        if (!cache.has(id)) cache.set(id, el());
        return cache.get(id);
      },
      querySelector: () => null,
      querySelectorAll: () => [],
      createElement: () => el(),
      addEventListener() {}, removeEventListener() {},
      // שומרים גם את **שם** האירוע: repo-notes.js מאזין למחרוזת מדויקת,
      // ושינוי שם היה שובר את הרכבת הפתקים בעוד כל הטסטים ממשיכים לעבור.
      dispatchEvent(ev) { events.push({ type: ev.type, ...ev.detail }); return true; },
    },
    window: {
      addEventListener() {}, removeEventListener() {},
      innerWidth: 1024, innerHeight: 768,
      location: { hash: '', search: '', href: '' },
      matchMedia: () => ({ matches: false }),
      history: { replaceState() {} },
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    navigator: { clipboard: {} },
    fetch(url) {
      const p = decodeURIComponent(String(url).replace(/^.*\/file\//, '').replace(/\?.*$/, ''));
      return new Promise((resolve, reject) => {
        gates.set(p, {
          resolve: (value) => resolve({ json: async () => (value || { content: '', language: 'python' }) }),
          reject,
        });
      });
    },
    setTimeout, clearTimeout, setInterval, clearInterval,
    requestAnimationFrame: (f) => setTimeout(f, 0),
  };
  sandbox.CustomEvent = function (type, init) { return { type, detail: (init || {}).detail }; };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);

  // נטרול כל מה שאינו התפר הנבדק. הצהרות ``function`` בטופ-לבל יושבות על
  // האובייקט הגלובלי, ולכן ההחלפה כאן היא זו שתיקרא מתוך ``selectFile``.
  for (const name of ['initCodeViewer', 'enableMarkdownPreview', 'disableMarkdownPreview',
                      'updateBreadcrumbs', 'updateFileHeader', 'updateFileInfo',
                      'updateMarkdownToggleVisibility', 'addToRecentFiles', 'updateUrlHash',
                      'closeInFileSearch', 'closeMobileSidebar']) {
    sandbox[name] = () => {};
  }
  return sandbox;
}

// -- ניקוי מיד, הרכבה רק בסוף --

check('הבחירה מנקה פתקים מיד, ומרכיבה רק אחרי שהקובץ נטען', async () => {
  // בלי הניקוי המוקדם, הפתקים של הקובץ הקודם נשארים תלויים מעל התוכן
  // החדש לכל אורך הטעינה. נופל אם הפליטה של ``null`` תרד מתחילת הבחירה.
  const sb = makeSandbox();
  const done = sb.selectFile('a.py', null);
  await delay(0);

  eq(sb.__events.length, 1, 'אירוע אחד כבר נפלט לפני שהקובץ נטען');
  eq(sb.__events[0].path, null, 'והוא ניקוי');
  // **שם האירוע עצמו.** repo-notes.js מאזין למחרוזת מדויקת; שינוי שם היה
  // מנתק את הרכבת הפתקים בלי שאף טסט אחר בקובץ ירגיש.
  eq(sb.__events[0].type, 'repo:file-loaded', 'שם האירוע');

  sb.__openGate('a.py', { content: 'x', language: 'python' });
  await done;

  eq(sb.__events.length, 2, 'ואחריו ההרכבה');
  eq(sb.__events[1].path, 'a.py', 'של הקובץ שנטען');
});

// -- ה-P1: טעינות חופפות --

check('טעינה שנעקפה אינה מרכיבה פתקים על הקובץ שכן מוצג', async () => {
  // המשתמש לחץ A ואז B. אם A נוחת אחרון, בלי ה-guard הוא היה פולט
  // ``a.py`` — כלומר פתקים של A מעל התוכן של B.
  //
  // נופל אם ``selectFile`` לא בודק ``mySeq === fileSelectionSeq``.
  const sb = makeSandbox();
  const first = sb.selectFile('A.py', null);
  const second = sb.selectFile('B.py', null);

  sb.__openGate('B.py', { content: 'b', language: 'python' });
  await second;
  sb.__openGate('A.py', { content: 'a', language: 'python' });
  await first;
  await delay(0);

  const mounted = sb.__events.filter((e) => e.path !== null).map((e) => e.path);
  eq(mounted.join(','), 'B.py', 'רק הקובץ שנבחר אחרון הורכב');
});

check('כשל של טעינה שנעקפה אינו מפרק את הפתקים של הקובץ שכן מוצג', async () => {
  // הצד השני של אותו מטבע: ניקוי (``null``) מטעינה ישנה שנכשלה היה מוחק
  // את הפתקים של הקובץ שהמשתמש באמת רואה.
  //
  // נופל אם הענף של ה-catch פולט בלי לבדוק את הדור.
  const sb = makeSandbox();
  const first = sb.selectFile('A.py', null);
  const second = sb.selectFile('B.py', null);

  sb.__openGate('B.py', { content: 'b', language: 'python' });
  await second;
  sb.__failGate('A.py', new Error('network'));
  await first;
  await delay(0);

  const last = sb.__events[sb.__events.length - 1];
  eq(last.path, 'B.py', 'האירוע האחרון הוא עדיין ההרכבה של B');
});

// -- צילום הריפו --

check('האירוע נושא את הריפו שהיה בתחילת הטעינה', async () => {
  // החלפת ריפו תוך כדי טעינה משנה את ``#current-repo-name[data-repo]``.
  // קריאה ממנו בסוף הטעינה הייתה מצמידה את הקובץ הישן לריפו החדש — זוג
  // ``(ריפו, נתיב)`` שלא קיים, ולכן פתקים שלא שייכים לשום דבר.
  //
  // נופל אם ``emitRepoFileEvent`` יחזור לקרוא את ה-DOM במקום לקבל צילום.
  const sb = makeSandbox();
  const done = sb.selectFile('a.py', null);
  sb.__repoHolder.dataset.repo = 'OtherRepo';   // המשתמש החליף ריפו תוך כדי
  sb.__openGate('a.py', { content: 'x', language: 'python' });
  await done;

  const mount = sb.__events.filter((e) => e.path !== null).pop();
  eq(mount.repo, 'CodeBot', 'הריפו של תחילת הבחירה');
});

check('מעבר למסך הפתיחה מנקה, וטעינה שהייתה באוויר אינה מחזירה פתקים', async () => {
  // מסך הפתיחה הוא בחירה בפני עצמה. בלי קידום המונה שם, טעינה שנחתה
  // אחריו הייתה מרכיבה פתקים מעל מסך שאין בו קובץ.
  //
  // נופל אם ``showWelcomeScreen`` לא מקדם את ``fileSelectionSeq``.
  const sb = makeSandbox();
  const done = sb.selectFile('a.py', null);
  sb.showWelcomeScreen();
  sb.__openGate('a.py', { content: 'x', language: 'python' });
  await done;
  await delay(0);

  const last = sb.__events[sb.__events.length - 1];
  eq(last.path, null, 'האירוע האחרון הוא ניקוי');
  eq(sb.__events.some((e) => e.path === 'a.py'), false, 'ושום הרכבה לא נפלטה');
});


check('כשל של הטעינה הפעילה מנקה פתקים, ולא משאיר אותם מעל הודעת השגיאה', async () => {
  // הצד שלא נבדק: כשהקובץ ש**כן** נבחר נכשל, יש לפלוט ניקוי. בלי זה
  // הפתקים של הקובץ הקודם נשארים תלויים מעל הודעת השגיאה.
  //
  // נופל אם ה-catch מפסיק לפלוט כשהבחירה עדיין פעילה.
  const sb = makeSandbox();
  const only = sb.selectFile('A.py', null);
  await delay(0);
  sb.__failGate('A.py', new Error('network'));
  await only;
  await delay(0);

  const mounted = sb.__events.filter((e) => e.path !== null);
  eq(mounted.length, 0, 'שום הרכבה לא קרתה');
  const last = sb.__events[sb.__events.length - 1];
  eq(last.path, null, 'האירוע האחרון הוא ניקוי');
  eq(last.type, 'repo:file-loaded', 'ובשם הנכון');
});

// -- ה-P1 השני: בקשה שנעקפה לא מתחייבת על התוכן --

check('טעינה שנעקפה אינה דורסת את תוכן העורך של הקובץ המוצג', async () => {
  // השומר הישן עטף רק את פליטת אירוע הפתקים; ``state.currentFileContent``
  // ו-``initCodeViewer`` רצו בכל מקרה. התוצאה: העורך הציג את התוכן של
  // הקובץ הישן בעוד הכותרת והפתקים היו של החדש.
  //
  // נופל אם ההתחייבות שאחרי ה-fetch אינה מוגנת בדור.
  const sb = makeSandbox();
  const viewed = [];
  sb.initCodeViewer = (content) => { viewed.push(content); };

  const first = sb.selectFile('A.py', null);
  const second = sb.selectFile('B.py', null);

  sb.__openGate('B.py', { content: 'תוכן של B', language: 'python' });
  await second;
  sb.__openGate('A.py', { content: 'תוכן של A', language: 'python' });
  await first;
  await delay(0);

  // ``state`` הוא ``const`` במודול ולכן אינו נחשף על הגלובל של ה-vm;
  // מה שכן נמדד ישירות הוא מה הועבר לעורך — וזה בדיוק ההתחייבות שנבדקת.
  eq(viewed.join('|'), 'תוכן של B', 'רק התוכן של B הוצג בעורך');
});

check('כשל של טעינה שנעקפה אינו מצייר שגיאה על הקובץ המוצג', async () => {
  // אותה מחלקה: ``wrapper.innerHTML`` של הודעת השגיאה רץ בלי תנאי, ולכן
  // כשל ישן היה מוחק תוכן תקין שכבר מוצג.
  //
  // נופל אם ה-catch מצייר בלי לבדוק את הדור.
  const sb = makeSandbox();
  const first = sb.selectFile('A.py', null);
  const second = sb.selectFile('B.py', null);

  sb.__openGate('B.py', { content: 'תוכן של B', language: 'python' });
  await second;
  const wrapper = sb.document.getElementById('code-editor-wrapper');
  const before = wrapper ? wrapper.innerHTML : null;

  sb.__failGate('A.py', new Error('network'));
  await first;
  await delay(0);

  const after = wrapper ? wrapper.innerHTML : null;
  eq(after, before, 'תצוגת הקובץ המוצג לא נגעה');
});

(async () => {
  await Promise.all(pending);
  console.log(`\n${passed} עברו, ${failed} נכשלו`);
  process.exit(failed === 0 ? 0 : 1);
})();
