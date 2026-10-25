'use strict';
// בדיקות ל-``webapp/static/js/notes-archive.js`` — עמוד הארכיון של הפתקים.
//
// **מה כאן:** חלוקת השם לרצפים (``NotesArchiveText``), והדבק של העמוד — שלושת מצבי הטעינה,
// בניית הכרטיסים, "נסו שוב" עם קישור עמוק, ומה קורה לכרטיס כשהפתק הפתוח נסגר או נמחק. המנהל
// עצמו (``StickyNotesManager``) מוחלף כאן ברשם: הוא נבדק ב-``sticky-notes-target.test.js``.
//
// **ומה לא:** פריסה, חיתוך לארבע שורות, כיוון אמיתי בדפדפן ומיקוד — ב-
// ``tests/test_note_archive_browser.py``, בכרומיום.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = fs.readFileSync(path.join(__dirname, '..', 'webapp', 'static', 'js', 'notes-archive.js'), 'utf8');

let passed = 0, failed = 0;
const pending = [];
function check(name, fn) {
  const fail = (e) => { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); };
  try {
    const out = fn();
    if (out && typeof out.then === 'function') { pending.push(out.then(() => { passed += 1; }, fail)); return; }
    passed += 1;
  } catch (e) { fail(e); }
}
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

/** אלמנט מדומה — רק מה שהעמוד נוגע בו. */
class El {
  constructor(tag, id) {
    this.tagName = tag; this.id = id || ''; this.children = []; this.parentNode = null;
    this.attrs = {}; this.hidden = false; this._text = ''; this.listeners = {};
    // ``setProperty`` / ``getPropertyValue`` כמו ב-``CSSStyleDeclaration`` — הצבע של כרטיס הוא טוקן.
    const props = {};
    this.style = { setProperty: (k, v) => { props[k] = String(v); }, getPropertyValue: (k) => props[k] || '' };
    this._classes = new Set();
    const self = this;
    this.classList = {
      add: (c) => self._classes.add(c), remove: (c) => self._classes.delete(c),
      contains: (c) => self._classes.has(c),
    };
  }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this._classes].join(' '); }
  set textContent(v) { this.children.forEach((c) => { c.parentNode = null; }); this.children = []; this._text = String(v); }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join('') : this._text; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  remove() { if (this.parentNode) { const p = this.parentNode; p.children = p.children.filter((c) => c !== this); this.parentNode = null; } }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n.tagName === 'body'; }
  get nextElementSibling() { const s = this.parentNode && this.parentNode.children; return s ? s[s.indexOf(this) + 1] || null : null; }
  get previousElementSibling() { const s = this.parentNode && this.parentNode.children; return s ? s[s.indexOf(this) - 1] || null : null; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  focus() { El.focused = this; }
  getBoundingClientRect() { return { left: 0, top: 0, width: 148, height: 148 }; }
  querySelector(sel) {
    const cls = sel.slice(1);
    for (const c of this.children) {
      if (c._classes.has(cls)) return c;
      const deep = c.querySelector(sel);
      if (deep) return deep;
    }
    return null;
  }
}

/**
 * מריץ את העמוד. ``answer(url)`` מחזיר ``[status, body]``; ``search`` היא מחרוזת השאילתה של
 * הכתובת. מחזיר את הרשמים: הבקשות, הטוסטים, ההחלפות של ההיסטוריה והמנהל המדומה.
 */
function runPage({ answer, search = '' }) {
  const body = new El('body');
  const ids = {};
  for (const [id, tag] of [['archiveGrid', 'div'], ['archiveMain', 'main'], ['archiveOverlay', 'div'],
    ['archiveBackdrop', 'div'], ['archiveError', 'div'], ['archiveRetry', 'button'],
    ['archiveEmpty', 'div'], ['archiveCount', 'span']]) {
    ids[id] = body.appendChild(new El(tag, id));
  }
  const requests = [];
  const toasts = [];
  const replaced = [];
  const mgr = { opts: null, opened: [], closed: 0 };
  const location = { search, pathname: '/boards/archive' };
  const docListeners = {};
  const window = {
    location,
    history: { replaceState: (_s, _t, url) => { replaced.push(url); location.search = ''; } },
    ckToast: (message, type) => { toasts.push({ message, type }); return true; },
    StickyNotesManager: function StickyNotesManager(opts) {
      mgr.opts = opts;
      this.openArchivedNote = (note, o) => { mgr.opened.push({ note, opts: o }); return new El('div'); };
      this.closeArchivedNote = () => { mgr.closed += 1; };
    },
  };
  const sandbox = {
    window, console, URLSearchParams, setTimeout,
    document: {
      body,
      getElementById: (id) => ids[id] || null,
      createElement: (tag) => new El(tag),
      addEventListener: (type, fn) => { docListeners[type] = fn; },
    },
    fetch: async (url) => {
      requests.push(String(url));
      const [status, json] = answer(String(url));
      return { ok: status >= 200 && status < 300, status, json: async () => json };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);
  const cards = () => ids.archiveGrid.children.filter((c) => c._classes.has('archive-card') && !c._classes.has('is-skeleton'));
  return { ids, requests, toasts, replaced, mgr, cards, docListeners, window };
}

const card = (id, title, color = '#fff9c4') => ({ id, title, color, archived_at: '2026-10-25T10:00:00+00:00' });

// ─── חלוקת השם לרצפים ────────────────────────────────────────────────────

const text = (() => {
  const sandbox = { window: {}, document: { getElementById: () => null } };
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);
  return sandbox.window.NotesArchiveText;
})();
const runs = (s) => text.titleRuns(s).map((r) => `${r.dir}:${r.text}`);

check('נתיב בתוך שם עברי מבודד כרצף LTR אחד — הלוכסן לא נודד לצד השני', () => {
  eq(JSON.stringify(runs('תיקון /admin/mcp בדף')), JSON.stringify(['rtl:תיקון ', 'ltr:/admin/mcp', 'rtl: בדף']));
});

check('כמה מילים לטיניות ברצף הן רצף אחד; ו-"ו-" העברי נשאר בחוץ', () => {
  eq(JSON.stringify(runs('שדרוג React Query ו-Vite')),
    JSON.stringify(['rtl:שדרוג ', 'ltr:React Query', 'rtl: ו-', 'ltr:Vite']));
});

check('פיסוק בסוף רצף שייך למשפט, לא לרצף', () => {
  eq(JSON.stringify(runs('באג #3542.')), JSON.stringify(['rtl:באג ', 'ltr:#3542', 'rtl:.']));
});

check('החיבור של הרצפים הוא השם עצמו — שום תו לא נוסף ולא אבד', () => {
  for (const s of ['תיקון /admin/mcp בדף.', 'a', 'שלום', 'v2.1: שחרור', 'מייל a@b.co, ועוד', '😀 emoji']) {
    eq(text.titleRuns(s).map((r) => r.text).join(''), s, s);
  }
});

check('כיוון הפסקה: עברית כלשהי ← rtl; בלי עברית ← ltr', () => {
  eq(text.titleDir('Fix login bug'), 'ltr', 'אנגלית');
  eq(text.titleDir('Fix באג'), 'rtl', 'מעורב');
  eq(text.titleDir(''), 'ltr', 'ריק');
});

// ─── מצבי הטעינה ─────────────────────────────────────────────────────────

check('טעינה שנכשלה (500) היא מצב שגיאה עם "נסו שוב" — ולא "הארכיון ריק"', async () => {
  const p = runPage({ answer: () => [500, { ok: false, error: 'Failed to list archived notes' }] });
  await tick(); await tick();
  eq(p.ids.archiveError.hidden, false, 'השגיאה מוצגת');
  eq(p.ids.archiveEmpty.hidden, true, 'ו"ריק" לא');
  eq(p.ids.archiveGrid.hidden, true, 'והרשת מוסתרת');
  eq(p.cards().length, 0, 'בלי כרטיסים ובלי שלד');
});

check('ארכיון ריק הוא מצב משלו', async () => {
  const p = runPage({ answer: () => [200, { ok: true, notes: [], count: 0, max: 500 }] });
  await tick(); await tick();
  eq(p.ids.archiveEmpty.hidden, false, 'ריק מוצג');
  eq(p.ids.archiveError.hidden, true, 'בלי שגיאה');
  eq(p.ids.archiveCount.textContent, '0 / 500', 'המונה');
});

check('הכרטיסים נבנים בסדר שהשרת נתן, עם שם, צבע ו"ללא שם" לפתק בלי שם', async () => {
  const p = runPage({ answer: () => [200, { ok: true, notes: [card('a', 'חדש'), card('b', '', '#c8e6c9')], max: 500 }] });
  await tick(); await tick();
  const [first, second] = p.cards();
  eq(p.cards().length, 2, 'שני כרטיסים');
  eq(first.getAttribute('data-note-id'), 'a', 'הסדר של השרת — החדש קודם');
  eq(first.tagName, 'button', 'כפתור — נגיש במקלדת');
  eq(first.querySelector('.archive-card-title').textContent, 'חדש', 'השם');
  eq(second.querySelector('.archive-card-title').textContent, 'ללא שם', 'פתק בלי שם');
  eq(second.querySelector('.archive-card-title').classList.contains('is-untitled'), true, 'מסומן');
  eq(second.style.getPropertyValue('--archive-card-color'), '#c8e6c9', 'הצבע — כטוקן שהכלל ב-CSS קורא');
  eq(p.ids.archiveCount.textContent, '2 / 500', 'המונה עם התקרה');
  eq(p.ids.archiveGrid.attrs['aria-busy'], 'false', 'הטעינה הסתיימה');
});

check('לאדמין אין תקרה (max: null) — המונה בלי "/"', async () => {
  const p = runPage({ answer: () => [200, { ok: true, notes: [card('a', 'x')], max: null }] });
  await tick(); await tick();
  eq(p.ids.archiveCount.textContent, '1', 'המונה');
});

// ─── קישור עמוק ו"נסו שוב" ──────────────────────────────────────────────

check('קישור עמוק פותח את הפתק, מעביר את השרשור, ויורד מהכתובת', async () => {
  const p = runPage({
    search: '?note=a&thread=' + 'c'.repeat(24),
    answer: (url) => (url.endsWith('/archive') ? [200, { ok: true, notes: [card('a', 'x')], max: 500 }]
      : [200, { ok: true, note: { id: 'a', title: 'x' } }]),
  });
  await tick(); await tick(); await tick();
  eq(p.mgr.opened.length, 1, 'הפתק נפתח');
  eq(p.mgr.opened[0].opts.threadId, 'c'.repeat(24), 'עם השרשור');
  eq(p.replaced.join(), '/boards/archive', 'הפרמטרים ירדו מהכתובת');
  eq(p.ids.archiveMain.inert, true, 'הרשת inert בזמן שהפתק פתוח');
});

check('"נסו שוב" אחרי טעינה שנכשלה — והקישור העמוק נפתח כשהרשת נטענת', async () => {
  // נופל על הצורה הקודמת: "נסו שוב" טען את הרשת בלבד, והפתק מההתראה לא נפתח.
  let fail = true;
  const p = runPage({
    search: '?note=a',
    answer: (url) => {
      if (url.endsWith('/archive')) return fail ? [500, { ok: false }] : [200, { ok: true, notes: [card('a', 'x')], max: 500 }];
      return [200, { ok: true, note: { id: 'a', title: 'x' } }];
    },
  });
  await tick(); await tick();
  eq(p.mgr.opened.length, 0, 'בקרה: הטעינה נכשלה, ושום פתק לא נפתח');
  eq(p.replaced.length, 0, 'והקישור עוד בכתובת');
  fail = false;
  await p.ids.archiveRetry.listeners.click();
  await tick();
  eq(p.cards().length, 1, 'הרשת נטענה');
  eq(p.mgr.opened.length, 1, 'והפתק מהקישור נפתח');
  await p.ids.archiveRetry.listeners.click();
  await tick();
  eq(p.mgr.opened.length, 1, 'טעינה נוספת אינה פותחת אותו שוב — הקישור נצרך');
});

// ─── פתיחה, סגירה ומחיקה ─────────────────────────────────────────────────

check('לחיצה על כרטיס שכבר נמחק ממכשיר אחר (404): הכרטיס יורד, והמשתמש יודע למה', async () => {
  const p = runPage({
    answer: (url) => (url.endsWith('/archive') ? [200, { ok: true, notes: [card('a', 'x')], max: 500 }]
      : [404, { ok: false, error: 'note_not_found' }]),
  });
  await tick(); await tick();
  await p.cards()[0].listeners.click();
  await tick();
  eq(p.cards().length, 0, 'הכרטיס ירד');
  eq(p.mgr.opened.length, 0, 'שום פתק לא נפתח');
  eq(p.toasts[0].type, 'info', 'הודעה');
  eq(p.ids.archiveEmpty.hidden, false, 'והארכיון ריק עכשיו');
});

check('פתיחה שנכשלה (500): הודעת שגיאה, והרשת נשארת פעילה', async () => {
  const p = runPage({
    answer: (url) => (url.endsWith('/archive') ? [200, { ok: true, notes: [card('a', 'x')], max: 500 }] : [500, { ok: false }]),
  });
  await tick(); await tick();
  await p.cards()[0].listeners.click();
  await tick();
  eq(p.toasts[0].type, 'error', 'שגיאה');
  eq(p.ids.archiveMain.inert === true, false, 'הרשת אינה inert');
  eq(p.cards().length, 1, 'והכרטיס במקומו');
});

check('סגירת הפתק מעדכנת את הכרטיס בשם ובצבע שבפתק עכשיו, ומחזירה אליו את המיקוד', async () => {
  const p = runPage({
    answer: (url) => (url.endsWith('/archive') ? [200, { ok: true, notes: [card('a', 'ישן')], max: 500 }]
      : [200, { ok: true, note: { id: 'a', title: 'ישן' } }]),
  });
  await tick(); await tick();
  const c = p.cards()[0];
  await c.listeners.click();
  p.mgr.opts.onArchivedNoteClosed({ id: 'a', title: 'חדש', color: '#bbdefb' });
  eq(c.querySelector('.archive-card-title').textContent, 'חדש', 'השם');
  eq(c.style.getPropertyValue('--archive-card-color'), '#bbdefb', 'הצבע');
  eq(p.ids.archiveOverlay.hidden, true, 'השכבה נסגרה');
  eq(p.ids.archiveMain.inert, false, 'הרשת פעילה');
  eq(El.focused, c, 'המיקוד חזר לכרטיס');
});

check('מחיקת הפתק הפתוח מורידה את הכרטיס, מעדכנת את המונה ומעבירה את המיקוד לשכן', async () => {
  const p = runPage({
    answer: (url) => (url.endsWith('/archive') ? [200, { ok: true, notes: [card('a', 'x'), card('b', 'y')], max: 500 }]
      : [200, { ok: true, note: { id: 'a', title: 'x' } }]),
  });
  await tick(); await tick();
  const [a, b] = p.cards();
  await a.listeners.click();
  p.mgr.opts.onArchivedNoteDeleted('a');
  eq(p.cards().length, 1, 'כרטיס אחד נשאר');
  eq(p.cards()[0], b, 'והוא השני');
  eq(p.ids.archiveCount.textContent, '1 / 500', 'המונה');
  eq(El.focused, b, 'המיקוד עבר לשכן');
});

check('Escape סוגר את הפתק — אלא אם רכיב בתוכו כבר טיפל בו', async () => {
  const p = runPage({
    answer: (url) => (url.endsWith('/archive') ? [200, { ok: true, notes: [card('a', 'x')], max: 500 }]
      : [200, { ok: true, note: { id: 'a', title: 'x' } }]),
  });
  await tick(); await tick();
  await p.cards()[0].listeners.click();
  p.docListeners.keydown({ key: 'Escape', defaultPrevented: true, preventDefault() {} });
  eq(p.mgr.closed, 0, 'רכיב בפתק טיפל — העמוד אינו סוגר');
  p.docListeners.keydown({ key: 'Escape', defaultPrevented: false, preventDefault() {} });
  eq(p.mgr.closed, 1, 'Escape רגיל סוגר');
});

(async () => {
  await Promise.all(pending);
  console.log(`${passed} עברו, ${failed} נכשלו`);
  process.exit(failed === 0 ? 0 : 1);
})();
