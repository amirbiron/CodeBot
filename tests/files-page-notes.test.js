'use strict';
// בדיקות ל-``webapp/static/js/files-page-notes.js`` — הפתקים הנעוצים בראש עמוד הקבצים.
//
// **מה כאן:** הדבק של העמוד — טעינה שנכשלה מול "אין נעוצים", כמה כרטיסים נכנסים בשורה ומה עובר
// אל מאחורי "+N", המעבר לפס כותרות (גובה, הכרזה — ולא רוחב), שמירת רוחב השורה רק במצב כרטיסים,
// הרשימה של "+N", ומה קורה לכרטיס כשהפתק הפתוח נסגר, עוזב את העמוד או כבר אינו נעוץ. המנהל עצמו
// (``StickyNotesManager``) מוחלף ברשם: הוא נבדק ב-``sticky-notes-target.test.js``.
//
// **ומה לא:** פריסה אמיתית, מיקוד אמיתי וצבעים — ב-``tests/test_files_page_pins_browser.py``, בכרומיום.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const JS = path.join(__dirname, '..', 'webapp', 'static', 'js');
const SRC = fs.readFileSync(path.join(JS, 'files-page-notes.js'), 'utf8');
const CARDS_SRC = fs.readFileSync(path.join(JS, 'note-cards.js'), 'utf8');

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

/** אלמנט מדומה — רק מה שהעמוד ורכיב הכרטיס נוגעים בו. ``width`` של מלבן לפי מחלקה. */
class El {
  constructor(tag, id) {
    this.tagName = tag; this.id = id || ''; this.children = []; this.parentNode = null;
    this.attrs = {}; this.hidden = false; this._text = ''; this.listeners = {}; this.type = '';
    const props = {};
    this.style = { setProperty: (k, v) => { props[k] = String(v); }, getPropertyValue: (k) => props[k] || '', display: '' };
    this._classes = new Set();
    const self = this;
    this.classList = {
      add: (c) => self._classes.add(c), remove: (c) => self._classes.delete(c), contains: (c) => self._classes.has(c),
    };
  }
  set className(v) { this._classes = new Set(String(v).split(/\s+/).filter(Boolean)); }
  get className() { return [...this._classes].join(' '); }
  set textContent(v) { this.children.forEach((c) => { c.parentNode = null; }); this.children = []; this._text = String(v); }
  get textContent() { return this.children.length ? this.children.map((c) => c.textContent).join('') : this._text; }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  appendChild(c) { if (c.parentNode) c.remove(); c.parentNode = this; this.children.push(c); return c; }
  removeChild(c) { c.remove(); return c; }
  remove() { if (this.parentNode) { const p = this.parentNode; p.children = p.children.filter((c) => c !== this); this.parentNode = null; } }
  contains(n) { while (n) { if (n === this) return true; n = n.parentNode; } return false; }
  get isConnected() { let n = this; while (n.parentNode) n = n.parentNode; return n.tagName === 'body'; }
  get previousElementSibling() { const s = this.parentNode && this.parentNode.children; return s ? s[s.indexOf(this) - 1] || null : null; }
  get nextElementSibling() { const s = this.parentNode && this.parentNode.children; return s ? s[s.indexOf(this) + 1] || null : null; }
  addEventListener(type, fn) { this.listeners[type] = fn; }
  focus() { El.focused = this; }
  getBoundingClientRect() {
    // רוחב לכל עמוד בנפרד (``rowWidth`` של ``runPage``): הבדיקות האסינכרוניות רצות במקביל, ומשתנה
    // משותף היה מזיז את הרוחב של בדיקה אחת באמצע אחרת.
    const w = this._classes.has('files-page-cards') ? this.__width
      : this._classes.has('files-page-more-wrap') ? 50 : 0;
    return { left: 0, top: 0, width: w, height: 0 };
  }
  _all(pred, out) { for (const c of this.children) { if (pred(c)) out.push(c); c._all(pred, out); } return out; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) {
    if (sel === '[data-note-id]') return this._all((c) => 'data-note-id' in c.attrs, []);
    if (sel === 'button') return this._all((c) => c.tagName === 'button', []);
    if (sel.startsWith('.')) return this._all((c) => c._classes.has(sel.slice(1)), []);
    throw new Error(`הדמה אינה מכירה ${sel}`);
  }
}

/**
 * מריץ את העמוד. ``answer(url)`` מחזיר ``[status, body]``. ``innerHeight`` — גובה החלון; ``banner`` —
 * האם ההכרזה של ``base.html`` מוצגת. מחזיר את הרשמים.
 */
function runPage({ answer, innerHeight = 800, banner = false, store = {}, rowWidth = 975 }) {
  const body = new El('body');
  const main = body.appendChild(new El('main'));
  main.className = 'main-content';
  const ids = {};
  for (const [id, tag, cls] of [['filesPageNotes', 'section', 'files-page-notes'],
    ['filesPageCards', 'div', 'files-page-cards note-cards'], ['filesPageNotesError', 'div', 'files-page-notes-error'],
    ['filesPageNotesRetry', 'button', ''], ['announcementBanner', 'div', 'announcement-banner']]) {
    ids[id] = main.appendChild(new El(tag, id));
    ids[id].className = cls;
  }
  ids.filesPageCards.__width = rowWidth;
  ids.filesPageNotes.hidden = true;
  ids.filesPageNotesError.hidden = true;
  ids.announcementBanner.setAttribute('aria-hidden', banner ? 'false' : 'true');
  ids.announcementBanner.style.display = banner ? '' : 'none';
  const requests = [];
  const toasts = [];
  const recorded = [];
  const mgr = { opts: null, opened: [], closed: 0 };
  const docListeners = {};
  const window = {
    innerHeight,
    ckToast: (message, type) => { toasts.push({ message, type }); return true; },
    ensureHandwritingFont: () => { window.__fontLoaded = (window.__fontLoaded || 0) + 1; },
    requestAnimationFrame: (fn) => { fn(); return 1; },
    addEventListener() {},
    localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } },
    StickyNotesFilesPage: {
      CARD_W: 168, CARD_GAP: 12,
      cardsThatFit: (w, cw, g) => Math.max(0, Math.floor((w + g) / (cw + g))),
      recordRowWidth: (w) => { recorded.push(w); },
    },
    StickyNotesManager: function StickyNotesManager(opts) {
      mgr.opts = opts;
      this.openOverlayNote = (note, o) => { mgr.opened.push({ note, opts: o }); return new El('div'); };
      this.closeOverlayNote = () => { mgr.closed += 1; };
    },
  };
  const sandbox = {
    window, console, setTimeout,
    document: {
      body,
      getElementById: (id) => ids[id] || (id === 'filesPageNoteOverlay' ? null : null),
      querySelector: (sel) => (sel === 'main.main-content' ? main : null),
      createElement: (tag) => new El(tag),
      addEventListener: (type, fn) => { docListeners[type] = fn; },
      // ``render`` זוכר על מה עמד המיקוד, כדי להחזיר אליו אחרי הבנייה מחדש — כמו בדפדפן.
      get activeElement() { return El.focused || null; },
    },
    fetch: async (url) => {
      requests.push(String(url));
      const [status, json] = answer(String(url));
      return { ok: status >= 200 && status < 300, status, json: async () => json };
    },
  };
  vm.createContext(sandbox);
  vm.runInContext(CARDS_SRC, sandbox);
  vm.runInContext(SRC, sandbox);
  const row = ids.filesPageCards;
  const cards = () => row.children.filter((c) => c._classes.has('archive-card'));
  const more = () => row.children.find((c) => c._classes.has('files-page-more-wrap')) || null;
  const overlay = body.children.find((c) => c.id === 'filesPageNoteOverlay');
  return { ids, main, row, requests, toasts, recorded, mgr, cards, more, overlay, docListeners, window, store };
}

const pin = (id, label, color = '#ffffcc') => ({ id, label, color, color_id: 'yellow', files_page_pinned_at: '2026-11-10T09:00:00+00:00' });
const list = (...notes) => (url) => (url === '/api/sticky-notes/files-page'
  ? [200, { ok: true, notes, count: notes.length, max: 4 }] : [200, { ok: true, note: { id: notes[0].id } }]);

// ─── מצבים ───────────────────────────────────────────────────────────────

check('בלי נעוצים האזור אינו מוצג — ואין הורדה של גופן כתב היד', async () => {
  const p = runPage({ answer: list() && (() => [200, { ok: true, notes: [], count: 0, max: 4 }]) });
  await tick(); await tick();
  eq(p.ids.filesPageNotes.hidden, true, 'מוסתר');
  eq(p.window.__fontLoaded || 0, 0, 'הגופן לא נטען');
});

check('טעינה שנכשלה (500) היא מצב שגיאה עם "נסו שוב" — ולא "אין נעוצים"', async () => {
  let fail = true;
  const p = runPage({ answer: (url) => (fail ? [500, { ok: false }] : list(pin('a', 'א'))(url)) });
  await tick(); await tick();
  eq(p.ids.filesPageNotes.hidden, false, 'האזור מוצג');
  eq(p.ids.filesPageNotesError.hidden, false, 'השגיאה מוצגת');
  eq(p.row.hidden, true, 'בלי כרטיסים');
  fail = false;
  p.ids.filesPageNotesRetry.listeners.click();
  await tick(); await tick();
  eq(p.ids.filesPageNotesError.hidden, true, 'השגיאה ירדה');
  eq(p.cards().length, 1, 'והכרטיס הגיע');
});

check('הכרטיסים בסדר שהשרת נתן, עם התווית והצבע — ובווריאנט של עמוד הקבצים', async () => {
  const p = runPage({ answer: list(pin('a', 'ראשון'), pin('b', '', '#bbdefb')) });
  await tick(); await tick();
  const [a, b] = p.cards();
  eq(a.getAttribute('data-note-id'), 'a', 'הראשון שננעץ ראשון');
  eq(a._classes.has('files-page-card'), true, 'הווריאנט');
  eq(a.querySelector('.archive-card-title').textContent, 'ראשון', 'התווית');
  eq(b.querySelector('.archive-card-title').textContent, 'ללא שם', 'תווית ריקה');
  eq(b.style.getPropertyValue('--archive-card-color'), '#bbdefb', 'הצבע כטוקן');
  eq(p.window.__fontLoaded, 1, 'הגופן נטען כשיש מה להציג');
  eq(p.row.style.getPropertyValue('--files-page-card-w'), '168px', 'הרוחב מ-sticky-notes.js');
});

// ─── כמה נכנסים ──────────────────────────────────────────────────────────

check('כולם נכנסים — בלי "+N"', async () => {
  const p = runPage({ answer: list(pin('a', 'א'), pin('b', 'ב'), pin('c', 'ג'), pin('d', 'ד')) });
  await tick(); await tick();
  eq(p.cards().length, 4, 'ארבעה');
  eq(p.more(), null, 'אין +N');
});

check('לא כולם נכנסים — כמה שנכנסים לצד "+N", ו-"+N" אומר כמה נשארו', async () => {
  // טלפון: שני כרטיסים — אבל לצד "+N" (50) נשאר מקום לאחד
  const p = runPage({ answer: list(pin('a', 'א'), pin('b', 'ב'), pin('c', 'ג'), pin('d', 'ד')), rowWidth: 366 });
  await tick(); await tick();
  eq(p.cards().length, 1, 'כרטיס אחד');
  eq(p.cards()[0].getAttribute('data-note-id'), 'a', 'הראשון בתור');
  const btn = p.more().querySelector('.files-page-more');
  eq(btn.textContent, '+3', 'שלושה נשארו');
  eq(btn.getAttribute('dir'), 'ltr', 'ה-+ לא נודד לצד השני במסמך RTL');
});

check('"+N" נפתח לרשימה של הפתקים שלא נכנסו, ומשם הם נפתחים', async () => {
  const p = runPage({ answer: list(pin('a', 'א'), pin('b', 'ב'), pin('c', 'ג')), rowWidth: 366 });
  await tick(); await tick();
  const btn = p.more().querySelector('.files-page-more');
  btn.listeners.click({ stopPropagation() {} });
  const items = p.more().querySelectorAll('.archive-card');
  eq(items.map((i) => i.getAttribute('data-note-id')).join(','), 'b,c', 'הנסתרים');
  eq(btn.getAttribute('aria-expanded'), 'true', 'aria-expanded');
  eq(El.focused === items[0], true, 'המיקוד על הראשון ברשימה');
  await items[1].listeners.click();
  await tick();
  eq(p.mgr.opened.length, 1, 'הפתק נפתח');
  eq(p.overlay.hidden, false, 'השכבה פתוחה');
});

// ─── פס הכותרות: גובה והכרזה, ולא רוחב ──────────────────────────────────

check('חלון נמוך — פס כותרות, ורוחב השורה אינו נשמר', async () => {
  const p = runPage({ answer: list(pin('a', 'א')), innerHeight: 390 });
  await tick(); await tick();
  eq(p.ids.filesPageNotes.getAttribute('data-mode'), 'strip', 'פס');
  eq(p.cards()[0]._classes.has('files-page-chip'), true, 'הווריאנט של הפס');
  eq(p.recorded.length, 0, 'לא נשמר — הרוחב נשמר רק כשמוצגים כרטיסים מלאים');
});

check('הכרזה מוצגת — פס כותרות, גם בחלון גבוה', async () => {
  const p = runPage({ answer: list(pin('a', 'א')), banner: true });
  await tick(); await tick();
  eq(p.ids.filesPageNotes.getAttribute('data-mode'), 'strip', 'פס');
});

check('חלון צר אבל גבוה — כרטיסים, ולא פס; והרוחב נשמר', async () => {
  const p = runPage({ answer: list(pin('a', 'א')), innerHeight: 900, rowWidth: 300 });
  await tick(); await tick();
  eq(p.ids.filesPageNotes.getAttribute('data-mode'), 'cards', 'כרטיסים');
  eq(p.recorded.join(), '300', 'הרוחב נשמר');
});

// ─── הפתק הפתוח ──────────────────────────────────────────────────────────

check('לחיצה על כרטיס פותחת את הפתק מעל העמוד, והתוכן inert', async () => {
  const p = runPage({ answer: list(pin('a', 'א')) });
  await tick(); await tick();
  await p.cards()[0].listeners.click();
  await tick();
  eq(p.requests.includes('/api/sticky-notes/files-page/a'), true, 'הפתק נשלף מהראוט של עמוד הקבצים');
  eq(p.mgr.opened[0].note.id, 'a', 'נמסר למנהל');
  eq(p.overlay.hidden, false, 'השכבה פתוחה');
  eq(p.main.inert, true, 'התוכן inert');
  eq(p.mgr.opts.filesPage, true, 'המנהל במצב filesPage');
});

check('פתק שכבר אינו נעוץ (404): הכרטיס יורד, והמשתמש יודע למה', async () => {
  const p = runPage({ answer: (url) => (url === '/api/sticky-notes/files-page'
    ? [200, { ok: true, notes: [pin('a', 'א'), pin('b', 'ב')], count: 2, max: 4 }] : [404, { ok: false, error: 'note_not_found' }]) });
  await tick(); await tick();
  await p.cards()[0].listeners.click();
  await tick();
  eq(p.cards().map((c) => c.getAttribute('data-note-id')).join(), 'b', 'הכרטיס ירד');
  eq(p.toasts[0].type, 'info', 'הודעה');
  eq(p.overlay.hidden, true, 'שום דבר לא נפתח');
});

check('הפתק עזב את העמוד (נמחק/לארכיון/הוסר): הכרטיס יורד, השכבה נסגרת והמיקוד עובר לשכן', async () => {
  const p = runPage({ answer: list(pin('a', 'א'), pin('b', 'ב')) });
  await tick(); await tick();
  await p.cards()[1].listeners.click();
  await tick();
  p.mgr.opts.onOverlayNoteGone('b');
  eq(p.cards().map((c) => c.getAttribute('data-note-id')).join(), 'a', 'נשאר אחד');
  eq(p.overlay.hidden, true, 'השכבה נסגרה');
  eq(p.main.inert, false, 'התוכן פעיל');
  eq(!!El.focused && El.focused.getAttribute('data-note-id'), 'a', 'המיקוד על השכן');
});

check('סגירת הפתק טוענת את הרשימה שוב — התווית נגזרת בשרת — והמיקוד חוזר לאותו כרטיס', async () => {
  let label = 'ישן';
  const p = runPage({ answer: (url) => (url === '/api/sticky-notes/files-page'
    ? [200, { ok: true, notes: [pin('a', label)], count: 1, max: 4 }] : [200, { ok: true, note: { id: 'a' } }]) });
  await tick(); await tick();
  await p.cards()[0].listeners.click();
  await tick();
  label = 'חדש';
  p.mgr.opts.onOverlayNoteClosed({ id: 'a', title: '', color: '#fff' });
  await tick(); await tick();
  eq(p.cards()[0].querySelector('.archive-card-title').textContent, 'חדש', 'התווית מהשרת');
  eq(El.focused === p.cards()[0], true, 'המיקוד על הכרטיס החדש — לא נפל ל-body');
  eq(p.requests.filter((u) => u === '/api/sticky-notes/files-page').length, 2, 'נטען פעמיים');
});

check('טעינה חוזרת שנכשלה אחרי סגירה משאירה את הכרטיסים כמו שהם', async () => {
  let fail = false;
  const p = runPage({ answer: (url) => (fail ? [500, {}] : list(pin('a', 'א'))(url)) });
  await tick(); await tick();
  fail = true;
  p.mgr.opts.onOverlayNoteClosed({ id: 'a' });
  await tick(); await tick();
  eq(p.cards().length, 1, 'הכרטיס נשאר');
  eq(p.ids.filesPageNotesError.hidden, true, 'בלי מצב שגיאה');
});

check('Escape סוגר את הפתק — אלא אם רכיב בתוכו כבר טיפל בו', async () => {
  const p = runPage({ answer: list(pin('a', 'א')) });
  await tick(); await tick();
  await p.cards()[0].listeners.click();
  await tick();
  p.docListeners.keydown({ key: 'Escape', defaultPrevented: true, preventDefault() {} });
  eq(p.mgr.closed, 0, 'רכיב בפתק טיפל');
  p.docListeners.keydown({ key: 'Escape', defaultPrevented: false, preventDefault() {} });
  eq(p.mgr.closed, 1, 'Escape רגיל סוגר');
});

(async () => {
  await Promise.all(pending);
  console.log(`${passed} עברו, ${failed} נכשלו`);
  process.exit(failed === 0 ? 0 : 1);
})();
