'use strict';
// בדיקות לחיפוש בתוך קובץ בדפדפן הריפו (``webapp/static/js/repo-browser.js``): על איזו תצוגה הוא
// רץ, מה המונה מציג, איזו התאמה פעילה ולאן גוללים, מה מנוקה בסגירה, ומתי הוא רץ שוב.
//
// **מה נבדק כאן, ומה לא.** כאן נבדקת ההחלטה של דפדפן הריפו: בתצוגה המרונדרת — לבקש מ-``TextHighlight``
// להדגיש את מיכל התצוגה, לספור את מה שחזר, לסמן פעילה ולגלול רק את התצוגה; בתצוגת הקוד — לספור בטקסט
// שבעורך, כמו קודם. ``TextHighlight`` מוחלף כאן בהקלטה, ולכן מה שהוא עושה בפועל ב-DOM — העטיפות, הדילוג,
// הגלילה — נבדק בכרומיום: ``tests/test_repo_browser_in_file_search_browser.py`` (החיפוש בדפדפן הריפו)
// ו-``tests/test_text_highlight_browser.py`` (המודול). הבדיקות כאן רצות ב-CI, ושם בדיקות הדפדפן מדולגות.
//
// ההתקנה כמו ב-``repo-browser-docs-page.test.js``: sandbox של vm עם DOM מינימלי, והקובץ נטען כמו שהוא.

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

/** אלמנט מינימלי, עם ``classList`` אמיתי — הבדיקות כאן שואלות איזו התאמה פעילה. */
function el(id) {
  const classes = new Set();
  return {
    id, style: {}, dataset: {}, textContent: '', value: '', innerHTML: '', title: '',
    classList: {
      add: (c) => { classes.add(c); },
      remove: (c) => { classes.delete(c); },
      contains: (c) => classes.has(c),
      toggle: (c, on) => {
        const next = on === undefined ? !classes.has(c) : !!on;
        if (next) classes.add(c); else classes.delete(c);
        return next;
      },
    },
    appendChild() {}, append() {}, addEventListener() {}, removeEventListener() {},
    querySelector: () => null, querySelectorAll: () => [],
    setAttribute() {}, getAttribute: () => null, remove() {}, click() {}, focus() {}, select() {}, blur() {},
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }),
  };
}

/**
 * ``highlighter`` — ``null`` מדמה מודול שלא נטען. אחרת ``hits`` הוא מספר העטיפות ש-``highlightWithin``
 * מחזיר, וכל קריאה למודול נרשמת ב-``calls``.
 *
 * ``realRender`` — מסלול הרינדור האמיתי של ``renderPreview`` ו-``renderMarkdownPreview``, כשרק
 * ``MarkdownLiveRenderer`` מוחלף: כל ``renderWithAnchors`` ממתין עד שהבדיקה משחררת אותו
 * (``__renders[i].resolve``), כדי שאפשר יהיה לסיים רינדורים בסדר הפוך.
 */
function makeSandbox({ highlighter = true, hits = 3, realRender = false } = {}) {
  const nodes = new Map();
  const byId = (id) => {
    if (!nodes.has(id)) nodes.set(id, el(id));
    return nodes.get(id);
  };
  byId('current-repo-name').dataset.repo = 'CodeBot';
  // הסרגל מוסתר כמו בתבנית (``repo/index.html``), עד ש-``searchInFile`` מציג אותו.
  byId('in-file-search').style.display = 'none';
  const calls = { highlight: [], clear: [], scroll: [] };
  const TextHighlight = highlighter ? {
    highlightWithin(root, term, opts) {
      const made = Array.from({ length: hits }, (_, i) => el(`hit-${calls.highlight.length}-${i}`));
      calls.highlight.push({ root, term, opts, made });
      return made;
    },
    clearHighlights(root, className) { calls.clear.push({ root, className }); return 0; },
    scrollIntoViewWithin(root, hit) { calls.scroll.push({ root, hit }); },
  } : undefined;

  const sandbox = {
    console: { log: console.log, warn() {}, error() {} },
    document: {
      body: el('body'), documentElement: el('html'),
      getElementById: byId,
      querySelector: () => null, querySelectorAll: () => [],
      createElement: () => el(''),
      addEventListener() {}, removeEventListener() {}, dispatchEvent() { return true; },
    },
    window: {
      addEventListener() {}, removeEventListener() {},
      innerWidth: 1024, innerHeight: 768,
      location: { hash: '', search: '', href: '' },
      matchMedia: () => ({ matches: false }),
      history: { replaceState() {} },
      TextHighlight,
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    navigator: { clipboard: {} },
    fetch: () => Promise.reject(new Error('אין רשת בבדיקה')),
    URLSearchParams, AbortSignal, AbortController,
    setTimeout, clearTimeout, setInterval, clearInterval,
    requestAnimationFrame: (f) => setTimeout(f, 0),
  };
  sandbox.CustomEvent = function (type, init) { return { type, detail: (init || {}).detail }; };
  sandbox.globalThis = sandbox;
  sandbox.self = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);

  // הרינדור והעורך אינם הנושא כאן. מה שנשאר מהם: התצוגה המרונדרת "מוצגת" אחרי ``enableMarkdownPreview``,
  // ותצוגת הקוד אחרי ``disableMarkdownPreview`` — הדגל ``state.markdownPreviewEnabled`` הוא האמיתי.
  if (realRender) {
    sandbox.__renders = [];
    sandbox.MarkdownLiveRenderer = {
      isSupported: () => true,
      renderWithAnchors: (content) => new Promise((resolve) => sandbox.__renders.push({ content, resolve })),
      enhance: async () => {},
    };
    for (const name of ['ensureHighlightJsLoaded', 'loadMarkdownDependencies']) sandbox[name] = async () => {};
    for (const name of ['applySyntaxHighlighting', 'setupMarkdownAnchorScrolling']) sandbox[name] = () => {};
  } else {
    sandbox.renderPreview = async () => {};
  }
  sandbox.ensureCodeViewerInitialized = async () => {};
  sandbox.emitRepoViewChanged = () => {};
  sandbox.__calls = calls;
  sandbox.__byId = byId;
  return sandbox;
}

const CONTENT = 'alpha beta\nAlpha gamma alpha';

/** קובץ שמוצג, והסרגל פתוח עם ``term`` בתיבה — כמו אחרי הקלדה. */
async function openWithSearch(sb, { rendered, term = 'alpha' }) {
  await sb.window.RepoState.setFileContent(CONTENT);
  if (rendered) await sb.enableMarkdownPreview();
  else sb.disableMarkdownPreview();
  sb.searchInFile();
  sb.__byId('in-file-search-input').value = term;
  sb.performInFileSearch(term);
}

const count = (sb) => sb.__byId('in-file-search-count').textContent;

/** מחכה עד ש-``n`` רינדורים התחילו — כל אחד עובר כמה ``await`` לפני ``renderWithAnchors``. */
async function waitForRender(sb, n) {
  for (let i = 0; i < 50 && sb.__renders.length < n; i += 1) await new Promise((r) => setTimeout(r, 0));
  eq(sb.__renders.length, n, 'מספר הרינדורים שהתחילו');
}
const activeOf = (hits) => hits.map((h, i) => (h.classList.contains('is-active') ? i : -1)).filter((i) => i >= 0);

check('בתצוגה המרונדרת: מדגישים את מיכל התצוגה, סופרים את העטיפות, והראשונה פעילה', async () => {
  const sb = makeSandbox({ hits: 3 });
  await openWithSearch(sb, { rendered: true });
  eq(sb.__calls.highlight.length, 1, 'קריאה אחת להדגשה');
  const { root, term, opts } = sb.__calls.highlight[0];
  eq(root, sb.__byId('markdown-preview-content'), 'השורש הוא התצוגה המרונדרת');
  eq(term, 'alpha', 'המונח');
  eq(opts.className, 'in-file-search-hit', 'המחלקה של דפדפן הריפו');
  eq(count(sb), '1 / 3', 'המונה סופר את מה שהודגש, ולא את המקור (3 גם במקור — ראו הבדיקה הבאה)');
});

check('בתצוגה המרונדרת: הספירה היא של התצוגה גם כשהמקור אומר אחרת', async () => {
  // במקור "alpha" מופיע שלוש פעמים. אם הספירה הייתה מהמקור, המונה היה 3.
  const sb = makeSandbox({ hits: 5 });
  await openWithSearch(sb, { rendered: true });
  eq(count(sb), '1 / 5', 'המונה');
});

check('בתצוגה המרונדרת: הבא מעביר את הסימון וגולל את התצוגה בלבד, במעגל', async () => {
  const sb = makeSandbox({ hits: 3 });
  await openWithSearch(sb, { rendered: true });
  const hits = sb.__calls.highlight[0].made;
  eq(JSON.stringify(activeOf(hits)), '[0]', 'אחרי ההקלדה');
  sb.findNextMatch();
  eq(JSON.stringify(activeOf(hits)), '[1]', 'אחרי הבא — אחת פעילה, השנייה');
  eq(count(sb), '2 / 3', 'המונה');
  const last = sb.__calls.scroll[sb.__calls.scroll.length - 1];
  eq(last.root, sb.__byId('markdown-preview-container'), 'נגלל מיכל התצוגה, ולא העמוד');
  eq(last.hit, hits[1], 'אל ההתאמה הפעילה');
  sb.findNextMatch();
  sb.findNextMatch();
  eq(JSON.stringify(activeOf(hits)), '[0]', 'מהאחרונה חוזרים לראשונה');
  sb.findPrevMatch();
  eq(count(sb), '3 / 3', 'הקודם מהראשונה הוא האחרונה');
});

check('בתצוגת הקוד: החיפוש בטקסט שבעורך, כמו קודם, בלי הדגשה בתצוגה המרונדרת', async () => {
  const sb = makeSandbox({ hits: 9 });
  await openWithSearch(sb, { rendered: false });
  eq(sb.__calls.highlight.length, 0, 'אין הדגשה');
  eq(count(sb), '1 / 3', 'שלוש התאמות בטקסט, בלי רישיות');
});

check('סגירה מנקה את ההדגשות של התצוגה המרונדרת, במחלקה של דפדפן הריפו', async () => {
  const sb = makeSandbox({ hits: 2 });
  await openWithSearch(sb, { rendered: true });
  const before = sb.__calls.clear.length;
  sb.closeInFileSearch();
  const last = sb.__calls.clear[sb.__calls.clear.length - 1];
  eq(sb.__calls.clear.length, before + 1, 'ניקוי אחד בסגירה');
  eq(last.root, sb.__byId('markdown-preview-content'), 'מהתצוגה המרונדרת');
  eq(last.className, 'in-file-search-hit', 'רק ההדגשות של החיפוש הזה');
  eq(count(sb), '', 'המונה ריק');
});

check('מעבר תצוגה עם חיפוש פתוח מחפש מחדש בתצוגה החדשה', async () => {
  const sb = makeSandbox({ hits: 4 });
  await openWithSearch(sb, { rendered: true });
  eq(count(sb), '1 / 4', 'בתצוגה המרונדרת');
  await sb.toggleMarkdownPreview();
  eq(count(sb), '1 / 3', 'בתצוגת הקוד — הספירה של הטקסט');
  eq(sb.__calls.highlight.length, 1, 'בתצוגת הקוד אין הדגשה חדשה');
  await sb.toggleMarkdownPreview();
  eq(count(sb), '1 / 4', 'ובחזרה — שוב של התצוגה');
  eq(sb.__calls.highlight.length, 2, 'הדגשה מחדש אחרי החזרה');
});

check('מעבר תצוגה כשהחיפוש סגור אינו מחפש', async () => {
  const sb = makeSandbox({ hits: 4 });
  await openWithSearch(sb, { rendered: true });
  sb.closeInFileSearch();
  const highlights = sb.__calls.highlight.length;
  await sb.toggleMarkdownPreview();
  await sb.toggleMarkdownPreview();
  eq(sb.__calls.highlight.length, highlights, 'אין הדגשה חדשה');
  eq(count(sb), '', 'המונה נשאר ריק');
});

check('גרסה מההיסטוריה עם חיפוש פתוח מחפשת מחדש בתוכן החדש', async () => {
  const sb = makeSandbox({ hits: 4 });
  await openWithSearch(sb, { rendered: false });
  eq(count(sb), '1 / 3', 'בגרסה הנוכחית');
  await sb.window.RepoState.setFileContent('alpha only once');
  eq(count(sb), '1 / 1', 'בגרסה מההיסטוריה');
});

check('שתי גרסאות מההיסטוריה ברצף: רינדור איטי של הראשונה לא נכתב מעל השנייה', async () => {
  // הבחירה (``fileSelectionSeq``) זהה בשתי הגרסאות, ולכן רק ``previewRenderSeq`` מבחין ביניהן. בלעדיו
  // ה-HTML של הגרסה הראשונה היה נכתב אחרון, והחיפוש הפתוח היה רץ עליו.
  const sb = makeSandbox({ realRender: true });
  await sb.window.RepoState.setFileContent('# נוכחי');
  const enabling = sb.enableMarkdownPreview();
  await waitForRender(sb, 1);
  sb.__renders[0].resolve({ html: '<h1>נוכחי</h1>', anchors: [] });
  await enabling;

  const older = sb.window.RepoState.setFileContent('# ישן', { ref: 'b'.repeat(40) });
  const newer = sb.window.RepoState.setFileContent('# חדש', { ref: 'c'.repeat(40) });
  await waitForRender(sb, 3);
  eq(sb.__renders[1].content, '# ישן', 'הרינדור של הראשונה');
  sb.__renders[2].resolve({ html: '<h1>חדש</h1>', anchors: [] });
  await newer;
  sb.__renders[1].resolve({ html: '<h1>ישן</h1>', anchors: [] });
  await older;
  eq(sb.__byId('markdown-preview-content').innerHTML, '<h1>חדש</h1>', 'התצוגה של הגרסה שנבחרה אחרונה');
});

check('בלי המודול: התצוגה המרונדרת אומרת שהחיפוש אינו זמין, ואינה סופרת את המקור', async () => {
  const sb = makeSandbox({ highlighter: false });
  await openWithSearch(sb, { rendered: true });
  // בחיפוש במקור המונה היה ``1 / 3``.
  eq(count(sb), 'Unavailable', 'המונה');
  sb.findNextMatch();
  eq(count(sb), 'Unavailable', 'ואין התאמות לנווט אליהן');
});

Promise.all(pending).then(() => {
  console.log(`${passed} עברו, ${failed} נכשלו`);
  process.exit(failed === 0 ? 0 : 1);
});
