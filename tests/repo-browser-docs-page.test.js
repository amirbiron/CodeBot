'use strict';
// בדיקות לתצוגה המרונדרת של עמוד rst בדפדפן הריפו (``webapp/static/js/repo-browser.js``):
// מתי היא מוצעת, מאיפה המארקדאון שלה, ומה ההודעה שמעליה.
//
// **מה נבדק כאן ולא בשרת.** ``tests/test_repo_browser_docs_page.py`` בודק מה השרת מחזיר
// (``has_docs_page`` ו-``freshness``). כאן נבדק שהדפדפן עושה עם זה את הדבר הנכון: מציע את
// התצוגה רק כשהשרת אומר שיש עמוד, מרנדר את העמוד ולא את מקור ה-rst, שולח את הגרסה שמוצגת
// מההיסטוריה, ולא נותן לטעינה ישנה לדרוס את ההודעה של טעינה חדשה.
//
// ההתקנה כמו ב-``repo-browser-notes.test.js``: sandbox של vm עם DOM מינימלי, והקובץ נטען כמו
// שהוא. הרינדור עצמו (``renderMarkdownPreview``) מוחלף בהקלטה של מה שנשלח אליו.

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
async function waitFor(condition, what) {
  for (let i = 0; i < 50; i += 1) {
    if (condition()) return;
    await delay(0);
  }
  throw new Error(`לא קרה: ${what}`);
}

/**
 * ``responses`` — נתיב (בלי ה-query) ← מה ש-``fetch`` מחזיר: אובייקט (תשובת JSON תקינה) או
 * ``{gate: true}`` (הבדיקה פותחת את התשובה בעצמה, ב-``__open``).
 */
function makeSandbox(responses = {}, storage = {}) {
  const el = () => {
    const node = {
      style: {}, dataset: {}, innerHTML: '', hidden: false, title: '', dir: '', children: [], _text: '',
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      appendChild() {}, addEventListener() {}, removeEventListener() {},
      querySelector: () => null, querySelectorAll: () => [],
      setAttribute() {}, getAttribute: () => null, remove() {}, click() {}, focus() {}, blur() {},
      getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }),
      // כמו ב-DOM: ``append`` מוסיף טקסט או אלמנט, ו-``textContent`` מחליף את כל מה שבפנים.
      append(...nodes) {
        for (const item of nodes) {
          if (typeof item === 'string') this._text += item;
          else { this.children.push(item); this._text += item.textContent; }
        }
      },
    };
    Object.defineProperty(node, 'textContent', {
      get() { return this._text; },
      set(value) { this._text = String(value); this.children = []; },
    });
    return node;
  };
  const repoHolder = el();
  repoHolder.dataset.repo = 'CodeBot';
  const cache = new Map([['current-repo-name', repoHolder]]);
  const requests = [];
  const gates = [];

  const sandbox = {
    console: { log: console.log, warn() {}, error() {} },
    __requests: requests,
    __gates: gates,
    __open(index, body) { gates[index](body); },
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
      location: { hash: '', search: '', href: '' },
      matchMedia: () => ({ matches: false }),
      history: { replaceState() {} },
    },
    localStorage: { getItem: (key) => (key in storage ? storage[key] : null), setItem() {}, removeItem() {} },
    navigator: { clipboard: {} },
    fetch(url) {
      requests.push(String(url));
      const key = String(url).replace(/\?.*$/, '');
      const answer = responses[key];
      const respond = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });
      if (answer && answer.gate) {
        return new Promise((resolve) => { gates.push((body) => resolve(respond(body))); });
      }
      if (answer === undefined) return Promise.resolve(respond({ error: 'no_docs_page' }, 404));
      return Promise.resolve(respond(answer));
    },
    URLSearchParams,
    AbortSignal,
    AbortController,
    setTimeout, clearTimeout, setInterval, clearInterval,
    requestAnimationFrame: (f) => setTimeout(f, 0),
  };
  sandbox.CustomEvent = function (type, init) { return { type, detail: (init || {}).detail }; };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);

  sandbox.__rendered = [];
  sandbox.renderMarkdownPreview = async (content) => { sandbox.__rendered.push(content); };
  sandbox.__codeViews = [];
  sandbox.initCodeViewer = async (content) => { sandbox.__codeViews.push(content); };
  for (const name of ['updateBreadcrumbs', 'updateFileHeader', 'updateFileInfo', 'addToRecentFiles',
                      'updateUrlHash', 'closeInFileSearch', 'closeMobileSidebar', 'emitRepoViewChanged']) {
    sandbox[name] = () => {};
  }
  return sandbox;
}

const RST = 'docs/webapp/code-browser.rst';
const FILE_URL = `/repo/api/file/${encodeURIComponent(RST)}`;
const PAGE_URL = `/repo/api/docs-page/${encodeURIComponent(RST)}`;
const PAGE = { path: RST, markdown: '# דפדפן קוד\n', page_path: 'webapp/code-browser.html', freshness: 'current' };
const PREFERS_PREVIEW = { 'repo-browser-markdown-preview': 'true' };

// -- מתי התצוגה מוצעת --

check('קובץ rst שיש לו עמוד נפתח בתצוגה המרונדרת, מהעמוד ולא מהמקור', async () => {
  // נופל אם ההחלטה של ``selectFile`` תחזור להיות לפי הסיומת בלבד: אז קובץ rst נפתח כקוד.
  const sb = makeSandbox({
    [FILE_URL]: { content: 'דפדפן קוד\n=========\n', language: 'text', has_docs_page: true },
    [PAGE_URL]: PAGE,
  }, PREFERS_PREVIEW);

  await sb.selectFile(RST, null);

  eq(sb.__rendered.length, 1, 'רינדור אחד');
  eq(sb.__rendered[0], PAGE.markdown, 'של העמוד מאתר התיעוד');
  eq(sb.document.getElementById('markdown-preview-toggle').style.display, 'flex', 'הכפתור מוצג');
  eq(sb.document.getElementById('markdown-preview-note').hidden, true, 'עמוד עדכני — בלי הודעה');
});

check('קובץ rst בלי עמוד נשאר קוד, גם כשהמשתמש מעדיף תצוגה מרונדרת', async () => {
  const sb = makeSandbox({
    [FILE_URL]: { content: 'api\n===\n', language: 'text', has_docs_page: false },
  }, PREFERS_PREVIEW);

  await sb.selectFile(RST, null);

  eq(sb.__rendered.length, 0, 'אין רינדור');
  eq(sb.__codeViews.length, 1, 'הקובץ מוצג כקוד');
  eq(sb.document.getElementById('markdown-preview-toggle').style.display, 'none', 'ואין כפתור');
  eq(sb.__requests.some((url) => url.includes('/docs-page/')), false, 'ואין בקשה לעמוד');
});

check('קובץ md מרונדר מהתוכן שלו, בלי בקשה לאתר התיעוד ובלי הודעה', async () => {
  const sb = makeSandbox({
    [`/repo/api/file/${encodeURIComponent('README.md')}`]: { content: '# קרא אותי\n', language: 'markdown' },
  }, PREFERS_PREVIEW);

  await sb.selectFile('README.md', null);

  eq(sb.__rendered[0], '# קרא אותי\n', 'התוכן של הקובץ');
  eq(sb.__requests.some((url) => url.includes('/docs-page/')), false, 'אין בקשה לעמוד');
  eq(sb.document.getElementById('markdown-preview-note').hidden, true, 'אין הודעה');
});

// -- ההודעה --

check('עמוד שהקובץ השתנה מאז הבנייה שלו מוצג עם ההודעה', async () => {
  const sb = makeSandbox({
    [FILE_URL]: { content: 'חדש\n', language: 'text', has_docs_page: true },
    [PAGE_URL]: { ...PAGE, freshness: 'changed' },
  }, PREFERS_PREVIEW);

  await sb.selectFile(RST, null);

  const note = sb.document.getElementById('markdown-preview-note');
  eq(note.hidden, false, 'ההודעה מוצגת');
  eq(note.textContent, 'התצוגה מהבנייה האחרונה של אתר התיעוד; הקובץ השתנה מאז', 'בנוסח שלה');
});

check('ערך שהדפדפן לא מכיר מוצג כ"אי אפשר לבדוק", ולא כעמוד עדכני', async () => {
  // נופל אם ההודעה תיגזר מ-``DOCS_PAGE_NOTES[freshness]`` לבד: ערך לא מוכר היה מסתיר אותה.
  const sb = makeSandbox({
    [FILE_URL]: { content: 'x\n', language: 'text', has_docs_page: true },
    [PAGE_URL]: { ...PAGE, freshness: 'stale-ish' },
  }, PREFERS_PREVIEW);

  await sb.selectFile(RST, null);

  const note = sb.document.getElementById('markdown-preview-note');
  eq(note.hidden, false, 'ההודעה מוצגת');
  eq(note.textContent, 'התצוגה מהבנייה האחרונה של אתר התיעוד; כרגע אי אפשר לבדוק אם הקובץ השתנה מאז', 'בנוסח של "אי אפשר לבדוק"');
});

check('כשקוד שהעמוד מציג מקובץ אחר השתנה, ההודעה נוקבת בקבצים, כל אחד משמאל לימין', async () => {
  // נופל אם ההודעה תתעלם מ-``changed_dependencies``, או תכתוב את הנתיבים כטקסט רגיל בתוך השורה העברית.
  const sb = makeSandbox({
    [FILE_URL]: { content: 'x\n', language: 'text', has_docs_page: true },
    [PAGE_URL]: { ...PAGE, freshness: 'dependency_changed', changed_dependencies: ['handlers/save_flow.py', 'main.py'] },
  }, PREFERS_PREVIEW);

  await sb.selectFile(RST, null);

  const note = sb.document.getElementById('markdown-preview-note');
  eq(note.hidden, false, 'ההודעה מוצגת');
  eq(note.textContent,
    'התצוגה מהבנייה האחרונה של אתר התיעוד; קובץ שהעמוד נבנה ממנו השתנה מאז: handlers/save_flow.py, main.py',
    'בנוסח שלה, עם הקבצים');
  eq(note.children.map((code) => `${code.dir}:${code.textContent}`).join(' '),
    'ltr:handlers/save_flow.py ltr:main.py', 'כל קובץ באלמנט משלו, משמאל לימין');
});

check('"קובץ אחר השתנה" בלי רשימת קבצים מוצג כ"אי אפשר לבדוק"', async () => {
  const sb = makeSandbox({
    [FILE_URL]: { content: 'x\n', language: 'text', has_docs_page: true },
    [PAGE_URL]: { ...PAGE, freshness: 'dependency_changed' },
  }, PREFERS_PREVIEW);

  await sb.selectFile(RST, null);

  eq(sb.document.getElementById('markdown-preview-note').textContent,
    'התצוגה מהבנייה האחרונה של אתר התיעוד; כרגע אי אפשר לבדוק אם הקובץ השתנה מאז', 'בנוסח של "אי אפשר לבדוק"');
});

check('עמוד שלא נטען מוצג כהודעת שגיאה, והטקסט שלה מוצג כטקסט', async () => {
  const sb = makeSandbox({
    [FILE_URL]: { content: 'x\n', language: 'text', has_docs_page: true },
    [PAGE_URL]: { gate: true },
  }, PREFERS_PREVIEW);
  const opening = sb.selectFile(RST, null);
  await waitFor(() => sb.__gates.length === 1, 'הבקשה לעמוד');
  sb.__open(0, { error: '<b>docs_page_unavailable</b>' });
  await opening;

  const shown = sb.document.getElementById('markdown-preview-content').innerHTML;
  eq(shown.includes('class="error-message"'), true, 'הודעת שגיאה');
  eq(shown.includes('העמוד מאתר התיעוד לא נטען: &lt;b&gt;docs_page_unavailable&lt;/b&gt;'), true, 'עם הסיבה, כטקסט');
  eq(sb.__rendered.length, 0, 'ובלי רינדור');
});

// -- טעינה שנחתה אחרי שעברו לקובץ אחר --

const README_URL = `/repo/api/file/${encodeURIComponent('README.md')}`;

check('עמוד שנטען מהמתג, ונחת אחרי שנבחר קובץ אחר, לא נכתב מעליו', async () => {
  // נופל בלי הקיבוע של ``seq`` בתחילת ``renderPreview``: המתג קורא לו בלי ``seq``,
  // ו-``selectionIsCurrent(undefined)`` מאשר תמיד.
  const sb = makeSandbox({
    [FILE_URL]: { content: 'דפדפן קוד\n', language: 'text', has_docs_page: true },
    [PAGE_URL]: { gate: true },
    [README_URL]: { content: '# קרא אותי\n', language: 'markdown' },
  });
  // כמו בתבנית (``repo/index.html``): ההודעה מתחילה מוסתרת, ובתצוגת קוד אף אחד לא נוגע בה.
  sb.document.getElementById('markdown-preview-note').hidden = true;
  await sb.selectFile(RST, null);
  const toggling = sb.toggleMarkdownPreview();
  await waitFor(() => sb.__gates.length === 1, 'הבקשה לעמוד מהמתג');

  await sb.selectFile('README.md', null);
  sb.__open(0, { ...PAGE, freshness: 'changed' });
  await toggling;

  eq(sb.__rendered.includes(PAGE.markdown), false, 'העמוד של ה-rst לא רונדר');
  const note = sb.document.getElementById('markdown-preview-note');
  eq(`${note.hidden}|${note.textContent}`, 'true|', 'וגם ההודעה שלו לא נכתבה');
});

check('עמוד של גרסה מההיסטוריה, שנחת אחרי שנבחר קובץ md, לא נכתב מעליו', async () => {
  // התרחיש מהסקירה: עמוד מההיסטוריה שנחת אחרי שנבחר קובץ md. שני שומרים חוסמים אותו — הקיבוע
  // לבחירה, ו-``previewRenderSeq``, שהרינדור של ה-md קידם.
  const sb = makeSandbox({
    [FILE_URL]: { content: 'דפדפן קוד\n', language: 'text', has_docs_page: true },
    [PAGE_URL]: { gate: true },
    [README_URL]: { content: '# קרא אותי\n', language: 'markdown' },
  }, PREFERS_PREVIEW);
  const opening = sb.selectFile(RST, null);
  await waitFor(() => sb.__gates.length === 1, 'הבקשה לעמוד בפתיחה');
  sb.__open(0, PAGE);
  await opening;
  const fromHistory = sb.window.RepoState.setFileContent('ישן\n', { ref: 'b'.repeat(40) });
  await waitFor(() => sb.__gates.length === 2, 'הבקשה של ההיסטוריה');

  await sb.selectFile('README.md', null);
  sb.__open(1, { ...PAGE, markdown: '# ישן\n', freshness: 'changed' });
  await fromHistory;

  eq(sb.__rendered[sb.__rendered.length - 1], '# קרא אותי\n', 'התצוגה היא של ה-README');
  eq(sb.document.getElementById('markdown-preview-note').hidden, true, 'בלי ההודעה של העמוד');
});

// -- היסטוריה --

check('גרסה מההיסטוריה נשלחת לשרת, כדי שהעמוד יושווה אליה', async () => {
  const sha = 'a'.repeat(40);
  const sb = makeSandbox({
    [FILE_URL]: { content: 'נוכחי\n', language: 'text', has_docs_page: true },
    [PAGE_URL]: PAGE,
  }, PREFERS_PREVIEW);
  await sb.selectFile(RST, null);

  await sb.window.RepoState.setFileContent('ישן\n', { ref: sha });

  const last = sb.__requests[sb.__requests.length - 1];
  eq(last.startsWith(PAGE_URL), true, 'בקשה לעמוד');
  eq(new URLSearchParams(last.split('?')[1]).get('ref'), sha, 'עם הגרסה שמוצגת');
  eq(sb.__rendered[sb.__rendered.length - 1], PAGE.markdown, 'והתצוגה היא עדיין העמוד');
});

check('טעינה איטית של גרסה קודמת לא דורסת את ההודעה של הגרסה שנבחרה אחריה', async () => {
  // הבחירה (``fileSelectionSeq``) לא משתנה בין גרסאות של אותו קובץ. נופל אם ``renderPreview``
  // יפסיק לבדוק את ``previewRenderSeq``.
  const sb = makeSandbox({
    [FILE_URL]: { content: 'נוכחי\n', language: 'text', has_docs_page: true },
    [PAGE_URL]: { gate: true },
  }, PREFERS_PREVIEW);
  const opening = sb.selectFile(RST, null);
  await waitFor(() => sb.__gates.length === 1, 'הבקשה לעמוד בפתיחת הקובץ');
  sb.__open(0, PAGE);
  await opening;

  const older = sb.window.RepoState.setFileContent('ישן\n', { ref: 'b'.repeat(40) });
  const newer = sb.window.RepoState.setFileContent('נוכחי\n', { ref: 'c'.repeat(40) });
  await waitFor(() => sb.__gates.length === 3, 'שתי הבקשות של ההיסטוריה');
  sb.__open(2, { ...PAGE, freshness: 'current' });
  await newer;
  sb.__open(1, { ...PAGE, markdown: '# ישן\n', freshness: 'changed' });
  await older;

  eq(sb.document.getElementById('markdown-preview-note').hidden, true, 'ההודעה של הגרסה האחרונה');
  eq(sb.__rendered[sb.__rendered.length - 1], PAGE.markdown, 'והעמוד שלה');
});

(async () => {
  await Promise.all(pending);
  console.log(`\n${passed} עברו, ${failed} נכשלו`);
  process.exit(failed === 0 ? 0 : 1);
})();
