'use strict';
// בדיקות על שייכות לריפו בדפדפן הקוד: מה מוצג ברשימת "קבצים אחרונים", ומה
// מותר לפתוח בזמן שמעבר בין ריפואים באוויר.
//
// **הבאג שהטסטים האלה שומרים מפניו (אישיו #3276):** הרשימה נשמרה במפתח
// גלובלי אחד ב-``localStorage``, והרשומות בה הן מחרוזות נתיב בלי שום סימן
// לריפו שממנו הגיעו. התוצאה: אותה רשימה הוצגה בכל הריפואים, לחיצה על רשומה
// שלחה את הנתיב מול ``getRepoParam()`` של הריפו הנוכחי — קובץ שגוי או 404 —
// ובמעבר ריפו הפאנל בכלל לא רונדר מחדש, כי ``showWelcomeScreen`` רק מחליפה
// ``display`` ומציגה את התוכן שכבר יושב בו.
//
// הבאג השני, מאותה משפחה: ``switchRepo`` מקדם את ``currentRepo`` סינכרונית
// (וזה מכוון — ראו ``repo-browser-url-state.test.js``), אבל התצוגה מתעדכנת
// רק אחרי ההמתנות שבדרך. בחלון הזה העץ הישן עדיין קליקבילי, ובחירה ממנו
// נשלחת מול הריפו החדש.
//
// ההתקנה: sandbox של vm משלו, לפי המוסכמה בריפו — כל קובץ טסט כאן עצמאי
// ומגדיר את העוזרים ואת הסביבה שהוא צריך. מה שייחודי לקובץ הזה הוא אלמנטים
// עם ``innerHTML`` אמיתי (כדי לקרוא את מה שהפאנל באמת רינדר), ו-``fetch``
// שסופר בנפרד את הבקשות ל-``/file/`` ואת ה-POST ל-``select-repo``.
//
// **כולם הורצו מול הקוד שלפני התיקון**, דרך ``REPO_BROWSER_SRC``, ותשעה מהם
// נפלו שם. השניים שעוברים גם שם מסומנים בגופם ואינם ראיה לכיסוי הבאג: הם
// שומרים מפני רגרסיה שהתיקון עצמו עלול להכניס — מסלול תקין שהשער חוסם,
// ודגל שנשאר דלוק אחרי כשל.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
// ``REPO_BROWSER_SRC`` מאפשר להריץ את אותם טסטים מול עותק של הקובץ מלפני
// התיקון, וזו הדרך שבה אומת שכל אחד מהם באמת נופל שם.
const MODULE_PATH = process.env.REPO_BROWSER_SRC
  || path.join(__dirname, '..', 'webapp', 'static', 'js', 'repo-browser.js');
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

function makeSandbox(opts = {}) {
  // ``innerHTML`` אמיתי-מספיק: הבדיקות קוראות את מה שהפאנל רינדר, ולכן
  // אלמנט שבולע השמות היה מסתיר בדיוק את מה שנבדק.
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
  repoHolder.dataset.source = opts.serverSource || 'user';
  const cache = new Map([['current-repo-name', repoHolder]]);

  const fileFetches = [];   // כל בקשה ל-/file/, לפי הסדר
  const posts = [];         // כל POST ל-select-repo
  const store = new Map();  // localStorage אמיתי-מספיק
  let release = null;       // משחרר POST שמוחזק, כשהבדיקה מבקשת זאת

  const location = {
    href: 'https://x.test/repo/', pathname: '/repo/', search: '', hash: '',
  };

  const sandbox = {
    console: { log: console.log, warn() {}, error() {} },
    __fileFetches: fileFetches,
    __posts: posts,
    __store: store,
    __el: (id) => { if (!cache.has(id)) cache.set(id, el()); return cache.get(id); },
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
      history: { replaceState() {} },
      scrollTo() {},
    },
    localStorage: {
      getItem: (k) => (store.has(k) ? store.get(k) : null),
      setItem: (k, v) => {
        if (opts.storageFull) throw new Error('QuotaExceededError');
        store.set(k, String(v));
      },
      removeItem: (k) => { store.delete(k); },
    },
    navigator: { clipboard: {} },
    history: null,
    fetch(url, init) {
      const u = String(url);
      if (u.includes('select-repo')) {
        posts.push(JSON.parse((init && init.body) || '{}'));
        // ``holdSelectRepo`` משאיר את ה-POST באוויר עד שהבדיקה משחררת אותו.
        // זה החלון שבו נבדק מה מותר לפתוח בזמן שהמעבר עוד לא הסתיים.
        if (opts.holdSelectRepo) {
          return new Promise((resolve) => {
            release = () => resolve({ ok: true, json: async () => ({ success: true }) });
          });
        }
        return Promise.resolve({ ok: true, json: async () => ({ success: true }) });
      }
      if (u.includes('/file/')) {
        fileFetches.push(u);
        return Promise.resolve({ ok: true, json: async () => ({ content: 'x', language: 'text' }) });
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
  sandbox.AbortController = AbortController;
  sandbox.AbortSignal = AbortSignal;
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);

  // נטרול כל מה שאינו התפר הנבדק. ``loadRecentFiles``, ``getRecentFiles``,
  // ``addToRecentFiles`` ו-``selectFile`` נשארים **אמיתיים** — הם ההתנהגות
  // שנבדקת כאן. ``initCodeViewer`` ומשפחתו גוררים את CodeMirror ואת כל צינור
  // התצוגה, ואין להם קשר לשאלה מול איזה ריפו נשלחה הבקשה.
  for (const name of ['initTree', 'loadFileTypes', 'updateRepoDisplay',
                      'saveFilterPreferences', 'clearSearchState',
                      'renderRepoSelector', 'showToast', 'performRepoSearch',
                      'updateFilterBadge', 'initCodeViewer', 'enableMarkdownPreview',
                      'disableMarkdownPreview', 'updateBreadcrumbs', 'updateFileHeader',
                      'updateFileInfo', 'updateMarkdownToggleVisibility',
                      'closeInFileSearch', 'closeMobileSidebar', 'updateUrlHash']) {
    if (typeof sandbox[name] === 'function') sandbox[name] = async () => {};
  }
  // ``let`` בטופ-לבל אינו יושב על אובייקט ה-sandbox, אבל הסביבה הלקסיקלית
  // הגלובלית משותפת לכל הסקריפטים באותו context — ולכן זו הדרך לקרוא ולכתוב
  // אותו.
  sandbox.__read = (expr) => vm.runInContext(expr, sandbox);
  sandbox.__exec = (stmt) => vm.runInContext(stmt, sandbox);
  return sandbox;
}

const panelHtml = (sb) => sb.__el('recent-files-list').innerHTML;

// -- הרשימה: מה שייך לאיזה ריפו --

check('רשומה שנוספה תחת ריפו אחד אינה מופיעה תחת אחר', () => {
  // נופל על הקוד שלפני התיקון: שם המפתח הוא ``'recentFiles'`` גלובלי, ולכן
  // ``getRecentFiles`` מחזיר את אותה רשימה בכל ריפו.
  const sb = makeSandbox();
  sb.__exec("currentRepo = 'CodeBot'");
  sb.addToRecentFiles('bot_handlers.py');

  sb.__exec("currentRepo = 'amir-bug-patterns'");
  eq(sb.getRecentFiles().length, 0, 'הרשימה של הריפו השני ריקה');

  sb.addToRecentFiles('CRITICAL-PATTERNS.md');
  eq(sb.getRecentFiles().join(','), 'CRITICAL-PATTERNS.md', 'ובה רק הרשומה שלה');

  sb.__exec("currentRepo = 'CodeBot'");
  eq(sb.getRecentFiles().join(','), 'bot_handlers.py', 'והרשימה הראשונה לא נגעה');
});

check('המפתח ב-localStorage נושא את שם הריפו', () => {
  // המוסכמה שכבר קיימת בריפו — ``prefKey`` ב-``repo-notes.js``. הבדיקה
  // מצמידה אותה, כדי שמפתח גלובלי לא יחזור בשקט.
  const sb = makeSandbox();
  sb.__exec("currentRepo = 'amir-bug-patterns'");
  sb.addToRecentFiles('INTEGRATION.md');

  eq(sb.__store.get('recentFiles:amir-bug-patterns'), '["INTEGRATION.md"]', 'נכתב למפתח הממופתח');
  eq(sb.__store.get('recentFiles'), undefined, 'ולא למפתח הגלובלי');
});

check('הפאנל מתאר את הריפו החדש כבר לפני שהשמירה בשרת חוזרת', async () => {
  // הלב של הבאג: ``switchRepo`` לא נגע ברשימה, ו-``showWelcomeScreen`` שבסוף
  // רק מחליפה ``display`` — כלומר מציגה מחדש את התוכן של הריפו הקודם.
  // הבדיקה מחזיקה את ה-POST באוויר, ובודקת שהפאנל כבר התחלף.
  const sb = makeSandbox({ holdSelectRepo: true });
  sb.__exec("repoMetadataByName = { 'CodeBot': {}, 'amir-bug-patterns': {} }");
  sb.__exec("currentRepo = 'CodeBot'");
  sb.addToRecentFiles('bot_handlers.py');
  ok(panelHtml(sb).includes('bot_handlers.py'), 'הפאנל מציג את הקובץ של הריפו הראשון');

  const switching = sb.switchRepo('amir-bug-patterns');
  await delay(0);

  eq(sb.__posts.length, 1, 'ה-POST באוויר — זה החלון שנבדק');
  ok(!panelHtml(sb).includes('bot_handlers.py'), 'הקובץ של הריפו הקודם כבר לא בפאנל');
  ok(panelHtml(sb).includes('No recent files'), 'והפאנל מתאר את הריפו החדש (ריק)');

  sb.__releaseSelectRepo();
  await switching;
  ok(panelHtml(sb).includes('No recent files'), 'ונשאר כך אחרי שהמעבר הסתיים');
});

check('המפתח הגלובלי הישן נמחק באתחול', async () => {
  // משתמשים קיימים מחזיקים ``recentFiles`` גלובלי שאין בו סימן לריפו שממנו
  // הגיעו הרשומות — ולכן אין לאן למגר אותן, וכל שיוך יהיה ניחוש.
  const sb = makeSandbox();
  sb.__store.set('recentFiles', '["old/path.py"]');
  sb.__store.set('recentFiles:CodeBot', '["kept.py"]');

  await sb.initRepoBrowser();

  eq(sb.__store.get('recentFiles'), undefined, 'המפתח הישן נמחק');
  eq(sb.__store.get('recentFiles:CodeBot'), '["kept.py"]', 'והמפתחות הממופתחים שרדו');
});

// -- הרשימה: ערך שהגיע מחוץ לתהליך --

check('ערך שאינו מערך ב-localStorage אינו מפיל את הפאנל', () => {
  // ``localStorage`` פתוח לעריכה ידנית ונושא גם מה שגרסה קודמת כתבה.
  // ``JSON.parse`` מצליח יפה על ``{}`` ועל ``5``, ואז ``.filter``/``.map``
  // זורקים — ו-``addToRecentFiles`` רצה בתוך ה-``try`` של ``selectFile``,
  // כך שקובץ שנטען בהצלחה היה מוצג כ-"Failed to load file".
  for (const bad of ['{"a":1}', '5', '"x"', 'null']) {
    const sb = makeSandbox();
    sb.__exec("currentRepo = 'CodeBot'");
    sb.__store.set('recentFiles:CodeBot', bad);
    // **גם המפתח הגלובלי, ובכוונה.** בלעדיו הטסט הזה "עובר" על הקוד שלפני
    // התיקון — לא כי הוא עמיד, אלא כי שם קוראים מפתח אחר, והוא ריק. הרצה
    // מול הקוד הישן היא מה שחשף את זה.
    sb.__store.set('recentFiles', bad);

    eq(sb.getRecentFiles().length, 0, `${bad} מתורגם לרשימה ריקה`);
    sb.loadRecentFiles();
    ok(panelHtml(sb).includes('No recent files'), `${bad} לא מפיל את הרינדור`);
    sb.addToRecentFiles('a.py');
    eq(sb.getRecentFiles().join(','), 'a.py', `${bad} לא מונע הוספה`);
  }
});

check('איבר שאינו מחרוזת מסונן מהרשימה', () => {
  // אותו קלט חיצוני, רק ברמת האיבר: ``path.split('/')`` על מספר זורק.
  const sb = makeSandbox();
  sb.__exec("currentRepo = 'CodeBot'");
  sb.__store.set('recentFiles:CodeBot', '["ok.py", 7, null, {"p":"x"}, "", "also.md"]');

  eq(sb.getRecentFiles().join(','), 'ok.py,also.md', 'רק המחרוזות שרדו');
  sb.loadRecentFiles();
  ok(panelHtml(sb).includes('ok.py'), 'והפאנל רינדר אותן');
});

check('מכסת אחסון מלאה אינה מפילה את פתיחת הקובץ', async () => {
  // המיפתוח מכפיל את צריכת האחסון במספר הריפואים, ולכן ``setItem`` שזורק
  // נעשה סביר יותר. בלי העטיפה החריגה מתפשטת ל-``catch`` של ``selectFile``
  // ומציגה שגיאת טעינה על קובץ שנטען בהצלחה.
  const sb = makeSandbox({ storageFull: true });
  sb.__exec("currentRepo = 'CodeBot'");

  await sb.selectFile('bot_handlers.py');

  eq(sb.__fileFetches.length, 1, 'הקובץ נטען');
  ok(!sb.__el('code-editor-wrapper').innerHTML.includes('Failed to load file'),
     'ולא הוצגה שגיאת טעינה');
});

// -- השער: מה מותר לפתוח בזמן מעבר --

check('בזמן שהמעבר באוויר, selectFile אינו יוצר בקשה ל-/file/', async () => {
  // נופל על הקוד שלפני התיקון: ``currentRepo`` כבר מצביע לריפו החדש, ולכן
  // הנתיב הישן נשלח מול ``getRepoParam()`` של החדש.
  const sb = makeSandbox({ holdSelectRepo: true });
  sb.__exec("repoMetadataByName = { 'CodeBot': {}, 'amir-bug-patterns': {} }");
  sb.__exec("currentRepo = 'CodeBot'");

  const switching = sb.switchRepo('amir-bug-patterns');
  await delay(0);
  eq(sb.__posts.length, 1, 'ה-POST באוויר — זה החלון שנבדק');

  await sb.selectFile('bot_handlers.py');
  eq(sb.__fileFetches.length, 0, 'לא יצאה בקשה לקובץ');

  sb.__releaseSelectRepo();
  await switching;
});

check('בחירה שנחסמה אינה מבטלת בחירה שעדיין באוויר', async () => {
  // ``fileSelectionSeq`` הוא מה שמחליט איזו טעינה רשאית להתחייב. קידום שלו
  // במסלול החסום היה מבטל בחירה לגיטימית בלי להעמיד דבר במקומה.
  const sb = makeSandbox({ holdSelectRepo: true });
  sb.__exec("repoMetadataByName = { 'CodeBot': {}, 'amir-bug-patterns': {} }");
  sb.__exec("currentRepo = 'CodeBot'");

  const switching = sb.switchRepo('amir-bug-patterns');
  await delay(0);
  const before = sb.__read('fileSelectionSeq');

  await sb.selectFile('bot_handlers.py');
  eq(sb.__read('fileSelectionSeq'), before, 'המונה לא זז');

  sb.__releaseSelectRepo();
  await switching;
});

check('אחרי שהמעבר הסתיים, selectFile עובד כרגיל', async () => {
  // **טסט רגרסיה — עובר גם על הקוד שלפני התיקון, ובכוונה.** מה שהוא שומר
  // עליו הוא שהשער נפתח: שער שנשאר סגור היה חוסם את המסלול התקין בשקט.
  const sb = makeSandbox({ holdSelectRepo: true });
  sb.__exec("repoMetadataByName = { 'CodeBot': {}, 'amir-bug-patterns': {} }");
  sb.__exec("currentRepo = 'CodeBot'");

  const switching = sb.switchRepo('amir-bug-patterns');
  await delay(0);
  sb.__releaseSelectRepo();
  await switching;

  await sb.selectFile('CRITICAL-PATTERNS.md');
  eq(sb.__fileFetches.length, 1, 'יצאה בקשה אחת');
  ok(sb.__fileFetches[0].includes('repo=amir-bug-patterns'), 'מול הריפו החדש');
  eq(sb.getRecentFiles().join(','), 'CRITICAL-PATTERNS.md', 'והרשומה נשמרה תחת הריפו החדש');
});

check('כשל באמצע המעבר עדיין משחרר את השער', async () => {
  // **טסט רגרסיה — עובר גם על הקוד שלפני התיקון, ובכוונה.** שם אין דגל
  // בכלל, ולכן אין מה להיתקע; הוא שומר מפני באג שהתיקון עלול להכניס.
  // הדגל מכובה ב-``finally`` ולא בנתיב ההצלחה: כשל חולף אחד שמשאיר אותו
  // דלוק נועל את הדפדפן על פתיחת קבצים עד ריענון.
  const sb = makeSandbox();
  sb.__exec("repoMetadataByName = { 'CodeBot': {}, 'amir-bug-patterns': {} }");
  sb.__exec("currentRepo = 'CodeBot'");
  sb.__exec("initTree = async () => { throw new Error('boom'); }");

  let threw = false;
  try { await sb.switchRepo('amir-bug-patterns'); } catch { threw = true; }
  ok(threw, 'המעבר אכן נכשל');

  await sb.selectFile('CRITICAL-PATTERNS.md');
  eq(sb.__fileFetches.length, 1, 'ואחריו אפשר לפתוח קובץ');
});

await Promise.all(pending);
console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
