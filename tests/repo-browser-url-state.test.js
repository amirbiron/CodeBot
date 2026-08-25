'use strict';
// בדיקות על מצב ה-URL של דפדפן הריפו: מי הבעלים של "איזה ריפו מוצג".
//
// **הבאג שהטסטים האלה שומרים מפניו:** ``?repo=`` ו-``?note=`` הם כוונת
// ניווט חד-פעמית — "פתח את הריפו הזה על הפתק הזה" — שנוצרת רק בקישור
// תזכורת (``webapp/boards_ui.py``). אבל ``get_current_repo_name`` בצד
// השרת נותנת ל-query עדיפות **מעל ה-session**, ואף מסלול ניווט בצד
// הלקוח לא מסיר אותו: ``updateUrlHash`` — הפונקציה היחידה שכותבת URL
// בניווט — משמרת את ``location.search`` בשתי דרכי הכתיבה שלה.
//
// התוצאה: אחרי מעבר לריפו אחר, ה-URL עדיין נושא את הריפו הראשון,
// והריענון מחזיר אליו. גרוע מזה — הריענון גם שולח POST ל-``select-repo``
// ובכך **דורס את בחירת הריפו השמורה של המשתמש**.
//
// ההתקנה: sandbox של vm משלו, לפי המוסכמה בריפו — כל קובץ טסט כאן עצמאי
// ומגדיר את העוזרים ואת הסביבה שהוא צריך. מה שייחודי לקובץ הזה הוא
// ``location`` ו-``history.replaceState`` שמתנהגים כמו בדפדפן: כלומר
// ``replaceState`` באמת מעדכן את ה-URL ופותר כתובות יחסיות מולו. בלי זה
// הטסט לא יכול לראות את הניקוי בכלל.

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
function ok(cond, what) {
  if (!cond) throw new Error(what || 'ציפיתי לאמת');
}
const delay = (ms) => new Promise((r) => setTimeout(r, ms));

// ``location`` אמיתי-מספיק: ``replaceState`` בדפדפן מקבל גם כתובת יחסית
// (``'#file=x'``) וגם מלאה, ופותר אותה מול ה-URL הנוכחי. סימולציה שלא
// עושה את זה הייתה מחמיצה בדיוק את המקרה שנבדק כאן.
function makeLocation(initialHref) {
  const loc = {};
  loc.__apply = (href) => {
    const u = new URL(href, loc.href || initialHref);
    loc.href = u.href;
    loc.pathname = u.pathname;
    loc.search = u.search;
    loc.hash = u.hash;
  };
  loc.__apply(initialHref);
  return loc;
}

function makeSandbox(href, opts = {}) {
  const el = () => ({
    style: {}, dataset: {}, innerHTML: '', textContent: '', value: '',
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    appendChild() {}, addEventListener() {}, removeEventListener() {},
    querySelector: () => null, querySelectorAll: () => [],
    setAttribute() {}, getAttribute: () => null, remove() {}, click() {}, focus() {}, blur() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }),
  });
  const repoHolder = el();
  repoHolder.dataset.repo = opts.serverRepo || 'CodeBot';
  repoHolder.dataset.source = opts.serverSource || 'query';
  const cache = new Map([['current-repo-name', repoHolder]]);

  const location = makeLocation(href);
  const posts = [];          // כל POST ל-select-repo, לפי הסדר
  const store = new Map();   // localStorage אמיתי-מספיק
  let release = null;        // משחרר POST שמוחזק, כשהבדיקה מבקשת זאת

  const sandbox = {
    console: { log: console.log, warn() {}, error() {} },
    __posts: posts,
    __store: store,
    __location: location,
    __releaseSelectRepo() { if (release) release(); },
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
      dispatchEvent() { return true; },
    },
    window: {
      addEventListener() {}, removeEventListener() {},
      innerWidth: 1024, innerHeight: 768,
      location,
      matchMedia: () => ({ matches: false }),
      // הסימולציה של הדפדפן: ``replaceState`` באמת מזיז את ה-URL.
      history: { replaceState(state, title, url) { location.__apply(String(url)); } },
      scrollTo() {},
    },
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => { store.set(k, String(v)); },
      removeItem: (k) => { store.delete(k); },
    },
    navigator: { clipboard: {} },
    // ``history`` הוא גלובל אמיתי בדפדפן, לא רק ``window.history`` —
    // והקוד קורא לו כך. סנדבוקס שמגדיר רק את השני היה בולע את הניקוי
    // בשקט (החריגה נתפסת ומדווחת ל-console בלבד).
    history: null,
    fetch(url, init) {
      const u = String(url);
      if (u.includes('select-repo')) {
        posts.push(JSON.parse((init && init.body) || '{}'));
        // ``holdSelectRepo`` משאיר את ה-POST באוויר עד שהבדיקה משחררת אותו.
        // זה החלון שבו נבדק מה ``currentRepo`` מחזיק בזמן שהשמירה מתעכבת.
        if (opts.holdSelectRepo) {
          return new Promise((resolve) => { release = () => resolve({ ok: true, json: async () => ({ success: true }) }); });
        }
        return Promise.resolve({ ok: true, json: async () => ({ success: true }) });
      }
      return Promise.resolve({ ok: true, json: async () => ({ success: true, repos: [] }) });
    },
    setTimeout, clearTimeout, setInterval, clearInterval,
    requestAnimationFrame: (f) => setTimeout(f, 0),
  };
  sandbox.history = sandbox.window.history;
  sandbox.location = location;
  sandbox.CustomEvent = function (type, init) { return { type, detail: (init || {}).detail }; };
  sandbox.URL = URL;
  sandbox.URLSearchParams = URLSearchParams;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);

  // נטרול כל מה שאינו התפר הנבדק. ``updateUrlHash`` נשאר **אמיתי** — הוא
  // חלק מההתנהגות שנבדקת, לא רעש רקע.
  for (const name of ['initTree', 'loadFileTypes', 'showWelcomeScreen', 'updateRepoDisplay',
                      'saveFilterPreferences', 'clearSearchState',
                      'renderRepoSelector', 'showToast', 'performRepoSearch',
                      'loadRecentFiles', 'updateFilterBadge']) {
    if (typeof sandbox[name] === 'function') sandbox[name] = async () => {};
  }
  // ``selectFile`` האמיתי גורר את CodeMirror ואת כל צינור התצוגה, אבל
  // החלק שנוגע ל-URL הוא שורה אחת בלבד (``updateUrlHash(path)``, שורה
  // 1622). התחליף מחזיק בדיוק אותה: ``switchRepo`` מנקה את ה-hash בדרך,
  // וה-hash נבנה מחדש כאן — בלי זה הטסט היה בודק סדר פעולות שאינו קיים.
  sandbox.selectFile = async (p) => { sandbox.updateUrlHash(p); };
  // ``let`` בטופ-לבל אינו יושב על אובייקט ה-sandbox, אבל הסביבה הלקסיקלית
  // הגלובלית משותפת לכל הסקריפטים באותו context — ולכן זו הדרך לקרוא
  // ולכתוב אותו.
  sandbox.__read = (expr) => vm.runInContext(expr, sandbox);
  sandbox.__exec = (stmt) => vm.runInContext(stmt, sandbox);
  return sandbox;
}

const q = (loc) => new URLSearchParams(loc.search);

// -- הבאג עצמו --

check('הריפו מה-query מוסר מה-URL אחרי שנצרך', async () => {
  // נופל על הקוד שלפני התיקון: ``applyInitialNavigationFromUrl`` צורכת את
  // ``?repo=`` אבל אף אחד לא מסיר אותו, ולכן הוא שורד לריענון הבא.
  const sb = makeSandbox('https://x.test/repo/?repo=amir-bug-patterns&note=abc123#file=INTEGRATION.md',
                         { serverRepo: 'CodeBot', serverSource: 'user' });
  sb.__exec("repoMetadataByName = { 'amir-bug-patterns': { repo_name: 'amir-bug-patterns' }, 'CodeBot': { repo_name: 'CodeBot' } }");
  sb.__exec("currentRepo = 'CodeBot'");

  await sb.applyInitialNavigationFromUrl();

  eq(q(sb.__location).get('repo'), null, 'repo הוסר מה-query');
  eq(q(sb.__location).get('note'), null, 'note הוסר מה-query');
});

check('ה-hash שורד את הניקוי במלואו', async () => {
  // הניקוי חייב לגעת ב-query בלבד. ה-hash הוא מצב לגיטימי ומתמשך —
  // הוא זה שאומר איזה קובץ פתוח, ומחיקתו הייתה מאבדת את הקובץ.
  const sb = makeSandbox('https://x.test/repo/?repo=amir-bug-patterns&note=abc123#file=INTEGRATION.md',
                         { serverRepo: 'CodeBot', serverSource: 'user' });
  sb.__exec("repoMetadataByName = { 'amir-bug-patterns': { repo_name: 'amir-bug-patterns' }, 'CodeBot': { repo_name: 'CodeBot' } }");
  sb.__exec("currentRepo = 'CodeBot'");

  await sb.applyInitialNavigationFromUrl();

  eq(sb.__location.hash, '#file=INTEGRATION.md', 'ה-hash לא נגע');
});

check('הריפו מהקישור נשמר גם כששרת הרינדור כבר קבע אותו', async () => {
  // המסלול שבו ``switchRepo`` יוצא מוקדם: השרת כבר רינדר את הריפו מה-query,
  // ולכן ``targetRepo === currentRepo`` והשמירה לא קורית מתופעת לוואי.
  // בלי שמירה מפורשת, הניקוי היה מוחק את הכוונה בלי שאיש יקלוט אותה —
  // ובריענון הבא המשתמש היה נוחת על ריפו ברירת המחדל.
  const sb = makeSandbox('https://x.test/repo/?repo=amir-bug-patterns&note=abc123#file=INTEGRATION.md',
                         { serverRepo: 'amir-bug-patterns', serverSource: 'query' });
  sb.__exec("repoMetadataByName = { 'amir-bug-patterns': { repo_name: 'amir-bug-patterns' } }");
  sb.__exec("currentRepo = 'amir-bug-patterns'");

  await sb.applyInitialNavigationFromUrl();

  eq(sb.__store.get('selectedRepo'), 'amir-bug-patterns', 'נשמר ב-localStorage');
  eq(sb.__posts.length, 1, 'ונשלח POST אחד ל-select-repo');
  eq(sb.__posts[0].repo_name, 'amir-bug-patterns', 'עם הריפו הנכון');
});

check('URL רגיל בלי הפרמטרים אינו משתנה', async () => {
  // הניקוי לא אמור לגעת בכלום כשאין מה לנקות — ובפרט לא לדרוס את ה-hash
  // או לשלוח POST מיותר בכל טעינת עמוד.
  const sb = makeSandbox('https://x.test/repo/#file=MIGRATION-NOTES.md',
                         { serverRepo: 'CodeBot', serverSource: 'user' });
  sb.__exec("repoMetadataByName = { 'CodeBot': { repo_name: 'CodeBot' } }");
  sb.__exec("currentRepo = 'CodeBot'");

  await sb.applyInitialNavigationFromUrl();

  eq(sb.__location.search, '', 'ה-query נשאר ריק');
  eq(sb.__location.hash, '#file=MIGRATION-NOTES.md', 'וה-hash שלם');
  eq(sb.__posts.length, 0, 'ולא נשלח POST');
});

check('ריפו שאינו ברשימת הריפואים אינו נשמר', async () => {
  // ``?repo=`` הוא קלט חיצוני. הקוד כבר מסרב להחליף לריפו שאינו מוכר,
  // והשמירה חייבת לכבד את אותה בדיקה — אחרת הניקוי היה מנציח שם פסול
  // ב-localStorage ובמסד.
  const sb = makeSandbox('https://x.test/repo/?repo=does-not-exist#file=a.md',
                         { serverRepo: 'CodeBot', serverSource: 'user' });
  sb.__exec("repoMetadataByName = { 'CodeBot': { repo_name: 'CodeBot' } }");
  sb.__exec("currentRepo = 'CodeBot'");

  await sb.applyInitialNavigationFromUrl();

  eq(sb.__store.get('selectedRepo'), undefined, 'לא נשמר ריפו לא מוכר');
  eq(sb.__posts.length, 0, 'ולא נשלח POST');
});

// -- תזמון: המצב המקומי לא ממתין לרשת --

check('currentRepo מתעדכן מיד, לפני שהשמירה בשרת חוזרת', async () => {
  // ``switchRepo`` שומר בשרת, וזו קריאת רשת. אם ``currentRepo`` מתעדכן רק
  // **אחרי** ההמתנה, כל מי שקורא אותו בחלון הזה מקבל את הריפו הישן:
  // ``getRepoParam`` בונה ממנו כל קריאת API, והשער של ``switchRepo`` עצמו
  // משווה מולו — כלומר קריאה שנייה בחלון הזה לא תיחסם ותיצור החלפה כפולה.
  //
  // נופל אם ``currentRepo = repoName`` יושב אחרי ``await persistSelectedRepo``.
  const sb = makeSandbox('https://x.test/repo/', { serverRepo: 'CodeBot', serverSource: 'user', holdSelectRepo: true });
  sb.__exec("repoMetadataByName = { 'CodeBot': { repo_name: 'CodeBot' }, 'other': { repo_name: 'other' } }");
  sb.__exec("currentRepo = 'CodeBot'");

  const switching = sb.switchRepo('other');
  await delay(0);

  // ה-POST באוויר ועדיין לא נענה — בדיוק החלון שנבדק.
  eq(sb.__posts.length, 1, 'ה-POST יצא');
  eq(sb.__read('currentRepo'), 'other', 'currentRepo כבר מצביע לריפו החדש');
  eq(sb.__store.get('selectedRepo'), 'other', 'וגם localStorage כבר עודכן');

  sb.__releaseSelectRepo();
  await switching;
  eq(sb.__read('currentRepo'), 'other', 'ונשאר כך אחרי שהשמירה חזרה');
});

await Promise.all(pending);
console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
