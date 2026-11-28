/**
 * טסטים ל-mcp_server/apps/note_view.js — הדף של תצוגת הפתק בתוך Claude (MCP App).
 *
 * הרצה:  node tests/mcp-note-view.test.js
 * (אין ברפו runner ל-JS, ולכן הקובץ עצמאי ומחזיר קוד יציאה 1 בכישלון — אותה תבנית כמו
 *  tests/md-anchors.test.js.)
 *
 * **הבדיקות מדברות עם הדף רק כמו מארח:** הודעות ``postMessage`` נכנסות, והודעות שהדף שולח
 * ל-``window.parent``. אין כאן גישה לפונקציה פנימית — הדף אינו חושף כלום — ולכן מה שנבדק הוא
 * בדיוק הממשק ש-Claude רואה. מה שהדפדפן אוכף (בדיקת המקור מול חלון אמיתי, CSP, ``dir="auto"``,
 * גדלים) נבדק בדפדפן אמיתי ב-``tests/test_mcp_note_view_browser.py``; כאן — הלוגיקה.
 *
 * ה-DOM כאן מינימלי ומזויף בכוונה: הוא רושם כל ``createElement``, ולכן אפשר לוודא שתוכן הפתק
 * לא יצר אף אלמנט (``<script>`` שנכתב בפתק נשאר טקסט).
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'mcp_server', 'apps', 'note_view.js');
// **התקרה ש-``content_too_long`` נושא ב-``max``** — ``sticky_notes_target.MAX_NOTE_CHARS``, נקראת מהמקור כדי
// שהתשובה המדומה תהיה זו שהשרת שולח, ולא עותק של מספר שנשאר מאחור בהגדלה הבאה של התקרה.
const SERVER_MAX_NOTE_CHARS = Number(/^MAX_NOTE_CHARS\s*=\s*([\d_]+)/m
  .exec(fs.readFileSync(path.join(__dirname, '..', 'sticky_notes_target.py'), 'utf8'))[1].replace(/_/g, ''));

let passed = 0;
let failed = 0;

function check(name, condition, actual) {
  if (condition) {
    passed += 1;
    console.log('  ✅', name);
  } else {
    failed += 1;
    console.log('  ❌', name, actual !== undefined ? '\n     actual: ' + JSON.stringify(actual) : '');
  }
}

class FakeStyle {
  constructor() { this.props = {}; this.height = ''; this.backgroundColor = ''; this.colorScheme = ''; }
  setProperty(key, value) { this.props[key] = value; }
  removeProperty(key) { delete this.props[key]; }
}

/** ``classList`` מעל ``className`` — מה שהדף קורא (``toggle``) ומה שהבדיקות שואלות (``contains``). */
class FakeClassList {
  constructor(el) { this.el = el; }
  list() { return this.el.className.split(/\s+/).filter(Boolean); }
  contains(name) { return this.list().indexOf(name) !== -1; }
  toggle(name, force) {
    const has = this.contains(name);
    const want = force === undefined ? !has : !!force;
    if (want && !has) this.el.className = this.list().concat(name).join(' ');
    if (!want && has) this.el.className = this.list().filter((c) => c !== name).join(' ');
    return want;
  }
}

class FakeElement {
  constructor(tag) {
    this.tagName = tag.toUpperCase();
    this.children = [];
    this.attrs = {};
    this.className = '';
    this.id = '';
    this.style = new FakeStyle();
    this.classList = new FakeClassList(this);
    this._text = '';
    this.listeners = {};
    this.hidden = false;
    this.disabled = false;
    // מדדי גלילה — הבדיקות מציבות אותם ביד; הפריסה האמיתית נבדקת בכרום.
    this.scrollTop = 0;
    this.clientHeight = 0;
    this.scrollHeight = 0;
    this.offsetHeight = 0;
    this.scrolls = [];
    // תיבת הטקסט של העורך: ערך, סמן, ופוקוס.
    this.dataset = {};
    this.value = '';
    this.selection = null;
    this.parentNode = null;
  }
  /** ``selectionAtFocus`` — איפה היה הסמן ברגע הפוקוס: ``focus()`` הוא שגולל את התיבה אל הסמן. */
  focus() { FakeElement.focused = this; this.selectionAtFocus = this.selection; this.classAtFocus = this.className; }
  setSelectionRange(start, end) { this.selection = [start, end]; }
  get firstChild() { return this.children[0] || null; }
  get nextSibling() {
    if (!this.parentNode) return null;
    const kids = this.parentNode.children;
    return kids[kids.indexOf(this) + 1] || null;
  }
  insertBefore(child, ref) {
    const at = ref ? this.children.indexOf(ref) : -1;
    if (at === -1) this.children.push(child);
    else this.children.splice(at, 0, child);
    child.parentNode = this;
    return child;
  }
  removeChild(child) {
    const at = this.children.indexOf(child);
    if (at !== -1) this.children.splice(at, 1);
    child.parentNode = null;
    return child;
  }
  /** ``querySelector`` ל-``.class`` בלבד — מה שהדף שואל. */
  querySelector(selector) {
    const cls = selector.replace(/^\./, '');
    for (const el of this.walk()) if (el !== this && el.className.split(/\s+/).indexOf(cls) !== -1) return el;
    return null;
  }
  /** ``querySelectorAll`` ל-``.class`` בלבד, בסדר המסמך — מה שהדף שואל (השורות של קטע מסומן). */
  querySelectorAll(selector) {
    const cls = selector.replace(/^\./, '');
    return [...this.walk()].filter((el) => el !== this && el.className.split(/\s+/).indexOf(cls) !== -1);
  }
  addEventListener(type, fn) { (this.listeners[type] = this.listeners[type] || []).push(fn); }
  dispatch(type, extra) {
    const event = Object.assign({ type, target: this, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } }, extra || {});
    for (const fn of this.listeners[type] || []) fn(event);
    return event;
  }
  scrollBy(options) { this.scrolls.push(options); this.scrollTop += options.top; }
  set textContent(value) { this.children = []; this._text = String(value); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  appendChild(child) { this.children.push(child); child.parentNode = this; return child; }
  /** ``closest`` לבורר בצורה ``tag.class`` או ``.class`` — מה שהדף שואל. */
  closest(selector) {
    const m = /^([a-z]*)\.([\w-]+)$/i.exec(selector);
    for (let el = this; el; el = el.parentNode) {
      if (!el.tagName) continue;
      if (m && (!m[1] || el.tagName === m[1].toUpperCase()) && el.className.split(/\s+/).indexOf(m[2]) !== -1) return el;
    }
    return null;
  }
  setAttribute(key, value) { this.attrs[key] = String(value); if (key === 'id') this.id = String(value); }
  getAttribute(key) { return Object.prototype.hasOwnProperty.call(this.attrs, key) ? this.attrs[key] : null; }
  getBoundingClientRect() { return { height: 240, width: 600 }; }
  *walk() { yield this; for (const c of this.children) yield* c.walk(); }
}

/**
 * טוען את הדף בסנדבוקס, עם מארח מזויף. ``opts.raf`` / ``opts.resizeObserver`` מדליקים את
 * היכולות האלה; בלעדיהן הדף הולך במסלול "אין יכולת" שלו.
 */
function load(opts = {}) {
  const created = [];
  const html = new FakeElement('html');
  const head = new FakeElement('head');
  const body = new FakeElement('body');
  const main = new FakeElement('main');
  main.setAttribute('id', 'ck-note-root');
  body.appendChild(main);
  html.appendChild(head);
  html.appendChild(body);
  const document = {
    documentElement: html,
    head,
    body,
    createElement(tag) { created.push(tag); return new FakeElement(tag); },
    /** הפוקוס — ``focus()`` של אלמנט מזויף רושם אותו כאן. */
    get activeElement() { return FakeElement.focused || null; },
    getElementById(id) {
      for (const el of html.walk()) if (el.id === id) return el;
      return null;
    },
  };
  const sent = [];
  const parent = { postMessage(message, target) { sent.push({ message: JSON.parse(JSON.stringify(message)), target }); } };
  const listeners = [];
  const resizeListeners = [];
  const timers = [];
  const observed = [];
  // הגדלת הטקסט של המנוע (WebView של אנדרואיד מכפיל כל גופן בגודל הגופן של המערכת): הגודל
  // המחושב הוא הגודל שהאלמנט ביקש כפול ``zoom.text``, וכפול ``text-size-adjust`` כשהוא אינו
  // ``auto`` — של האלמנט עצמו, או שירש מ-``html`` — באותה מכפלה, כמו ב-``FontBuilder`` של Blink.
  // ``zoom.tsa: false`` — מנוע שאינו מכבד את התכונה (WebView ישן). ``zoom.raw`` מחליף את התשובה
  // כולה — לבדוק ערך שאינו מספר.
  const zoom = { text: opts.textZoom || 1, raw: null, tsa: opts.tsa !== false };
  // **המסך** (``screen``) — ``opts.screen`` לטלפון; ברירת המחדל היא מסך של טאבלט או מחשב.
  // **השטח הגלוי** (``visualViewport``) — ``opts.visualViewport`` מדליק דמה שהבדיקה מזיזה ב-``host.vv``.
  const vvListeners = {};
  const vv = opts.visualViewport ? {
    height: 600, offsetTop: 0, pageTop: 0, scale: 1,
    addEventListener(type, fn) { (vvListeners[type] = vvListeners[type] || []).push(fn); },
    move(height, offsetTop) {
      this.height = height;
      this.offsetTop = offsetTop;
      for (const fn of (vvListeners.resize || []).concat(vvListeners.scroll || [])) fn({ type: 'resize' });
    },
  } : undefined;
  const win = {
    document,
    parent,
    innerWidth: 600,
    screen: opts.screen === undefined ? { width: 1280, height: 800 } : opts.screen,
    visualViewport: vv,
    getComputedStyle(el) {
      if (zoom.raw !== null) return { fontSize: zoom.raw };
      let factor = zoom.text;
      const own = el.style.props['text-size-adjust'];
      const adjust = own !== undefined ? own : html.style.props['text-size-adjust'];
      if (zoom.tsa && adjust !== undefined && adjust !== 'auto') factor *= parseFloat(adjust) / 100;
      return { fontSize: `${parseFloat(el.style.fontSize || '16') * factor}px` };
    },
    addEventListener(type, fn) {
      if (type === 'message') listeners.push(fn);
      if (type === 'resize') resizeListeners.push(fn);
    },
    setTimeout(fn, ms) { timers.push({ fn, ms, cleared: false }); return timers.length; },
    clearTimeout(handle) { if (timers[handle - 1]) timers[handle - 1].cleared = true; },
  };
  // **סוג המצביע** — ``opts.coarse`` מדליק ``matchMedia`` שעונה על ``(pointer: coarse)``: ``true``
  // למסך מגע, ``false`` למחשב. בלעדיו אין ``matchMedia`` בכלל, כמו בבדיקות שקדמו לו.
  if (opts.coarse !== undefined) win.matchMedia = (query) => ({ media: query, matches: query === '(pointer: coarse)' && opts.coarse === true });
  const unobserved = [];
  if (opts.resizeObserver) {
    win.ResizeObserver = class {
      constructor(cb) { this.cb = cb; }
      observe(el) { observed.push(el); }
      unobserve(el) { unobserved.push(el); }
    };
  }
  // **דמה של מנוע התצוגה**, בחוזה שלו: ``render(container, text, options)`` מנקה את המכל ובונה אותו
  // מהטקסט, רק עם ``createElement`` ו-``textContent``. שורה שכולה ``[תווית](כתובת)`` הופכת לקישור,
  // ושורה ``::: details כותרת`` לכותרת של בלוק מתקפל, כמו במנוע. ``options.sourceOffsets`` מציב על כל
  // שורה את ההיסט שלה, ו-``isViewControl`` / ``sourceOffsetAt`` עונים כמו של המנוע. המנוע האמיתי
  // נבדק בדפדפן (``tests/test_mcp_note_view_browser.py``) ובבדיקות שלו; כאן — מה שהדף עושה סביבו.
  // ``opts.engineOmit`` — מנוע שחסר בו חלק מהחוזה (דף שנבנה עם מנוע אחר).
  const mdCalls = [];
  const detailsCalls = [];
  // **דמה של מודול ההדגשה** (``utils/text-highlight.js``), בחוזה שלו: ``highlightWithin`` מנקה הדגשות קודמות
  // ומחזיר עטיפה לכל מופע (כאן — לפי ``_text`` של כל אלמנט, בלי הבדל רישיות), ``hitsWithin`` מוצא אותן מהעץ,
  // ``setActive`` מסמן אחת. הכללים עצמם (רצפים, דילוג, גלילה) נבדקים על המודול האמיתי — בטסטים שלו ובדפדפן.
  // ``opts.highlighterOmit`` — מודול שחסר בו חלק מהחוזה; ``opts.noHighlighter`` — בלי המודול.
  const hl = { calls: [] };
  if (!opts.noHighlighter) {
    const highlighter = {
      highlightWithin(root, term, o) {
        hl.calls.push({ fn: 'highlightWithin', root, term, opts: o });
        this.clearHighlights(root, o.className);
        const heads = [];
        for (const el of [...root.walk()]) {
          if (el === root || el.isHit || !el._text) continue;
          const n = el._text.toLowerCase().split(String(term).toLowerCase()).length - 1;
          for (let i = 0; i < n; i += 1) {
            const w = document.createElement('span');
            w.className = o.className;
            w.isHit = true;
            el.appendChild(w);
            heads.push(w);
          }
        }
        return heads;
      },
      hitsWithin(root, cls) { return [...root.walk()].filter((el) => el.isHit && el.className.split(/\s+/).indexOf(cls) !== -1); },
      setActive(root, cls, hit) {
        hl.calls.push({ fn: 'setActive', root, hit });
        for (const el of this.hitsWithin(root, cls)) el.classList.toggle('is-active', el === hit);
        return hit ? [hit] : [];
      },
      clearHighlights(root, cls) {
        hl.calls.push({ fn: 'clearHighlights', root });
        const hits = this.hitsWithin(root, cls);
        for (const el of hits) el.parentNode.removeChild(el);
        return hits.length;
      },
      scrollIntoViewWithin(root, hit) { hl.calls.push({ fn: 'scrollIntoViewWithin', root, hit }); },
      isRendered() { return true; },
    };
    for (const key of opts.highlighterOmit || []) delete highlighter[key];
    win.TextHighlight = Object.freeze(highlighter);
  }
  if (!opts.noEngine) {
    const engine = {
      MD_SAFE_LINK: /^https?:\/\//i,
      /** כמו של המנוע: ``svg`` עם צורה לכל פריט — כאן בלי צמתי SVG אמיתיים. */
      buildStrokeIcon(shapes) {
        const svg = document.createElement('svg');
        svg.className = 'ck-test-icon';
        svg.shapes = shapes;
        return svg;
      },
      isViewControl(t) {
        return !!t && (t.classList.contains('sticky-task-box') || !!t.closest('a.sticky-md-link')
          || !!t.closest('summary.sticky-md-details-summary'));
      },
      sourceOffsetAt(t) {
        const row = t ? t.closest('.sticky-task-line') : null;
        const offset = row ? parseInt(row.dataset.charOffset, 10) : NaN;
        return Number.isFinite(offset) ? offset : null;
      },
      GENERATED_TEXT_CLASS: 'sticky-md-generated',
      /** נרשם בלבד — הפתיחה עצמה (מה נפתח ומה לא) נבדקת על המנוע האמיתי, בדפדפן. */
      openDetailsAround(node, root) {
        detailsCalls.push({ node, root });
        return [];
      },
      render(container, text, options) {
        mdCalls.push({ container, text, options });
        container.textContent = '';
        let offset = 0;
        for (const line of String(text).split('\n')) {
          const isSummary = /^::: details /.test(line);
          const row = document.createElement(isSummary ? 'summary' : 'div');
          row.className = isSummary ? 'sticky-task-line sticky-md-details-summary' : 'sticky-task-line';
          if (options && options.sourceOffsets) row.dataset.charOffset = String(offset);
          offset += line.length + 1;
          const link = /^\[([^\]]+)\]\((\S+)\)$/.exec(line);
          if (link) {
            const a = document.createElement('a');
            a.className = 'sticky-md-link';
            a.setAttribute('href', link[2]);
            a.textContent = link[1];
            row.appendChild(a);
          } else {
            row.textContent = line;
          }
          container.appendChild(row);
        }
        return container;
      },
    };
    for (const key of opts.engineOmit || []) delete engine[key];
    win.StickyMdRender = Object.freeze(engine);
  }
  const sandbox = { window: win, JSON, Object, Array, Math, String, parseInt, isFinite };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  const host = {
    win, document, main, sent, created, timers, observed, unobserved, parent, zoom, mdCalls, vv, hl, detailsCalls,
    deliver(data, source = parent) { for (const fn of listeners) fn({ source, data }); },
    methods() { return sent.map((s) => s.message.method || (s.message.error ? 'error' : 'result')); },
    last(method) { return [...sent].reverse().find((s) => s.message.method === method); },
    /** הזמן עובר ב-``ms``: כל טיימר של ``ms`` שקיים **עכשיו** יורה, פעם אחת, כמו בדפדפן. טיימר שנוצר בתוך
     *  אחד מהם (למשל תקרת הזמן של הקריאה שאחרי שמירה שלא נענתה) עוד לא הגיע זמנו. */
    fire(ms) {
      for (const t of timers.slice()) {
        if (t.ms === ms && !t.cleared) { t.cleared = true; t.fn(); }
      }
    },
    /** המארח משנה את המסגרת — מה שהדפדפן מודיע עליו ב-``resize`` של החלון שבתוכה. */
    resize() { for (const fn of resizeListeners) fn({ type: 'resize' }); },
    find(cls) {
      for (const el of html.walk()) if (el.className.split(/\s+/).indexOf(cls) !== -1) return el;
      return null;
    },
    findAll(cls) { return [...html.walk()].filter((el) => el.className.split(/\s+/).indexOf(cls) !== -1); },
    sizes() { return sent.filter((s) => s.message.method === 'ui/notifications/size-changed'); },
  };
  return host;
}

function initialize(host, hostContext, hostCapabilities) {
  const init = host.sent[0].message;
  host.deliver({ jsonrpc: '2.0', id: init.id, result: { protocolVersion: '2026-01-26', hostInfo: { name: 'test-host', version: '1' },
    hostCapabilities: hostCapabilities === undefined ? {} : hostCapabilities, hostContext: hostContext || {} } });
}

function toolResult(answer, extra = {}) {
  return { jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: { content: [{ type: 'text', text: JSON.stringify(answer, null, 2) }], ...extra } };
}

const NOTE = {
  ok: true,
  note: { id: 'a'.repeat(24), title: 'רשימת קניות', content: '# כותרת\n\nEnglish line\nשורה בעברית', color: '#ffeddb', color_id: 'orange_light' },
  target: 'board',
  board_id: 'b'.repeat(24),
};

console.log('\nלחיצת היד הראשונה');
{
  const host = load();
  const first = host.sent[0];
  check('הודעה ראשונה היא ui/initialize', first && first.message.method === 'ui/initialize', first);
  check('נשלחת ל-"*" כמו PostMessageTransport.send', first && first.target === '*', first && first.target);
  check('הפרמטרים הם בדיוק appInfo, appCapabilities ו-protocolVersion',
    JSON.stringify(Object.keys(first.message.params).sort()) === JSON.stringify(['appCapabilities', 'appInfo', 'protocolVersion']),
    first.message.params);
  check('protocolVersion הוא של המפרט היציב', first.message.params.protocolVersion === '2026-01-26', first.message.params.protocolVersion);
  check('הדף מצהיר על inline ועל fullscreen', JSON.stringify(first.message.params.appCapabilities) === JSON.stringify({ availableDisplayModes: ['inline', 'fullscreen'] }), first.message.params.appCapabilities);
  check('לפני תשובה — שום הודעה נוספת', host.sent.length === 1, host.methods());
  initialize(host);
  const methods = host.methods();
  check('אחרי התשובה: initialized ואחריו size-changed', methods[1] === 'ui/notifications/initialized' && methods[2] === 'ui/notifications/size-changed', methods);
  check('initialized נשלח בלי params, כמו ב-SDK', !('params' in host.sent[1].message), host.sent[1].message);
  const size = host.sent[2].message.params;
  check('size-changed נושא רוחב וגובה במספרים שלמים', size.width === 600 && size.height === 240, size);
}

console.log('\nבדיקת המקור של ההודעה');
{
  const host = load();
  const init = host.sent[0].message;
  const stranger = { postMessage() {} };
  host.deliver({ jsonrpc: '2.0', id: init.id, result: { hostContext: {} } }, stranger);
  check('תשובה ממקור זר אינה מתקבלת — initialized לא נשלח', host.sent.length === 1, host.methods());
  host.deliver({ jsonrpc: '2.0', method: 'ui/notifications/tool-result', params: toolResult(NOTE).params }, stranger);
  check('תוצאה ממקור זר אינה מוצגת', host.main.textContent.indexOf('רשימת קניות') === -1, host.main.textContent);
  host.deliver('not an object');
  host.deliver({ jsonrpc: '1.0', id: init.id, result: {} });
  check('הודעה שאינה JSON-RPC 2.0 מהמארח נזרקת', host.sent.length === 1, host.methods());
}

console.log('\nרינדור הפתק');
{
  const host = load();
  initialize(host);
  host.deliver({ jsonrpc: '2.0', method: 'ui/notifications/tool-input', params: { arguments: { note_id: 'x' } } });
  host.deliver(toolResult(NOTE));
  const paper = host.main.children[0];
  check('הפתק נבנה כ-article.ck-paper', paper && paper.tagName === 'ARTICLE' && paper.className.indexOf('ck-paper') === 0, paper && paper.className);
  check('הצבע של הפתק על הנייר', paper.style.backgroundColor === '#ffeddb', paper.style.backgroundColor);
  check('has-note-color כשהצבע תקין', paper.className.indexOf('has-note-color') !== -1, paper.className);
  check('הנייר נושא sticky-note — המחלקה שהעיצוב המשותף תחום בה', paper.className.split(' ').indexOf('sticky-note') !== -1, paper.className);
  const head = paper.children[0];
  check('שורת הראש ראשונה בנייר, והכותרת בתוכה', head.className === 'ck-head' && head.children.length === 1, [head.className, head.children.length]);
  const title = head.children[0];
  check('הכותרת ב-h1, בלי dir — יורשת rtl כמו שם הפתק בוובאפ', title.tagName === 'H1' && title.getAttribute('dir') === null && title.textContent === 'רשימת קניות', [title.getAttribute('dir'), title.textContent]);
  const body = paper.children[1];
  const content = body.children[0];
  check('ck-body עוטף ck-content אחד', body.className === 'ck-body' && body.children.length === 1 && content.className === 'ck-content',
    [body.className, body.children.map((c) => c.className)]);
  check('המנוע נקרא פעם אחת, על ck-content, עם הטקסט של הפתק כמו שהוא',
    host.mdCalls.length === 1 && host.mdCalls[0].container === content && host.mdCalls[0].text === NOTE.note.content,
    host.mdCalls.map((c) => [c.container.className, c.text]));
  check('מה שהמנוע בנה הוא התוכן', content.children.length === 4 && content.children[0].className === 'sticky-task-line',
    content.children.map((c) => c.className));
  check('אחרי רינדור — מדידת גודל נוספת', host.methods().filter((m) => m === 'ui/notifications/size-changed').length >= 1, host.methods());
}

console.log('\nתוכן לא מהימן נשאר טקסט');
{
  const host = load();
  initialize(host);
  const evil = '<script>window.pwned=1</script><img src=x onerror=alert(1)>';
  host.deliver(toolResult({ ok: true, note: { title: evil, content: evil + '\n<b>bold</b>', color: '#ffffcc' } }));
  const tags = new Set(host.created.map((t) => t.toLowerCase()));
  check('לא נוצר אף script / img / b', !tags.has('script') && !tags.has('img') && !tags.has('b'), [...tags]);
  check('הטקסט מוצג כמו שהוא', host.main.textContent.indexOf(evil) !== -1, host.main.textContent);
}

console.log('\nצבע שאינו בצורה של השרת');
{
  for (const color of ['red', '#fff', 'url(x)', '#ffffcc; background:url(//x)', 12, null]) {
    const host = load();
    initialize(host);
    host.deliver(toolResult({ ok: true, note: { title: null, content: 'x', color } }));
    const paper = host.main.children[0];
    check(`צבע ${JSON.stringify(color)} אינו מוצב`, paper.style.backgroundColor === '' && paper.className === 'ck-paper sticky-note', [paper.style.backgroundColor, paper.className]);
  }
}

console.log('\nתשובות שאינן פתק');
{
  const cases = [
    ['not_found', { ok: false, error: 'not_found' }, 'הפתק לא נמצא'],
    ['rate_limited', { ok: false, error: 'rate_limited', retry_after: 3 }, 'יותר מדי קריאות'],
    ['קוד לא מוכר', { ok: false, error: 'brand_new_code' }, '(brand_new_code)'],
  ];
  for (const [name, answer, expected] of cases) {
    const host = load();
    initialize(host);
    host.deliver(toolResult(answer));
    check(`${name}: הודעה ברורה`, host.main.textContent.indexOf(expected) !== -1, host.main.textContent);
    check(`${name}: מסומנת כשגיאה`, host.main.children[0].className === 'ck-status is-error', host.main.children[0].className);
  }
  const host = load();
  initialize(host);
  host.deliver(toolResult({ ok: false, error: '<b>x</b> not a code' }));
  check('קוד שאינו בצורה של קוד אינו מוצג', host.main.textContent.indexOf('<b>') === -1 && host.main.textContent.indexOf('לא הצלחתי') !== -1, host.main.textContent);
  for (const params of [null, 'x', { content: 'x' }, { content: [] }, { content: [{ type: 'image' }] },
    { content: [{ type: 'text', text: 'not json' }] }, { content: [{ type: 'text', text: '[1,2]' }] },
    { isError: true, content: [{ type: 'text', text: JSON.stringify(NOTE) }] },
    { content: [{ type: 'text', text: JSON.stringify({ ok: true, note: { content: 5 } }) }] }]) {
    const h = load();
    initialize(h);
    let threw = false;
    try { h.deliver({ jsonrpc: '2.0', method: 'ui/notifications/tool-result', params }); } catch (_) { threw = true; }
    check(`צורה ${JSON.stringify(params).slice(0, 60)}: לא זורק ומציג הודעה`, !threw && h.main.textContent.indexOf('לא הצלחתי') !== -1, h.main.textContent);
  }
}

console.log('\nפתק ריק');
{
  const host = load();
  initialize(host);
  host.deliver(toolResult({ ok: true, note: { title: '', content: '', color: '#ffffcc' } }));
  const paper = host.main.children[0];
  check('בלי כותרת ריקה — שורת הראש ריקה', paper.children[0].className === 'ck-head' && paper.children[0].children.length === 0,
    paper.children.map((c) => c.className));
  check('הודעת "הפתק ריק"', host.main.textContent.indexOf('הפתק ריק') !== -1, host.main.textContent);
}

console.log('\nבקשות מהמארח');
{
  const host = load();
  initialize(host);
  host.deliver({ jsonrpc: '2.0', id: 77, method: 'ping', params: {} });
  const pong = host.sent[host.sent.length - 1].message;
  check('ping נענה {} עם אותו id', pong.id === 77 && JSON.stringify(pong.result) === '{}', pong);
  host.deliver({ jsonrpc: '2.0', id: 'td', method: 'ui/resource-teardown', params: { reason: 'x' } });
  const td = host.sent[host.sent.length - 1].message;
  check('resource-teardown נענה {}', td.id === 'td' && JSON.stringify(td.result) === '{}', td);
  host.deliver({ jsonrpc: '2.0', id: 9, method: 'tools/call', params: {} });
  const err = host.sent[host.sent.length - 1].message;
  check('בקשה לא מוכרת: -32601', err.id === 9 && err.error && err.error.code === -32601, err);
}

console.log('\nערכת הנושא של המארח');
{
  const host = load();
  initialize(host, { theme: 'dark', styles: { variables: { '--color-text-primary': '#fafafa', 'color': 'red', '--font-sans': 7 }, css: { fonts: '@font-face{font-family:X;src:url(a)}' } } });
  const docEl = host.document.documentElement;
  check('data-theme ו-color-scheme לפי המארח', docEl.getAttribute('data-theme') === 'dark' && docEl.style.colorScheme === 'dark', [docEl.getAttribute('data-theme'), docEl.style.colorScheme]);
  check('רק מפתחות שמתחילים ב-"--" ועם ערך מחרוזת', JSON.stringify(docEl.style.props) === JSON.stringify({ '--color-text-primary': '#fafafa' }), docEl.style.props);
  const fonts = host.document.getElementById('ck-host-fonts');
  check('הגופנים נכנסים פעם אחת כ-style', fonts && fonts.tagName === 'STYLE' && fonts.textContent.indexOf('@font-face') === 0, fonts && fonts.textContent);
  host.deliver({ jsonrpc: '2.0', method: 'ui/notifications/host-context-changed', params: { theme: 'light', styles: { css: { fonts: 'second' } } } });
  check('host-context-changed מעדכן את הערכה', docEl.getAttribute('data-theme') === 'light', docEl.getAttribute('data-theme'));
  check('ובלי style שני לגופנים', host.document.head.children.filter((c) => c.id === 'ck-host-fonts').length === 1, host.document.head.children.length);
  host.deliver({ jsonrpc: '2.0', method: 'ui/notifications/host-context-changed', params: { theme: 'neon' } });
  check('ערכה שאינה light/dark אינה מוצבת', docEl.getAttribute('data-theme') === 'light', docEl.getAttribute('data-theme'));
}

console.log('\nתקרות הזמן');
{
  const host = load();
  host.fire(10000);
  check('בלי תשובה ל-initialize — הודעה במקום "טוען"', host.main.textContent.indexOf('לא התקבלה תשובה') !== -1, host.main.textContent);
  initialize(host);
  check('תשובה שמגיעה אחרי התקרה עדיין מחברת', host.methods().indexOf('ui/notifications/initialized') !== -1, host.methods());
  host.fire(120000);
  check('בלי תוצאה — הודעה שהפתק לא הגיע', host.main.textContent.indexOf('הפתק לא הגיע') !== -1, host.main.textContent);
  host.deliver(toolResult(NOTE));
  check('תוצאה מאוחרת עדיין מוצגת', host.main.textContent.indexOf('רשימת קניות') !== -1, host.main.textContent);

  const fast = load();
  initialize(fast);
  fast.deliver(toolResult(NOTE));
  fast.fire(120000);
  check('אחרי רינדור התקרה אינה דורסת את הפתק', fast.main.textContent.indexOf('רשימת קניות') !== -1, fast.main.textContent);

  const refused = load();
  initialize(refused);
  refused.deliver(toolResult({ ok: false, error: 'not_found' }));
  refused.fire(120000);
  check('אחרי תשובת שגיאה התקרה אינה דורסת את ההודעה', refused.main.textContent.indexOf('הפתק לא נמצא') !== -1, refused.main.textContent);

  const early = load();
  early.deliver(toolResult(NOTE));
  initialize(early);
  early.fire(120000);
  check('תוצאה שהגיעה לפני initialize (מארח שלא מקפיד) אינה נדרסת', early.main.textContent.indexOf('רשימת קניות') !== -1, early.main.textContent);

  const cancelled = load();
  initialize(cancelled);
  cancelled.deliver({ jsonrpc: '2.0', method: 'ui/notifications/tool-cancelled', params: { reason: 'user' } });
  cancelled.fire(120000);
  check('אחרי ביטול התקרה אינה דורסת את "בוטלה"', cancelled.main.textContent.indexOf('בוטלה') !== -1, cancelled.main.textContent);
}

console.log('\nביטול');
{
  const host = load();
  initialize(host);
  host.deliver({ jsonrpc: '2.0', method: 'ui/notifications/tool-cancelled', params: { reason: 'user' } });
  check('ביטול לפני תוצאה — הודעה', host.main.textContent.indexOf('בוטלה') !== -1, host.main.textContent);
}

console.log('\nמדידת גודל עם ResizeObserver');
{
  const host = load({ resizeObserver: true });
  initialize(host);
  check('צופה ב-html וב-body, כמו ה-SDK', host.observed.length === 2 && host.observed[0].tagName === 'HTML' && host.observed[1].tagName === 'BODY', host.observed.map((e) => e.tagName));
  const before = host.methods().filter((m) => m === 'ui/notifications/size-changed').length;
  host.deliver(toolResult(NOTE));
  const after = host.methods().filter((m) => m === 'ui/notifications/size-changed').length;
  check('גודל שלא השתנה אינו נשלח שוב', after === before, [before, after]);
}

function hostContextChanged(params) {
  return { jsonrpc: '2.0', method: 'ui/notifications/host-context-changed', params };
}

console.log('\nהמסגרת מהמארח — containerDimensions');
{
  const host = load();
  initialize(host, { containerDimensions: { width: 600, maxHeight: 500 } });
  const docEl = host.document.documentElement;
  check('maxHeight נכנס ל---ck-host-max בפיקסלים', docEl.style.props['--ck-host-max'] === '500px', docEl.style.props);
  check('בלי height — אין ck-fill', !docEl.classList.contains('ck-fill'), docEl.className);
  host.deliver(hostContextChanged({ containerDimensions: { width: 800, height: 600 } }));
  check('height קבוע — ck-fill, ובלי תקרה', docEl.classList.contains('ck-fill') && !('--ck-host-max' in docEl.style.props), [docEl.className, docEl.style.props]);
  host.deliver(hostContextChanged({ containerDimensions: { width: 600, maxHeight: 450 } }));
  check('חזרה למסגרת גמישה — ck-fill יורד והתקרה החדשה נכנסת',
    !docEl.classList.contains('ck-fill') && docEl.style.props['--ck-host-max'] === '450px', [docEl.className, docEl.style.props]);
  check('בתוך השיחה — בלי ck-expanded', !docEl.classList.contains('ck-expanded'), docEl.className);
  host.deliver(hostContextChanged({ displayMode: 'fullscreen', containerDimensions: { width: 800, maxHeight: 6000 } }));
  check('מסך מלא בגובה גמיש — ck-expanded, עם התקרה של המארח',
    docEl.classList.contains('ck-expanded') && !docEl.classList.contains('ck-fill') && docEl.style.props['--ck-host-max'] === '6000px',
    [docEl.className, docEl.style.props]);
  host.deliver(hostContextChanged({ containerDimensions: { width: 800, height: 600 } }));
  check('מסך מלא בגובה קבוע — ck-fill בלבד', docEl.classList.contains('ck-fill') && !docEl.classList.contains('ck-expanded'), docEl.className);
  host.deliver(hostContextChanged({ displayMode: 'inline', containerDimensions: { width: 600, maxHeight: 450 } }));
  check('חזרה לשיחה — שתי המחלקות יורדות', !docEl.classList.contains('ck-fill') && !docEl.classList.contains('ck-expanded'), docEl.className);
}
{
  // הערכים עוברים בלי JSON, כמו ב-postMessage, ולכן גם NaN ו-Infinity מגיעים לדף.
  const bad = ['500', -1, 0, null, Infinity, NaN, {}, [500], true];
  for (const value of bad) {
    const host = load();
    initialize(host, { containerDimensions: { width: 600, maxHeight: value, height: value } });
    const docEl = host.document.documentElement;
    check(`ערך פגום (${Array.isArray(value) ? '[500]' : String(value)}) — לא נכנס ל-CSS`,
      !('--ck-host-max' in docEl.style.props) && !docEl.classList.contains('ck-fill'), [docEl.className, docEl.style.props]);
  }
  const host = load();
  initialize(host, { containerDimensions: 'tall' });
  check('containerDimensions שאינו אובייקט — מתעלמים', !('--ck-host-max' in host.document.documentElement.style.props), host.document.documentElement.style.props);
}

console.log('\nעדכון חלקי של ההקשר מתמזג');
{
  const host = load();
  initialize(host, { containerDimensions: { width: 600, maxHeight: 500 }, availableDisplayModes: ['inline', 'fullscreen'], displayMode: 'inline' });
  host.deliver(toolResult(NOTE));
  host.deliver(hostContextChanged({ theme: 'dark' }));
  const docEl = host.document.documentElement;
  check('הודעה על ערכה בלבד שומרת את התקרה', docEl.style.props['--ck-host-max'] === '500px', docEl.style.props);
  check('ואת "מסך מלא"', host.find('ck-expand').hidden === false, host.find('ck-expand').hidden);
  check('והערכה עצמה חלה', docEl.getAttribute('data-theme') === 'dark', docEl.getAttribute('data-theme'));
}

console.log('\nשוליים בטוחים');
{
  const host = load();
  initialize(host, { safeAreaInsets: { top: 0, right: 12, bottom: 48, left: -3 } });
  const props = host.document.documentElement.style.props;
  check('0 נכנס — זה ערך תקין', props['--ck-safe-top'] === '0px', props);
  check('ימין ומטה נכנסים בפיקסלים', props['--ck-safe-right'] === '12px' && props['--ck-safe-bottom'] === '48px', props);
  check('שלילי נזרק', !('--ck-safe-left' in props), props);
  host.deliver(hostContextChanged({ safeAreaInsets: { top: 0, right: 0, bottom: 0, left: 0 } }));
  check('עדכון מחליף את הקודם', props['--ck-safe-bottom'] === '0px' && props['--ck-safe-left'] === '0px', props);
}

console.log('\nכפתור "מסך מלא"');
{
  const host = load();
  initialize(host, { availableDisplayModes: ['inline'] });
  host.deliver(toolResult(NOTE));
  check('המארח מונה inline בלבד — אין כפתור', host.find('ck-expand').hidden === true, host.find('ck-expand').hidden);
  host.find('ck-expand').dispatch('click');
  check('ולחיצה (שלא אמורה להיות אפשרית) אינה שולחת בקשה', !host.last('ui/request-display-mode'), host.methods());
}
{
  const host = load();
  initialize(host, {});
  host.deliver(toolResult(NOTE));
  check('המארח לא מונה מצבים בכלל — אין כפתור', host.find('ck-expand').hidden === true, host.find('ck-expand').hidden);
}
{
  const host = load();
  initialize(host, { availableDisplayModes: ['inline', 'fullscreen'], displayMode: 'inline' });
  host.deliver(toolResult(NOTE));
  const expand = host.find('ck-expand');
  check('המארח מונה fullscreen — הכפתור מוצג', expand.hidden === false, expand.hidden);
  check('והשורה שלו מוצגת גם כשהפתק קצר', host.find('ck-controls').hidden === false, host.find('ck-controls').hidden);
  expand.dispatch('click');
  const req = host.last('ui/request-display-mode');
  check('לחיצה שולחת ui/request-display-mode עם mode: fullscreen',
    req && JSON.stringify(req.message.params) === JSON.stringify({ mode: 'fullscreen' }) && req.message.id !== undefined, req && req.message);
  host.deliver({ jsonrpc: '2.0', id: req.message.id, result: { mode: 'inline' } });
  check('המארח סירב (החזיר inline) — הכפתור נשאר', expand.hidden === false, expand.hidden);
  expand.dispatch('click');
  const err = host.last('ui/request-display-mode');
  host.deliver({ jsonrpc: '2.0', id: err.message.id, error: { code: -32000, message: 'nope' } });
  check('שגיאה מהמארח — הכפתור נשאר', expand.hidden === false, expand.hidden);
  expand.dispatch('click');
  const ok = host.last('ui/request-display-mode');
  host.deliver({ jsonrpc: '2.0', id: ok.message.id, result: { mode: 'fullscreen' } });
  check('המארח אישר — הכפתור נעלם', expand.hidden === true, expand.hidden);
  host.deliver(hostContextChanged({ displayMode: 'inline' }));
  check('חזרה לשיחה — הכפתור חוזר', expand.hidden === false, expand.hidden);
  host.deliver(hostContextChanged({ displayMode: 'fullscreen' }));
  check('host-context-changed למסך מלא — הכפתור נעלם', expand.hidden === true, expand.hidden);
}
{
  const host = load();
  initialize(host, { availableDisplayModes: ['inline', 'fullscreen'], displayMode: 'inline' });
  host.deliver(toolResult(NOTE));
  host.find('ck-expand').dispatch('click');
  const req = host.last('ui/request-display-mode');
  host.deliver({ jsonrpc: '2.0', id: req.message.id, result: { mode: 'sidebar' } });
  check('מצב שאינו במפרט בתשובה — לא נכנס להקשר', host.find('ck-expand').hidden === false, host.find('ck-expand').hidden);
}

console.log('\nשינוי מסגרת מדווח גם בלי שינוי תוכן');
{
  const host = load();
  initialize(host);
  host.deliver(toolResult(NOTE));
  const before = host.sizes().length;
  host.resize();
  const after = host.sizes();
  check('resize של המסגרת — דיווח נוסף, גם כשהגודל זהה', after.length === before + 1, [before, after.length]);
  check('והדיווח הוא הגודל הנוכחי', after[after.length - 1].message.params.height === 240, after[after.length - 1].message.params);
  host.deliver(hostContextChanged({ containerDimensions: { width: 600, maxHeight: 700 } }));
  check('הודעה על המסגרת — דיווח נוסף', host.sizes().length === before + 2, host.sizes().length);
  host.deliver(hostContextChanged({ theme: 'light' }));
  check('הודעה על ערכה בלבד — בלי דיווח של אותו גודל', host.sizes().length === before + 2, host.sizes().length);
}

console.log('\nגלילה בכפתורים');
{
  const host = load();
  initialize(host, { availableDisplayModes: ['inline'] });
  host.deliver(toolResult(NOTE));
  check('פתק שנכנס בגובה — בלי שורת כפתורים', host.find('ck-controls').hidden === true, host.find('ck-controls').hidden);
  const body = host.find('ck-body');
  body.clientHeight = 200;
  body.scrollHeight = 1000;
  host.resize();
  const up = host.find('ck-up');
  const down = host.find('ck-down');
  check('פתק ארוך — ▲▼ מוצגים', host.find('ck-scroll-btns').hidden === false && host.find('ck-controls').hidden === false,
    [host.find('ck-scroll-btns').hidden, host.find('ck-controls').hidden]);
  check('בראש הפתק ▲ מושבת ו-▼ פעיל', up.disabled === true && down.disabled === false, [up.disabled, down.disabled]);
  check('לכפתורים יש תווית בעברית', up.getAttribute('aria-label') === 'גלילה למעלה' && down.getAttribute('aria-label') === 'גלילה למטה',
    [up.getAttribute('aria-label'), down.getAttribute('aria-label')]);
  down.dispatch('click');
  check('▼ גולל שלושה רבעים מהגובה הגלוי', body.scrolls.length === 1 && body.scrolls[0].top === 150, body.scrolls);
  check('בלי behavior — הרכות נקבעת ב-CSS', !('behavior' in body.scrolls[0]), body.scrolls[0]);
  up.dispatch('click');
  check('▲ גולל אותו צעד למעלה', body.scrolls.length === 2 && body.scrolls[1].top === -150, body.scrolls);
  body.scrollTop = 800;
  body.dispatch('scroll');
  check('בתחתית ▼ מושבת ו-▲ פעיל', down.disabled === true && up.disabled === false, [up.disabled, down.disabled]);

  // השורה מוצגת רק בגלל ▲▼: הגובה שלה חוזר לגוף כשמחליטים אם הוא גולש.
  body.scrollTop = 0;
  host.find('ck-controls').offsetHeight = 52;
  body.scrollHeight = 240;
  host.resize();
  check('תוכן שנכנס כשהשורה מוסתרת — ▲▼ נעלמים', host.find('ck-scroll-btns').hidden === true && host.find('ck-controls').hidden === true,
    [host.find('ck-scroll-btns').hidden, host.find('ck-controls').hidden]);
  body.scrollHeight = 260;
  host.resize();
  host.resize();
  check('תוכן שאינו נכנס — מוצגים, ונשארים בבדיקה חוזרת', host.find('ck-scroll-btns').hidden === false, host.find('ck-scroll-btns').hidden);
}

console.log('\nכיוון — הדף אינו מוסיף dir משלו');
{
  const host = load();
  initialize(host);
  host.deliver(toolResult({ ok: true, note: { title: 'Title in English', content: 'English first\nשורה בעברית\n', color: '#ffeddb' } }));
  // הכיוון של השורות הוא של המנוע ושל הדף (``<html dir="rtl">``), ונמדד בדפדפן. כאן — שהעטיפה של
  // הדף אינה מכריעה כיוון בעצמה, ולא מסתירה את מה שהשורות יורשות.
  const own = ['ck-paper', 'ck-title', 'ck-body', 'ck-content'].map((c) => host.find(c));
  check('לנייר, לכותרת, לגוף ולתוכן אין dir', own.every((el) => el && el.getAttribute('dir') === null), own.map((el) => el && el.getAttribute('dir')));
}

console.log('\nבלי המנוע');
{
  const host = load({ noEngine: true });
  initialize(host);
  host.deliver(toolResult(NOTE));
  check('הודעה ברורה במקום פתק ריק או "טוען…"', host.main.textContent.indexOf('לא נטענה במלואה') !== -1 && host.main.children[0].className === 'ck-status is-error',
    host.main.textContent);
  host.fire(120000);
  check('והודעת "לא הגיע" אינה דורסת אותה אחר כך', host.main.textContent.indexOf('לא נטענה במלואה') !== -1, host.main.textContent);
}
{
  // כל מה שהתצוגה צריכה מהמנוע נבדק במקום אחד, לפני הרינדור — ולא רק מה שהרינדור עצמו קורא.
  for (const missing of ['render', 'MD_SAFE_LINK', 'isViewControl', 'sourceOffsetAt', 'buildStrokeIcon',
    'openDetailsAround', 'GENERATED_TEXT_CLASS']) {
    const host = load({ engineOmit: [missing] });
    initialize(host, {}, { openLinks: {} });
    host.deliver(toolResult({ ok: true, note: { title: 'x', content: '[אתר](https://example.com)', color: '#ffffcc' } }));
    check(`מנוע בלי ${missing} — הודעה, ולא פתק שהקישור בו היה זורק בלחיצה`,
      host.main.textContent.indexOf('לא נטענה במלואה') !== -1 && !host.find('ck-paper') && host.mdCalls.length === 0,
      [host.main.textContent, host.mdCalls.length]);
  }
}

console.log('\nקישורים');
{
  const host = load();
  initialize(host, {}, { openLinks: {} });
  host.deliver(toolResult({ ok: true, note: { title: 'x', content: 'שורה\n[אתר](https://example.com/a?b=1)', color: '#ffffcc' } }));
  const link = host.find('sticky-md-link');
  check('לקישור יש title עם הכתובת', link && link.getAttribute('title') === 'https://example.com/a?b=1', link && link.getAttribute('title'));
  const ev = host.find('ck-body').dispatch('click', { target: link });
  check('הלחיצה אינה מנווטת בעצמה (preventDefault)', ev.defaultPrevented === true, ev.defaultPrevented);
  const req = host.last('ui/open-link');
  check('ui/open-link נשלח עם הכתובת', req && JSON.stringify(req.message.params) === JSON.stringify({ url: 'https://example.com/a?b=1' }) && req.message.id !== undefined,
    req && req.message);
  host.deliver({ jsonrpc: '2.0', id: req.message.id, error: { code: -32000, message: 'cancelled' } });
  check('סירוב או ביטול — הקישור נשאר, בלי הודעה', host.find('sticky-md-link') === link && host.main.textContent.indexOf('אתר') !== -1, host.main.textContent);
  const inner = host.find('sticky-task-line');
  const other = host.find('ck-body').dispatch('click', { target: inner });
  check('לחיצה שאינה על קישור — לא נבלמת ולא נשלח דבר', other.defaultPrevented === false
    && host.sent.filter((m) => m.message.method === 'ui/open-link').length === 1, other.defaultPrevented);
  link.setAttribute('href', 'javascript:alert(1)');
  host.find('ck-body').dispatch('click', { target: link });
  check('כתובת שאינה http/https אינה נשלחת', host.sent.filter((m) => m.message.method === 'ui/open-link').length === 1,
    host.sent.filter((m) => m.message.method === 'ui/open-link').length);
}
{
  // הקישור נשפט מול המנוע שבנה אותו — זה שנבדק לפני הרינדור — ולא מול מה שיש ב-``window`` ברגע הלחיצה.
  const host = load();
  initialize(host, {}, { openLinks: {} });
  host.deliver(toolResult({ ok: true, note: { title: 'x', content: '[אתר](https://example.com/b)', color: '#ffffcc' } }));
  host.win.StickyMdRender = undefined;
  let thrown = null;
  try {
    host.find('ck-body').dispatch('click', { target: host.find('sticky-md-link') });
  } catch (err) {
    thrown = err;
  }
  const req = host.last('ui/open-link');
  check('הלחיצה אינה קוראת שוב את window — הבקשה נשלחת, בלי חריגה',
    thrown === null && req && req.message.params.url === 'https://example.com/b', [thrown && String(thrown), req && req.message]);
}
{
  for (const caps of [{}, { openLinks: true }, { openLinks: null }, null, 'x']) {
    const host = load();
    initialize(host, {}, caps);
    host.deliver(toolResult({ ok: true, note: { title: 'x', content: '[אתר](https://example.com)', color: '#ffffcc' } }));
    const link = host.find('sticky-md-link');
    const ev = host.find('ck-body').dispatch('click', { target: link });
    check(`המארח אינו מודיע על openLinks (${JSON.stringify(caps)}) — אין בקשה, וגם אין ניווט`,
      !host.last('ui/open-link') && ev.defaultPrevented === true, [host.methods(), ev.defaultPrevented]);
  }
}

console.log('\nצופה הגודל רואה את התוכן');
{
  const host = load({ resizeObserver: true });
  initialize(host);
  host.deliver(toolResult(NOTE));
  const first = host.find('ck-content');
  check('אחרי רינדור — הצופה צופה ב-ck-content', host.observed.indexOf(first) !== -1, host.observed.map((e) => e.className || e.tagName));
  host.deliver(toolResult({ ok: true, note: { title: 'y', content: 'אחר', color: '#ffffcc' } }));
  const second = host.find('ck-content');
  check('פתק חדש — הצופה מפסיק לצפות בתוכן הקודם ומתחיל בחדש', second !== first && host.unobserved.indexOf(first) !== -1 && host.observed.indexOf(second) !== -1,
    [host.unobserved.length, host.observed.length]);
}
{
  // התוצאה מגיעה לפני התשובה ל-``ui/initialize`` (מארח שאינו מקפיד): הצופה, שנוצר אחר כך, צופה גם בתוכן שכבר מוצג.
  const host = load({ resizeObserver: true });
  host.deliver(toolResult(NOTE));
  initialize(host);
  check('תוכן שכבר מוצג כשהצופה נוצר — נצפה', host.observed.indexOf(host.find('ck-content')) !== -1, host.observed.map((e) => e.className || e.tagName));
}

console.log('\nהגדלת הטקסט של המערכת');
const adjustOf = (host) => host.document.documentElement.style.props['text-size-adjust'];
const probesOf = (host) => host.document.body.children.filter((c) => c.tagName === 'SPAN');
{
  const host = load();
  const props = host.document.documentElement.style.props;
  check('בלי הגדלה — לא פיצוי ולא חלוקה', adjustOf(host) === undefined && !('--ck-text-scale' in props), props);
  const probes = probesOf(host);
  check('אלמנט בדיקה אחד נוצר כבר בעלייה, לפני לחיצת היד — מוסתר, בגודל קבוע, ואינו יורש את הפיצוי',
    probes.length === 1 && host.sent.length === 1 && probes[0].style.display === 'none' && probes[0].style.fontSize === '100px'
      && probes[0].style.props['text-size-adjust'] === 'auto',
    [probes.length, host.sent.length, probes[0] && probes[0].style.props]);
}
{
  // מנוע שמכבד ``text-size-adjust`` — WebView מודרני.
  const host = load({ textZoom: 1.3 });
  const props = host.document.documentElement.style.props;
  const near = (value, expected) => value !== undefined && /%$/.test(value) && Math.abs(parseFloat(value) - expected) < 1e-9;
  check('הגדלה של 130% נמדדת כבר בעלייה, ומבוטלת ב-text-size-adjust של 100/1.3 אחוז', near(adjustOf(host), 100 / 1.3), props);
  check('והגופנים אינם מחולקים — ה-em נשאר של הוובאפ', !('--ck-text-scale' in props), props);
  initialize(host);
  host.deliver(toolResult(NOTE));
  host.zoom.text = 1.15;
  host.resize();
  check('שינוי של ההגדלה נמדד שוב במדידת הגודל הבאה — מול ההגדלה עצמה, לא מול מה שנשאר אחרי הפיצוי',
    near(adjustOf(host), 100 / 1.15), props);
  host.zoom.text = 1;
  host.resize();
  check('חזרה ל-100% — הפיצוי יורד', adjustOf(host) === undefined && !('--ck-text-scale' in props), props);
  check('ובכל המדידות — אותם שני אלמנטי בדיקה, לא חדשים בכל פעם', probesOf(host).length === 2, probesOf(host).length);
}
{
  // מנוע שאינו מכבד ``text-size-adjust`` — הבדיקה שאחרי ההצבה מגלה שההגדלה נשארה.
  const host = load({ textZoom: 1.3, tsa: false });
  const props = host.document.documentElement.style.props;
  check('מנוע שמתעלם מ-text-size-adjust — חלוקה של הגופנים ב-1.3, והפיצוי שלא עבד אינו נשאר',
    props['--ck-text-scale'] === '1.3' && adjustOf(host) === undefined, props);
  initialize(host);
  host.deliver(toolResult(NOTE));
  host.zoom.text = 1.15;
  host.resize();
  check('שינוי של ההגדלה — החלוקה מתעדכנת', props['--ck-text-scale'] === '1.15' && adjustOf(host) === undefined, props);
  host.zoom.text = 1;
  host.resize();
  check('חזרה ל-100% — שום דבר אינו מוצב', !('--ck-text-scale' in props) && adjustOf(host) === undefined, props);
}
{
  for (const tsa of [true, false]) {
    for (const raw of ['', 'abc', '0px', '-100px', 'NaNpx']) {
      const host = load({ textZoom: 1.3, tsa });
      const before = JSON.stringify(host.document.documentElement.style.props);
      host.zoom.raw = raw;
      host.resize();
      initialize(host);
      host.resize();
      const after = JSON.stringify(host.document.documentElement.style.props);
      check(`גודל מחושב לא תקין (${JSON.stringify(raw)}, tsa=${tsa}) — הפיצוי התקין האחרון נשאר`, before === after && before !== '{}', [before, after]);
    }
  }
}

// ── עריכה ────────────────────────────────────────────────────────────────────────

const SHA = 'c'.repeat(64);
const SHA2 = 'd'.repeat(64);
const EDIT_CTX = { availableDisplayModes: ['inline', 'fullscreen'], displayMode: 'inline' };
const EDIT_CAPS = { serverTools: {} };
const LINES = ['שורה ראשונה', 'שורה שנייה', 'שורה שלישית'];
const editNote = (over = {}) => ({ ok: true, editable: true, target: 'board',
  note: { id: 'a'.repeat(24), title: 'רשימת קניות', content: LINES.join('\n'), content_sha256: SHA, color: '#ffeddb', ...over } });
const toolAnswer = (obj) => ({ content: [{ type: 'text', text: JSON.stringify(obj) }] });
const toolCalls = (host, name) => host.sent.filter((s) => s.message.method === 'tools/call' && s.message.params.name === name);
const answer = (host, req, result) => host.deliver({ jsonrpc: '2.0', id: req.message.id, result });
const answerError = (host, req) => host.deliver({ jsonrpc: '2.0', id: req.message.id, error: { code: -32000, message: 'no' } });

function editableView(opts = {}) {
  const host = load();
  initialize(host, opts.ctx || EDIT_CTX, opts.caps === undefined ? EDIT_CAPS : opts.caps);
  host.deliver(toolResult(opts.note || editNote()));
  return host;
}

/** לחיצה על שורה ``index``, ושתי התשובות שהעריכה מחכה להן. מחזיר את תיבת הטקסט. */
function openEditorAt(host, index, fresh = editNote()) {
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[index] });
  const fs = host.last('ui/request-display-mode');
  if (fs) answer(host, fs, { mode: 'fullscreen' });
  answer(host, toolCalls(host, 'codekeeper_show_note').pop(), toolAnswer(fresh));
  return host.find('ck-editor');
}

function savedAnswer(content, sha = SHA2) {
  return toolAnswer({ ok: true, note: { ...editNote().note, content, content_sha256: sha }, content_changed: false });
}

console.log('\nעריכה — מתי מוצעת');
{
  const host = editableView();
  check('editable, serverTools ומסך מלא — כפתור העריכה מוצג: ✎, ושמו בתווית', host.find('ck-edit').hidden === false && host.find('ck-edit').textContent === '✎'
    && host.find('ck-edit').getAttribute('aria-label') === 'עריכה' && host.find('ck-edit').getAttribute('title') === 'עריכה',
    host.find('ck-edit').hidden);
  check('הפתק נבנה עם ההיסטים של השורות (sourceOffsets)', host.mdCalls[0].options && host.mdCalls[0].options.sourceOffsets === true, host.mdCalls[0].options);
}
for (const [name, opts] of [
  ['השרת אומר editable: false', { note: { ...editNote(), editable: false } }],
  ['בלי editable בכלל', { note: { ok: true, note: editNote().note } }],
  ['המארח אינו מעביר קריאות לכלים (בלי serverTools)', { caps: {} }],
  ['serverTools שאינו אובייקט', { caps: { serverTools: true } }],
  ['המארח אינו מציע מסך מלא', { ctx: { availableDisplayModes: ['inline'] } }],
  ['לפתק אין content_sha256', { note: editNote({ content_sha256: undefined }) }],
  ['לפתק אין מזהה', { note: editNote({ id: undefined }) }],
]) {
  const host = editableView(opts);
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[1] });
  check(`${name} — אין כפתור, ולחיצה על שורה אינה שולחת דבר`, host.find('ck-edit').hidden === true && toolCalls(host, 'codekeeper_show_note').length === 0
    && !host.last('ui/request-display-mode'), [host.find('ck-edit').hidden, host.methods()]);
}

console.log('\nפתיחת העריכה');
{
  const host = editableView();
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[1] });
  const fs = host.last('ui/request-display-mode');
  const reads = toolCalls(host, 'codekeeper_show_note');
  check('לחיצה על שורה — בקשה למסך מלא, מתוך הלחיצה', fs && JSON.stringify(fs.message.params) === JSON.stringify({ mode: 'fullscreen' }), host.methods());
  check('ובמקביל קריאה טרייה של הפתק — tools/call של codekeeper_show_note עם המזהה בלבד',
    reads.length === 1 && JSON.stringify(reads[0].message.params.arguments) === JSON.stringify({ note_id: 'a'.repeat(24) }), reads.map((r) => r.message.params));
  check('לפני התשובות — אין עורך, ההודעה "פותח לעריכה…", והכפתור מוסתר',
    !host.find('ck-editor') && host.find('ck-notice').textContent === 'פותח לעריכה…' && host.find('ck-edit').hidden === true,
    [!!host.find('ck-editor'), host.find('ck-notice').textContent]);
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[2] });
  check('לחיצה נוספת בזמן ההמתנה — בלי בקשה שנייה', toolCalls(host, 'codekeeper_show_note').length === 1, toolCalls(host, 'codekeeper_show_note').length);
  answer(host, reads[0], toolAnswer(editNote()));
  check('הקריאה ענתה, המסך המלא עוד לא — עדיין אין עורך', !host.find('ck-editor'), !!host.find('ck-editor'));
  answer(host, fs, { mode: 'fullscreen' });
  const ta = host.find('ck-editor');
  const offset = LINES[0].length + 1;
  check('שתיהן ענו — תיבת טקסט עם הגוף הגולמי', ta && ta.tagName === 'TEXTAREA' && ta.value === LINES.join('\n'), ta && ta.value);
  check('הסמן בתחילת השורה שנלחצה', ta.selection && ta.selection[0] === offset && ta.selection[1] === offset, ta.selection);
  check('ובפוקוס', FakeElement.focused === ta, FakeElement.focused && FakeElement.focused.className);
  check('הגוף המרונדר והשורה שלו מוסתרים, שורת העורך מוצגת',
    host.find('ck-body').hidden === true && host.find('ck-controls').hidden === true && host.find('ck-edit-bar').hidden === false,
    [host.find('ck-body').hidden, host.find('ck-controls').hidden, host.find('ck-edit-bar').hidden]);
  check('שורת העורך: "שמור" ו"בטל", ו"החזר את הטקסט שלי" מוסתר',
    host.find('ck-save').textContent === 'שמור' && host.find('ck-cancel').textContent === 'בטל' && host.find('ck-restore').hidden === true,
    [host.find('ck-save').textContent, host.find('ck-cancel').textContent]);
  check('ההודעה נוקתה', host.find('ck-notice').hidden === true, host.find('ck-notice').textContent);
  const paper = host.find('ck-paper');
  check('"שמור" ו"בטל" בשורת הראש, עם הכותרת — והשורה מעל תיבת הטקסט',
    host.find('ck-edit-bar').parentNode === host.find('ck-head') && host.find('ck-head').children[0] === host.find('ck-title')
      && paper.children.indexOf(host.find('ck-head')) < paper.children.indexOf(ta), paper.children.map((c) => c.className));
  check('הסטטוס בשורה משלו, מוסתר כשהוא ריק', host.find('ck-edit-status').hidden === true && host.find('ck-edit-status').parentNode === paper,
    host.find('ck-edit-status').hidden);
}
{
  const host = editableView();
  host.find('ck-edit').dispatch('click');
  answer(host, host.last('ui/request-display-mode'), { mode: 'fullscreen' });
  answer(host, toolCalls(host, 'codekeeper_show_note')[0], toolAnswer(editNote()));
  check('כפתור העריכה — הסמן בתחילת הפתק', host.find('ck-editor').selection[0] === 0, host.find('ck-editor').selection);
}
{
  const host = editableView({ ctx: { ...EDIT_CTX, displayMode: 'fullscreen' } });
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[2] });
  check('כבר במסך מלא — בלי בקשה למסך מלא', !host.last('ui/request-display-mode'), host.methods());
  answer(host, toolCalls(host, 'codekeeper_show_note')[0], toolAnswer(editNote()));
  const offset = LINES[0].length + LINES[1].length + 2;
  check('והעורך נפתח אחרי הקריאה בלבד', host.find('ck-editor') && host.find('ck-editor').selection[0] === offset, host.find('ck-editor') && host.find('ck-editor').selection);
}
{
  const host = editableView();
  const link = host.find('ck-body');
  host.deliver(toolResult(editNote({ content: '::: details פרטים\n[אתר](https://example.com)\nשורה' })));
  host.find('ck-body').dispatch('click', { target: host.find('sticky-md-details-summary') });
  host.find('ck-body').dispatch('click', { target: host.find('sticky-md-link') });
  check('לחיצה על כותרת של בלוק מתקפל או על קישור — אינה פותחת עריכה', toolCalls(host, 'codekeeper_show_note').length === 0, host.methods());
  void link;
}

console.log('\nפתיחה שלא מצליחה');
{
  const host = editableView();
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[1] });
  answer(host, host.last('ui/request-display-mode'), { mode: 'inline' });
  answer(host, toolCalls(host, 'codekeeper_show_note')[0], toolAnswer(editNote()));
  check('המארח סירב למסך מלא — אין עורך, הודעה, והכפתור חוזר',
    !host.find('ck-editor') && host.find('ck-notice').className === 'ck-notice is-error' && host.find('ck-notice').textContent.indexOf('מסך מלא') !== -1
      && host.find('ck-edit').hidden === false, [host.find('ck-notice').textContent, host.find('ck-edit').hidden]);
}
{
  const host = editableView();
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[1] });
  answer(host, host.last('ui/request-display-mode'), { mode: 'fullscreen' });
  answer(host, toolCalls(host, 'codekeeper_show_note')[0], toolAnswer({ ok: false, error: 'not_found' }));
  check('הקריאה הטרייה החזירה not_found — אין עורך, וההודעה הידועה', !host.find('ck-editor')
    && host.find('ck-notice').textContent === 'הפתק לא נמצא, או שאין לך גישה אליו.', host.find('ck-notice').textContent);
}
{
  const host = editableView();
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[1] });
  answer(host, host.last('ui/request-display-mode'), { mode: 'fullscreen' });
  answer(host, toolCalls(host, 'codekeeper_show_note')[0], toolAnswer({ ...editNote(), editable: false }));
  check('הקריאה הטרייה אומרת editable: false — אין עורך, והסבר על הרשאת כתיבה', !host.find('ck-editor')
    && host.find('ck-notice').textContent.indexOf('הרשאת כתיבה') !== -1 && host.find('ck-edit').hidden === true, host.find('ck-notice').textContent);
}
{
  const host = editableView();
  const fresh = editNote({ content: 'גוף חדש\nשנכתב בוובאפ', content_sha256: SHA2 });
  const ta = openEditorAt(host, 2, fresh);
  check('הפתק השתנה מאז שהתצוגה קיבלה אותו — העורך נפתח על הגרסה הטרייה', ta && ta.value === fresh.note.content, ta && ta.value);
  check('הסמן בתחילת הפתק — ההיסט שנלחץ שייך לטקסט הישן', ta.selection[0] === 0, ta.selection);
  check('והתצוגה נבנתה מחדש מהגרסה הטרייה', host.mdCalls.length === 2 && host.mdCalls[1].text === fresh.note.content, host.mdCalls.map((c) => c.text));
  host.find('ck-save').dispatch('click');
  check('והשמירה תיבנה על ה-hash הטרי', toolCalls(host, 'codekeeper_note_view_save')[0].message.params.arguments.expected_content_sha256 === SHA2,
    toolCalls(host, 'codekeeper_note_view_save')[0].message.params.arguments);
}
{
  const host = editableView();
  const fresh = editNote({ content: 'גרסה טרייה', content_sha256: SHA2 });
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[1] });
  answer(host, toolCalls(host, 'codekeeper_show_note')[0], toolAnswer(fresh));
  answer(host, host.last('ui/request-display-mode'), { mode: 'inline' });
  check('מסך מלא נדחה אבל הקריאה הטרייה הגיעה — התצוגה מתעדכנת בכל זאת', host.mdCalls.length === 2 && host.mdCalls[1].text === 'גרסה טרייה',
    host.mdCalls.map((c) => c.text));
}
{
  const host = editableView();
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[1] });
  const fs = host.last('ui/request-display-mode');
  const read = toolCalls(host, 'codekeeper_show_note')[0];
  host.fire(20000);
  check('אף תשובה לא הגיעה — אחרי תקרת הזמן: הודעה, והכפתור חוזר',
    host.find('ck-notice').textContent.indexOf('לא התקבלה תשובה') !== -1 && host.find('ck-edit').hidden === false && !host.find('ck-editor'),
    [host.find('ck-notice').textContent, host.find('ck-edit').hidden]);
  answer(host, fs, { mode: 'fullscreen' });
  answer(host, read, toolAnswer(editNote()));
  check('תשובות שמגיעות אחרי התקרה — אינן פותחות עורך', !host.find('ck-editor'), !!host.find('ck-editor'));
  host.find('ck-edit').dispatch('click');
  check('ואפשר לנסות שוב', toolCalls(host, 'codekeeper_show_note').length === 2, toolCalls(host, 'codekeeper_show_note').length);
}
{
  const host = editableView();
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[1] });
  answer(host, toolCalls(host, 'codekeeper_show_note')[0], toolAnswer(editNote()));
  host.fire(20000);
  check('רק המסך המלא לא ענה — אותה תקרה משחררת', host.find('ck-edit').hidden === false && host.find('ck-notice').textContent.indexOf('לא התקבלה תשובה') !== -1,
    host.find('ck-notice').textContent);
}

console.log('\nשמירה');
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'שורה ראשונה\nשורה שנייה ערוכה\nשורה שלישית';
  host.find('ck-save').dispatch('click');
  const saves = toolCalls(host, 'codekeeper_note_view_save');
  check('"שמור" — codekeeper_note_view_save עם המזהה, הגוף כולו וה-hash שהעריכה נבנתה עליו',
    saves.length === 1 && JSON.stringify(saves[0].message.params.arguments) === JSON.stringify({ note_id: 'a'.repeat(24), content: ta.value, expected_content_sha256: SHA }),
    saves.map((s) => s.message.params.arguments));
  check('בזמן השמירה "שמור" ו"בטל" מושבתים, והסטטוס "שומר…"',
    host.find('ck-save').disabled === true && host.find('ck-cancel').disabled === true && host.find('ck-edit-status').textContent === 'שומר…',
    [host.find('ck-save').disabled, host.find('ck-edit-status').textContent]);
  host.find('ck-save').dispatch('click');
  check('לחיצה נוספת בזמן השמירה — אין בקשה שנייה', toolCalls(host, 'codekeeper_note_view_save').length === 1, toolCalls(host, 'codekeeper_note_view_save').length);
  const sent = ta.value;
  answer(host, saves[0], savedAnswer(sent));
  const ctx = host.last('ui/update-model-context');
  check('השמירה עברה — המודל מתעדכן (ui/update-model-context)', !!ctx, host.methods());
  const text = ctx && ctx.message.params.content[0].text;
  check('בגוף העדכון: המזהה, ה-hash החדש, ההסבר והגוף כולו',
    ctx && ctx.message.params.content.length === 1 && ctx.message.params.content[0].type === 'text'
      && text.indexOf('note_id: ' + 'a'.repeat(24)) !== -1 && text.indexOf('content_sha256: ' + SHA2) !== -1
      && text.indexOf('codekeeper_show_note') !== -1 && text.endsWith('\n' + sent), text);
  check('העורך נסגר, והפתק מוצג מהגרסה השמורה', !host.find('ck-editor') && host.mdCalls[host.mdCalls.length - 1].text === sent && host.find('ck-body').hidden === false,
    [!!host.find('ck-editor'), host.mdCalls[host.mdCalls.length - 1].text]);
  check('ההודעה "נשמר."', host.find('ck-notice').textContent === 'נשמר.' && host.find('ck-notice').hidden === false, host.find('ck-notice').textContent);
  answer(host, ctx, {});
  check('המארח קיבל את העדכון — בלי הערה על המודל', host.find('ck-notice').textContent === 'נשמר.', host.find('ck-notice').textContent);
  const ta2 = openEditorAt(host, 0, { ...editNote(), note: { ...editNote().note, content: sent, content_sha256: SHA2 } });
  ta2.value = sent + '\nעוד';
  host.find('ck-save').dispatch('click');
  check('העריכה הבאה נבנית על ה-hash של מה שנשמר', toolCalls(host, 'codekeeper_note_view_save')[1].message.params.arguments.expected_content_sha256 === SHA2,
    toolCalls(host, 'codekeeper_note_view_save')[1].message.params.arguments);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'א';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[0], savedAnswer('א'));
  answerError(host, host.last('ui/update-model-context'));
  check('המארח דחה את עדכון המודל — ההודעה אומרת שהמודל לא עודכן', host.find('ck-notice').textContent.indexOf('Claude לא עודכן') !== -1,
    host.find('ck-notice').textContent);
  const ta2 = openEditorAt(host, 0, { ...editNote(), note: { ...editNote().note, content: 'א', content_sha256: SHA2 } });
  check('ההערה נשארת גם כשההודעות מתחלפות — עד עדכון שעובר', host.find('ck-notice').textContent.indexOf('Claude לא עודכן') !== -1,
    host.find('ck-notice').textContent);
  ta2.value = 'ב';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[1], savedAnswer('ב', 'e'.repeat(64)));
  answer(host, host.last('ui/update-model-context'), {});
  check('עדכון שעבר מוחק את ההערה', host.find('ck-notice').textContent === 'נשמר.', host.find('ck-notice').textContent);
}
{
  // רק התשובה לעדכון האחרון קובעת — כל עדכון מחליף את הקודם.
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'א';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[0], savedAnswer('א'));
  const first = host.last('ui/update-model-context');
  const ta2 = openEditorAt(host, 0, { ...editNote(), note: { ...editNote().note, content: 'א', content_sha256: SHA2 } });
  ta2.value = 'ב';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[1], savedAnswer('ב', 'e'.repeat(64)));
  const second = host.last('ui/update-model-context');
  answer(host, second, {});
  answerError(host, first);
  check('דחייה מאוחרת של עדכון ישן — אינה מסמנת את המודל כלא מעודכן', host.find('ck-notice').textContent === 'נשמר.', host.find('ck-notice').textContent);
}
for (const [name, reply, expect] of [
  ['rate_limited', toolAnswer({ ok: false, error: 'rate_limited' }), 'יותר מדי קריאות'],
  ['empty_content', toolAnswer({ ok: false, error: 'empty_content' }), 'פתק ריק'],
  ['content_too_long עם max', toolAnswer({ ok: false, error: 'content_too_long', max: SERVER_MAX_NOTE_CHARS }), `עד ${SERVER_MAX_NOTE_CHARS} תווים`],
  ['קוד לא מוכר', toolAnswer({ ok: false, error: 'weird_code' }), '(weird_code)'],
  ['isError של insufficient_scope', { isError: true, content: [{ type: 'text', text: 'Error executing tool codekeeper_note_view_save: insufficient_scope: this action needs write permission.' }] }, 'הרשאת כתיבה'],
]) {
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'שינוי';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[0], reply);
  check(`השמירה נדחתה (${name}) — העורך נשאר עם הטקסט, הסטטוס מסביר, ואפשר לשמור שוב`,
    host.find('ck-editor') && host.find('ck-editor').value === 'שינוי' && host.find('ck-edit-status').textContent.indexOf(expect) !== -1
      && host.find('ck-edit-status').className === 'ck-edit-status is-error' && host.find('ck-save').disabled === false && !host.last('ui/update-model-context'),
    [host.find('ck-edit-status').textContent, host.find('ck-save').disabled]);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'שינוי';
  host.find('ck-save').dispatch('click');
  const save = toolCalls(host, 'codekeeper_note_view_save')[0];
  host.fire(20000);
  const reads = toolCalls(host, 'codekeeper_show_note');
  check('אין תשובה לשמירה — אחרי תקרת הזמן הדף קורא את הפתק כדי להכריע, והכפתורים עוד מושבתים',
    reads.length === 2 && host.find('ck-save').disabled === true && host.find('ck-edit-status').textContent.indexOf('בודק אם היא עברה') !== -1,
    [reads.length, host.find('ck-save').disabled, host.find('ck-edit-status').textContent]);
  answer(host, reads[1], toolAnswer(editNote()));
  check('הפתק לא השתנה — ייתכן שהשמירה עוד בדרך: הסטטוס אומר את זה, והכפתורים חוזרים',
    host.find('ck-save').disabled === false && host.find('ck-cancel').disabled === false && host.find('ck-edit-status').textContent.indexOf('ייתכן שהיא עוד בדרך') !== -1
      && host.find('ck-edit-status').className === 'ck-edit-status is-error', [host.find('ck-save').disabled, host.find('ck-edit-status').textContent]);
  answer(host, save, savedAnswer('שינוי'));
  check('תשובה שמגיעה אחרי התקרה — נזרקת: העורך פתוח, והמודל לא עודכן ממנה', !!host.find('ck-editor') && !host.last('ui/update-model-context'),
    [!!host.find('ck-editor'), host.methods().slice(-3)]);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'נחתה';
  host.find('ck-save').dispatch('click');
  host.fire(20000);
  answer(host, toolCalls(host, 'codekeeper_show_note')[1], toolAnswer(editNote({ content: 'נחתה', content_sha256: SHA2 })));
  check('אחרי תקרה, הקריאה מראה בדיוק את מה שנשלח — השמירה עברה: העורך נסגר, "נשמר.", והמודל מתעדכן',
    !host.find('ck-editor') && host.find('ck-notice').textContent === 'נשמר.' && !!host.last('ui/update-model-context')
      && host.last('ui/update-model-context').message.params.content[0].text.endsWith('\nנחתה'), [!!host.find('ck-editor'), host.find('ck-notice').textContent]);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'נשלח';
  host.find('ck-save').dispatch('click');
  ta.value = 'נשלח ועוד';
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[0], savedAnswer('נשלח'));
  check('הקלדה בזמן השמירה — העורך נשאר פתוח עם מה שהוקלד', host.find('ck-editor') === ta && ta.value === 'נשלח ועוד', [!!host.find('ck-editor'), ta.value]);
  check('והסטטוס אומר שמה שהוקלד עוד לא נשמר', host.find('ck-edit-status').textContent.indexOf('עוד לא נשמר') !== -1, host.find('ck-edit-status').textContent);
  host.find('ck-save').dispatch('click');
  check('והשמירה הבאה נבנית על מה שנשמר', toolCalls(host, 'codekeeper_note_view_save')[1].message.params.arguments.expected_content_sha256 === SHA2,
    toolCalls(host, 'codekeeper_note_view_save')[1].message.params.arguments);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'מקלדת';
  const ev = ta.dispatch('keydown', { key: 's', ctrlKey: true });
  check('Ctrl+S שומר, ולא שומר את הדף', toolCalls(host, 'codekeeper_note_view_save').length === 1 && ev.defaultPrevented === true, host.methods().slice(-2));
  const host2 = editableView();
  const ta2 = openEditorAt(host2, 1);
  ta2.dispatch('keydown', { key: 'S', metaKey: true });
  check('Cmd+S גם', toolCalls(host2, 'codekeeper_note_view_save').length === 1, host2.methods().slice(-2));
  const host3 = editableView();
  const ta3 = openEditorAt(host3, 1);
  ta3.dispatch('keydown', { key: 's' });
  check('s בלי מקש שליטה — אינו שומר', toolCalls(host3, 'codekeeper_note_view_save').length === 0, host3.methods().slice(-2));
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'בעבודה';
  host.deliver(toolResult(editNote({ content: 'אחר' })));
  check('תוצאת כלי שמגיעה בזמן עריכה — אינה דורסת את העורך', host.find('ck-editor') === ta && ta.value === 'בעבודה', [!!host.find('ck-editor'), ta.value]);
}

console.log('\nהתנגשות');
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'הטקסט שלי';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[0], toolAnswer({ ok: false, error: 'conflict', hint: 'x' }));
  const reads = toolCalls(host, 'codekeeper_show_note');
  check('conflict — קריאה טרייה כדי להכריע מה קרה, והכפתורים מושבתים בזמנה', reads.length === 2 && host.find('ck-save').disabled === true,
    [reads.length, host.find('ck-save').disabled]);
  answer(host, reads[1], toolAnswer(editNote({ content: 'הגרסה של מישהו אחר', content_sha256: SHA2 })));
  check('מישהו אחר שינה — שורת ההתנגשות מוצגת, והטקסט שלי נשאר בעורך',
    host.find('ck-conflict').hidden === false && ta.value === 'הטקסט שלי' && host.find('ck-save').disabled === false,
    [host.find('ck-conflict').hidden, ta.value]);
  check('בשורה: "עדכן" ו"שמור בכל זאת"', host.find('ck-accept').textContent === 'עדכן' && host.find('ck-overwrite').textContent === 'שמור בכל זאת',
    [host.find('ck-accept').textContent, host.find('ck-overwrite').textContent]);
  host.find('ck-accept').dispatch('click');
  check('"עדכן" — הגרסה שבשרת בעורך, והשורה נעלמת', ta.value === 'הגרסה של מישהו אחר' && host.find('ck-conflict').hidden === true, ta.value);
  check('ו"החזר את הטקסט שלי" מופיע', host.find('ck-restore').hidden === false, host.find('ck-restore').hidden);
  host.find('ck-restore').dispatch('click');
  check('"החזר את הטקסט שלי" — הטקסט שלי חוזר, והכפתור נעלם', ta.value === 'הטקסט שלי' && host.find('ck-restore').hidden === true, ta.value);
  host.find('ck-save').dispatch('click');
  const save = toolCalls(host, 'codekeeper_note_view_save')[1];
  check('ושמירה אחריו — הטקסט שלי, מעל הגרסה שנטענה', save.message.params.arguments.content === 'הטקסט שלי' && save.message.params.arguments.expected_content_sha256 === SHA2,
    save.message.params.arguments);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'הטקסט שלי';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[0], toolAnswer({ ok: false, error: 'conflict' }));
  answer(host, toolCalls(host, 'codekeeper_show_note')[1], toolAnswer(editNote({ content: 'של מישהו אחר', content_sha256: SHA2 })));
  host.find('ck-overwrite').dispatch('click');
  const save = toolCalls(host, 'codekeeper_note_view_save')[1];
  check('"שמור בכל זאת" — שמירה של הטקסט שלי מעל הגרסה שבשרת (ה-hash שלה)', save && save.message.params.arguments.content === 'הטקסט שלי'
    && save.message.params.arguments.expected_content_sha256 === SHA2 && host.find('ck-conflict').hidden === true, save && save.message.params.arguments);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'מה ששלחתי';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[0], toolAnswer({ ok: false, error: 'conflict' }));
  answer(host, toolCalls(host, 'codekeeper_show_note')[1], toolAnswer(editNote({ content: 'מה ששלחתי', content_sha256: SHA2 })));
  check('בשרת בדיוק מה ששלחתי — זו השמירה שלי: נשמר, בלי שורת התנגשות, והמודל מתעדכן',
    !host.find('ck-editor') && host.find('ck-notice').textContent === 'נשמר.' && !!host.last('ui/update-model-context'),
    [!!host.find('ck-editor'), host.find('ck-notice').textContent]);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'ראשון';
  host.find('ck-save').dispatch('click');
  host.fire(20000);
  answer(host, toolCalls(host, 'codekeeper_show_note')[1], toolAnswer(editNote()));
  ta.value = 'ראשון ושני';
  host.find('ck-save').dispatch('click');
  const second = toolCalls(host, 'codekeeper_note_view_save')[1];
  check('אחרי תקרה שלא הוכרעה — השמירה הבאה עדיין על ה-hash הישן', second.message.params.arguments.expected_content_sha256 === SHA, second.message.params.arguments);
  answer(host, second, toolAnswer({ ok: false, error: 'conflict' }));
  answer(host, toolCalls(host, 'codekeeper_show_note')[2], toolAnswer(editNote({ content: 'ראשון', content_sha256: SHA2 })));
  const third = toolCalls(host, 'codekeeper_note_view_save')[2];
  check('בשרת מה שהשמירה שלא נענתה שלחה — השמירה שלי עברה: יוצאת שוב, על ה-hash שלה, בלי שורת התנגשות',
    third && third.message.params.arguments.content === 'ראשון ושני' && third.message.params.arguments.expected_content_sha256 === SHA2
      && host.find('ck-conflict').hidden === true, third && third.message.params.arguments);
  const ctx = host.last('ui/update-model-context');
  check('והמודל לומד על השמירה ההיא', ctx && ctx.message.params.content[0].text.endsWith('\nראשון'), ctx && ctx.message.params.content[0].text);
  answer(host, third, toolAnswer({ ok: false, error: 'conflict' }));
  answer(host, toolCalls(host, 'codekeeper_show_note')[3], toolAnswer(editNote({ content: 'ראשון', content_sha256: 'f'.repeat(64) })));
  check('ואם גם השמירה הזו נתקלת — רק פעם אחת: עכשיו שורת התנגשות, לא לולאה', toolCalls(host, 'codekeeper_note_view_save').length === 3
    && host.find('ck-conflict').hidden === false, toolCalls(host, 'codekeeper_note_view_save').length);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'שלי';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[0], toolAnswer({ ok: false, error: 'conflict' }));
  host.fire(20000);
  check('הקריאה שאחרי ההתנגשות לא ענתה — הכפתורים חוזרים, והטקסט נשאר', host.find('ck-save').disabled === false && ta.value === 'שלי'
    && host.find('ck-edit-status').className === 'ck-edit-status is-error', [host.find('ck-save').disabled, host.find('ck-edit-status').textContent]);
}

console.log('\nהתשובה על שמירה שייכת לדף — גם כשהעורך כבר נסגר');
const lastRender = (host) => host.mdCalls[host.mdCalls.length - 1].text;
/** שמירה של ``edited``, ובזמן שהיא בדרך: הטקסט חוזר למקור, ו-Claude יוצא ממסך מלא — העורך הנקי נסגר. */
function saveThenUndoAndLeave(host, edited) {
  const ta = openEditorAt(host, 1);
  const original = ta.value;
  ta.value = edited;
  host.find('ck-save').dispatch('click');
  ta.value = original;
  host.deliver(hostContextChanged({ displayMode: 'inline' }));
  return toolCalls(host, 'codekeeper_note_view_save')[0];
}
{
  const host = editableView();
  const edited = LINES.join('\n') + '\nנוסף';
  const save = saveThenUndoAndLeave(host, edited);
  check('החזרת הטקסט למקור ויציאה ממסך מלא בזמן שמירה — העורך הנקי נסגר', !host.find('ck-editor'), !!host.find('ck-editor'));
  check('בזמן שהשמירה בדרך אין כפתור עריכה', host.find('ck-edit').hidden === true, host.find('ck-edit').hidden);
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[0] });
  check('ולחיצה על שורה אינה פותחת עורך חדש — ההודעה אומרת שהשמירה עוד בדרך',
    toolCalls(host, 'codekeeper_show_note').length === 1 && host.find('ck-notice').textContent.indexOf('עוד בדרך') !== -1,
    [toolCalls(host, 'codekeeper_show_note').length, host.find('ck-notice').textContent]);
  answer(host, save, savedAnswer(edited));
  check('השמירה נחתה — הפתק מוצג מהגרסה השמורה, ולא מהגרסה שלפני העריכה', lastRender(host) === edited, lastRender(host));
  check('וההודעה "נשמר."', host.find('ck-notice').textContent === 'נשמר.', host.find('ck-notice').textContent);
  const ctx = host.last('ui/update-model-context');
  check('והמודל מקבל את הגרסה השמורה', ctx && ctx.message.params.content[0].text.endsWith('\n' + edited), ctx && ctx.message.params.content[0].text);
  check('כפתור העריכה חוזר', host.find('ck-edit').hidden === false, host.find('ck-edit').hidden);
  const ta2 = openEditorAt(host, 0, { ...editNote(), note: { ...editNote().note, content: edited, content_sha256: SHA2 } });
  ta2.value = edited + '!';
  host.find('ck-save').dispatch('click');
  check('והעריכה הבאה נבנית על ה-hash של מה שנשמר', toolCalls(host, 'codekeeper_note_view_save')[1].message.params.arguments.expected_content_sha256 === SHA2,
    toolCalls(host, 'codekeeper_note_view_save')[1].message.params.arguments);
}
{
  const host = editableView();
  const save = saveThenUndoAndLeave(host, 'משהו אחר');
  answer(host, save, toolAnswer({ ok: false, error: 'conflict' }));
  const reads = toolCalls(host, 'codekeeper_show_note');
  check('העורך כבר נסגר והשמירה נתקלה — הדף עדיין קורא את הפתק כדי להכריע', reads.length === 2, reads.length);
  answer(host, reads[1], toolAnswer(editNote({ content: 'מהוובאפ', content_sha256: SHA2 })));
  check('מישהו אחר שינה — הפתק מוצג מהגרסה שבשרת, וההודעה אומרת שהשמירה לא עברה',
    lastRender(host) === 'מהוובאפ' && host.find('ck-notice').textContent.indexOf('השמירה לא עברה') !== -1 && host.find('ck-notice').className === 'ck-notice is-error',
    [lastRender(host), host.find('ck-notice').textContent]);
  check('ובלי עדכון של המודל על גוף שלא נכתב', !host.last('ui/update-model-context'), host.methods().slice(-3));
  check('כפתור העריכה חוזר', host.find('ck-edit').hidden === false, host.find('ck-edit').hidden);
}
{
  const host = editableView();
  saveThenUndoAndLeave(host, 'שלי');
  host.fire(20000);
  answer(host, toolCalls(host, 'codekeeper_show_note')[1], toolAnswer(editNote({ content: 'שלי', content_sha256: SHA2 })));
  check('העורך כבר נסגר, התשובה לא הגיעה, והקריאה מראה את מה שנשלח — "נשמר.", הגרסה השמורה מוצגת, והמודל מתעדכן',
    host.find('ck-notice').textContent === 'נשמר.' && lastRender(host) === 'שלי' && !!host.last('ui/update-model-context'),
    [host.find('ck-notice').textContent, lastRender(host)]);
}
{
  const host = editableView();
  const save = saveThenUndoAndLeave(host, 'שלי');
  answer(host, save, toolAnswer({ ok: false, error: 'rate_limited' }));
  check('העורך כבר נסגר והשמירה נדחתה — ההודעה שמתחת לפתק אומרת למה',
    host.find('ck-notice').textContent.indexOf('יותר מדי קריאות') !== -1 && host.find('ck-notice').className === 'ck-notice is-error' && host.find('ck-edit').hidden === false,
    [host.find('ck-notice').textContent, host.find('ck-edit').hidden]);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'נשמר בשרת';
  host.find('ck-save').dispatch('click');
  ta.value = 'נשמר בשרת ועוד';
  host.deliver(hostContextChanged({ displayMode: 'inline' }));
  check('יציאה ממסך מלא עם שינוי בזמן שמירה — העורך נשאר, ו"בטל שינויים" מושבת עד התשובה',
    host.find('ck-editor') === ta && host.find('ck-drop').disabled === true, [!!host.find('ck-editor'), host.find('ck-drop').disabled]);
  host.find('ck-drop').dispatch('click');
  check('ולחיצה עליו (שלא אמורה להיות אפשרית) אינה סוגרת', host.find('ck-editor') === ta, !!host.find('ck-editor'));
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[0], savedAnswer('נשמר בשרת'));
  check('השמירה נחתה — הפתק שבתוך השיחה מצויר מחדש מהגרסה השמורה', lastRender(host) === 'נשמר בשרת' && host.find('ck-body').hidden === false,
    [lastRender(host), host.find('ck-body').hidden]);
  check('והעורך נשאר עם מה שהוקלד אחרי השמירה, ושורת "יש שינוי שלא נשמר" מוצגת',
    host.find('ck-editor') === ta && ta.value === 'נשמר בשרת ועוד' && host.find('ck-unsaved').hidden === false, [ta.value, host.find('ck-unsaved').hidden]);
  check('"בטל שינויים" חוזר', host.find('ck-drop').disabled === false, host.find('ck-drop').disabled);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'שלי';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[0], toolAnswer({ ok: false, error: 'conflict' }));
  answer(host, toolCalls(host, 'codekeeper_show_note')[1], toolAnswer(editNote({ content: 'של מישהו אחר', content_sha256: SHA2 })));
  host.deliver(hostContextChanged({ displayMode: 'inline' }));
  check('התנגשות ואז יציאה ממסך מלא — הפתק בתוך השיחה הוא הגרסה שבשרת, ולא זו שהעריכה נפתחה עליה',
    lastRender(host) === 'של מישהו אחר' && host.find('ck-body').hidden === false && host.find('ck-unsaved').hidden === false,
    [lastRender(host), host.find('ck-unsaved').hidden]);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'אולי';
  host.find('ck-save').dispatch('click');
  host.fire(20000);
  answer(host, toolCalls(host, 'codekeeper_show_note')[1], toolAnswer(editNote()));
  host.find('ck-cancel').dispatch('click');
  host.find('ck-discard').dispatch('click');
  check('שמירה שלא הוכרעה, והעורך נסגר בלי לשמור שוב', !host.find('ck-editor') && !host.last('ui/update-model-context'), !!host.find('ck-editor'));
  openEditorAt(host, 0, editNote({ content: 'אולי', content_sha256: SHA2 }));
  const ctx = host.last('ui/update-model-context');
  check('הפתיחה הבאה רואה שהיא נחתה בסוף — והמודל לומד עליה', ctx && ctx.message.params.content[0].text.endsWith('\nאולי'), ctx && ctx.message.params.content[0].text);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'אולי';
  host.find('ck-save').dispatch('click');
  host.fire(20000);
  answer(host, toolCalls(host, 'codekeeper_show_note')[1], toolAnswer(editNote()));
  host.find('ck-cancel').dispatch('click');
  host.find('ck-discard').dispatch('click');
  openEditorAt(host, 0, editNote({ content: 'גרסה של מישהו אחר', content_sha256: SHA2 }));
  const ta2 = host.find('ck-editor');
  ta2.value = 'חדש';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[1], toolAnswer({ ok: false, error: 'conflict' }));
  answer(host, toolCalls(host, 'codekeeper_show_note')[3], toolAnswer(editNote({ content: 'אולי', content_sha256: 'e'.repeat(64) })));
  check('גרסה אחרת בשרת מכריעה ששמירה ישנה כבר לא תנחת — גוף זהה לה אחר כך אינו נחשב "שלנו"',
    host.find('ck-conflict').hidden === false && toolCalls(host, 'codekeeper_note_view_save').length === 2 && !host.last('ui/update-model-context'),
    [host.find('ck-conflict').hidden, toolCalls(host, 'codekeeper_note_view_save').length]);
}

{
  // גם הקריאה שאחרי התקרה לא ענתה: השמירה נשארת "לא מוכרעת", והשמירה הבאה מזהה אותה אם נחתה.
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'ראשון';
  host.find('ck-save').dispatch('click');
  host.fire(20000);
  host.fire(20000);
  check('השמירה וגם הקריאה שאחריה לא ענו — הסטטוס אומר שלא ידוע, והכפתורים חוזרים',
    host.find('ck-edit-status').textContent.indexOf('לא הצלחתי לבדוק') !== -1 && host.find('ck-save').disabled === false,
    [host.find('ck-edit-status').textContent, host.find('ck-save').disabled]);
  ta.value = 'ראשון ושני';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[1], toolAnswer({ ok: false, error: 'conflict' }));
  answer(host, toolCalls(host, 'codekeeper_show_note')[2], toolAnswer(editNote({ content: 'ראשון', content_sha256: SHA2 })));
  const third = toolCalls(host, 'codekeeper_note_view_save')[2];
  check('השמירה הבאה מזהה שהראשונה נחתה — ויוצאת שוב על ה-hash שלה, בלי שורת התנגשות',
    third && third.message.params.arguments.content === 'ראשון ושני' && third.message.params.arguments.expected_content_sha256 === SHA2
      && host.find('ck-conflict').hidden === true, third && third.message.params.arguments);
}

console.log('\nטלפון: תצוגה בלבד — לפי הצלע הקצרה של המסך');
for (const [name, screen, allowed] of [
  ['טלפון לאורך (390×844)', { width: 390, height: 844 }, false],
  ['טלפון לרוחב (844×390) — רחב מטאבלט לאורך, ובכל זאת טלפון', { width: 844, height: 390 }, false],
  ['צלע קצרה 599', { width: 599, height: 1000 }, false],
  ['צלע קצרה 600 — הסף עצמו', { width: 600, height: 1000 }, true],
  ['טאבלט לאורך (800×1280)', { width: 800, height: 1280 }, true],
  ['טאבלט לרוחב (1280×800)', { width: 1280, height: 800 }, true],
  ['מסך שאינו נמדד (null)', null, false],
  ['מסך עם ערכים שאינם מספרים', { width: 'x', height: 800 }, false],
  ['מסך עם 0', { width: 0, height: 0 }, false],
]) {
  const host = load({ screen });
  initialize(host, EDIT_CTX, EDIT_CAPS);
  host.deliver(toolResult(editNote()));
  const buttonShown = host.find('ck-edit').hidden === false;
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[1] });
  const opened = toolCalls(host, 'codekeeper_show_note').length > 0;
  check(`${name} — ${allowed ? 'יש' : 'אין'} עריכה`, buttonShown === allowed && opened === allowed, [buttonShown, opened]);
  if (!allowed) {
    check(`${name} — ו"מסך מלא" עדיין מוצע`, host.find('ck-expand').hidden === false, host.find('ck-expand').hidden);
  }
}

console.log('\nכפתורי אייקון');
{
  const host = editableView();
  const expand = host.find('ck-expand');
  const icon = expand.children[0];
  check('"מסך מלא" — אייקון בלבד, ושמו בתווית ובריחוף', expand.getAttribute('aria-label') === 'מסך מלא' && expand.getAttribute('title') === 'מסך מלא'
    && expand.children.length === 1 && icon.className === 'ck-test-icon', [expand.getAttribute('aria-label'), expand.children.map((c) => c.className)]);
  check('והאייקון הוא maximize-2 של Lucide, צורה בצורה', JSON.stringify(icon.shapes) === JSON.stringify([
    ['path', { d: 'M15 3h6v6' }], ['path', { d: 'm21 3-7 7' }], ['path', { d: 'm3 21 7-7' }], ['path', { d: 'M9 21H3v-6' }]]), icon.shapes);
  const icons = ['ck-expand', 'ck-edit', 'ck-up', 'ck-down'].map((c) => host.find(c));
  check('ארבעת כפתורי השורה הם כפתורי אייקון (ck-icon)', icons.every((b) => b.className.split(' ').indexOf('ck-icon') !== -1),
    icons.map((b) => b.className));
}

console.log('\nמסך מלא: בלי שורת כפתורים');
{
  const host = editableView({ ctx: { ...EDIT_CTX, displayMode: 'fullscreen' } });
  const body = host.find('ck-body');
  body.clientHeight = 200;
  body.scrollHeight = 1000;
  host.resize();
  check('פתק ארוך במסך מלא — אין שורת כפתורים: לא ▲▼ ולא עריכה',
    host.find('ck-controls').hidden === true && host.find('ck-scroll-btns').hidden === true && host.find('ck-edit').hidden === true,
    [host.find('ck-controls').hidden, host.find('ck-scroll-btns').hidden, host.find('ck-edit').hidden]);
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[1] });
  check('ולחיצה על שורה עדיין פותחת עריכה', toolCalls(host, 'codekeeper_show_note').length === 1, host.methods().slice(-2));
  host.deliver(hostContextChanged({ displayMode: 'inline' }));
}
{
  const host = editableView();
  host.deliver(hostContextChanged({ displayMode: 'fullscreen' }));
  host.deliver(hostContextChanged({ displayMode: 'inline' }));
  check('חזרה לשיחה — השורה חוזרת עם "מסך מלא" ועריכה', host.find('ck-controls').hidden === false && host.find('ck-expand').hidden === false
    && host.find('ck-edit').hidden === false, [host.find('ck-controls').hidden, host.find('ck-expand').hidden, host.find('ck-edit').hidden]);
}

console.log('\nהשטח הגלוי → משתני CSS');
{
  const host = load({ visualViewport: true });
  initialize(host, EDIT_CTX, EDIT_CAPS);
  host.deliver(toolResult(editNote()));
  const props = host.document.documentElement.style.props;
  check('אחרי לחיצת היד — הגובה הגלוי והמרחק שלו מראש הפריסה', props['--ck-vv-height'] === '600px' && props['--ck-vv-top'] === '0px', props);
  host.vv.move(300, 120);
  check('המקלדת נפתחה (השטח קטן וזז) — המשתנים מתעדכנים', props['--ck-vv-height'] === '300px' && props['--ck-vv-top'] === '120px', props);
  for (const [h, t] of [[NaN, 0], [300, -5], [0, 0], ['300', 0]]) {
    host.vv.move(h, t);
    check(`ערכים לא תקינים (${String(h)}, ${String(t)}) — המשתנים יורדים, וה-CSS חוזר למסגרת כולה`,
      !('--ck-vv-height' in props) && !('--ck-vv-top' in props), props);
  }
}
{
  const host = editableView();
  const props = host.document.documentElement.style.props;
  check('בלי visualViewport — שום משתנה, העורך ממלא את המסגרת כמו קודם', !('--ck-vv-height' in props) && !('--ck-vv-top' in props), props);
}

console.log('\nמצב עריכה ב-CSS, והסמן לפני הפוקוס');
{
  const host = editableView();
  const docEl = host.document.documentElement;
  check('לפני עריכה — אין ck-editing', !docEl.classList.contains('ck-editing'), docEl.className);
  const ta = openEditorAt(host, 2);
  check('העורך מוצג — ck-editing על html', docEl.classList.contains('ck-editing'), docEl.className);
  const offset = LINES[0].length + LINES[1].length + 2;
  check('הסמן הוצב לפני הפוקוס — כך הפוקוס גולל את התיבה אליו', ta.selectionAtFocus && ta.selectionAtFocus[0] === offset, ta.selectionAtFocus);
  ta.value = 'שינוי';
  host.deliver(hostContextChanged({ displayMode: 'inline' }));
  check('יציאה ממסך מלא עם שינוי — העורך נשאר בזיכרון, אבל ck-editing יורד', host.find('ck-editor') === ta && !docEl.classList.contains('ck-editing'),
    docEl.className);
  host.find('ck-drop').dispatch('click');
  check('והעורך נסגר — עדיין בלי ck-editing', !host.find('ck-editor') && !docEl.classList.contains('ck-editing'), docEl.className);
}
{
  const host = editableView();
  openEditorAt(host, 1);
  host.find('ck-cancel').dispatch('click');
  check('"בטל" במסך מלא — ck-editing יורד', !host.document.documentElement.classList.contains('ck-editing'), host.document.documentElement.className);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'שינוי';
  host.find('ck-save').dispatch('click');
  check('"שומר…" — שורת הסטטוס מוצגת', host.find('ck-edit-status').hidden === false && host.find('ck-edit-status').textContent === 'שומר…',
    [host.find('ck-edit-status').hidden, host.find('ck-edit-status').textContent]);
}

console.log('\nמצב מדידה (layout_debug)');
{
  const host = editableView();
  check('בלי layout_debug — אין שורת מדידה', !host.find('ck-debug'), !!host.find('ck-debug'));
}
{
  const host = load({ visualViewport: true });
  initialize(host, { ...EDIT_CTX, containerDimensions: { width: 600, maxHeight: 900 }, safeAreaInsets: { top: 10, right: 0, bottom: 48, left: 0 } }, EDIT_CAPS);
  host.deliver(toolResult({ ...editNote(), layout_debug: true }));
  const debug = host.find('ck-debug');
  check('layout_debug: true — שורת מדידה משמאל לימין, אחרי שורת הראש', debug && debug.getAttribute('dir') === 'ltr'
    && host.find('ck-paper').children.indexOf(debug) === 1, debug && debug.getAttribute('dir'));
  const text = debug.textContent;
  check('המספרים: השטח הגלוי, החלון, המסך, ומה שהמארח מסר', /vv h=600 top=0/.test(text) && /inner 600x/.test(text) && /screen 1280x800 edit=true/.test(text)
    && /mode=inline dims=\{"width":600,"maxHeight":900\} safe=\{"top":10,"right":0,"bottom":48,"left":0\}/.test(text), text);
  check('ובלי תוכן הפתק', LINES.every((line) => text.indexOf(line) === -1), text);
  host.vv.move(300, 120);
  check('המקלדת נפתחה — המספרים מתעדכנים', /vv h=300 top=120/.test(host.find('ck-debug').textContent), host.find('ck-debug').textContent);
  openEditorAt(host, 1);
  check('העריכה נפתחה (קריאה טרייה בלי layout_debug) — שורת המדידה נשארת, ועם תיבת הטקסט',
    !!host.find('ck-debug') && /editor /.test(host.find('ck-debug').textContent), host.find('ck-debug') && host.find('ck-debug').textContent);
}
{
  for (const value of ['true', 1, {}, null]) {
    const host = editableView({ note: { ...editNote(), layout_debug: value } });
    check(`layout_debug שאינו בדיוק true (${JSON.stringify(value)}) — אין שורת מדידה`, !host.find('ck-debug'), !!host.find('ck-debug'));
  }
}

console.log('\nביטול, ויציאה ממסך מלא');
{
  const host = editableView();
  openEditorAt(host, 1);
  host.find('ck-cancel').dispatch('click');
  check('"בטל" בלי שינוי — העורך נסגר בלי לשאול ובלי לשמור', !host.find('ck-editor') && toolCalls(host, 'codekeeper_note_view_save').length === 0
    && host.find('ck-body').hidden === false, [!!host.find('ck-editor'), host.methods().slice(-2)]);
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'שינוי';
  host.find('ck-cancel').dispatch('click');
  check('"בטל" עם שינוי — שאלה בתוך הדף, והעורך עדיין פתוח', host.find('ck-confirm').hidden === false && host.find('ck-editor') === ta,
    host.find('ck-confirm').hidden);
  host.find('ck-keep').dispatch('click');
  check('"להמשיך לערוך" — השאלה נעלמת והטקסט נשאר', host.find('ck-confirm').hidden === true && ta.value === 'שינוי', ta.value);
  host.find('ck-cancel').dispatch('click');
  host.find('ck-discard').dispatch('click');
  check('"כן, לבטל" — העורך נסגר, בלי שמירה, והפתק המקורי מוצג', !host.find('ck-editor') && toolCalls(host, 'codekeeper_note_view_save').length === 0
    && host.mdCalls[host.mdCalls.length - 1].text === LINES.join('\n'), [!!host.find('ck-editor'), host.mdCalls.length]);
}
{
  const host = editableView();
  openEditorAt(host, 1);
  host.deliver(hostContextChanged({ displayMode: 'inline' }));
  check('יציאה ממסך מלא בלי שינוי — העורך נסגר', !host.find('ck-editor') && host.find('ck-body').hidden === false, !!host.find('ck-editor'));
}
{
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'לא נשמר';
  host.deliver(hostContextChanged({ displayMode: 'inline' }));
  check('יציאה ממסך מלא עם שינוי — הטקסט שמור בזיכרון, והפתק מוצג עם שורה שאומרת שיש שינוי',
    host.find('ck-editor') === ta && ta.hidden === true && host.find('ck-unsaved').hidden === false && host.find('ck-body').hidden === false
      && host.find('ck-edit-bar').hidden === true, [ta.hidden, host.find('ck-unsaved').hidden, host.find('ck-body').hidden]);
  host.find('ck-resume').dispatch('click');
  const fs = host.last('ui/request-display-mode');
  check('"המשך עריכה" — בקשה למסך מלא מתוך הלחיצה', fs && fs.message.params.mode === 'fullscreen', host.methods().slice(-2));
  answer(host, fs, { mode: 'fullscreen' });
  check('ואחריה — העורך חוזר עם הטקסט', ta.hidden === false && ta.value === 'לא נשמר' && host.find('ck-unsaved').hidden === true && FakeElement.focused === ta,
    [ta.hidden, ta.value]);
  host.deliver(hostContextChanged({ displayMode: 'inline' }));
  host.find('ck-drop').dispatch('click');
  check('"בטל שינויים" בשורה שבתוך השיחה — העורך נסגר בלי שמירה', !host.find('ck-editor') && toolCalls(host, 'codekeeper_note_view_save').length === 0,
    !!host.find('ck-editor'));
}

console.log('\nכניסה לעריכה במסך מגע — בלי דחיפה של המסגרת');
// ``KEYBOARD_REPORT_DEADLINE_MS`` ב-``note_view.js``: השעון המזויף יורה רק טיימר באורך הזה בדיוק, ולכן
// שינוי של הקבוע מפיל את הבדיקה של התקרה — ולא עובר בשקט.
const KEYBOARD_DEADLINE = 1500;
const KEYBOARD_INSETS = (bottom) => ({ safeAreaInsets: { top: 120, right: 0, bottom, left: 0 } });
/** מסך מלא בגובה קבוע (``ck-fill``), כמו ש-Claude מוסר, ופתיחה של העורך מלחיצה על שורה. */
function touchEditor(opts = {}) {
  const host = load({ coarse: opts.coarse === undefined ? true : opts.coarse });
  initialize(host, { ...EDIT_CTX, ...KEYBOARD_INSETS(195) }, EDIT_CAPS);
  host.deliver(toolResult(opts.debug ? { ...editNote(), layout_debug: true } : editNote()));
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[2] });
  answer(host, host.last('ui/request-display-mode'), { mode: 'fullscreen' });
  host.deliver(hostContextChanged({ displayMode: 'fullscreen', containerDimensions: { width: 1400, height: 924 } }));
  answer(host, toolCalls(host, 'codekeeper_show_note').pop(), toolAnswer(editNote()));
  return host;
}
{
  const host = touchEditor({ debug: true });
  const ta = host.find('ck-editor');
  const docEl = host.document.documentElement;
  check('מסך מגע — הריפוד הזמני כבר על התיבה ברגע הפוקוס, כלומר לפני שהמקלדת נקראת',
    ta && /\bck-opening\b/.test(ta.classAtFocus || '') && ta.classList.contains('ck-opening'), ta && ta.classAtFocus);
  check('הקו התחתון של העריכה — השוליים שהמארח מסר בפתיחה', docEl.style.props['--ck-edit-bottom'] === '195px', docEl.style.props['--ck-edit-bottom']);
  host.deliver(hostContextChanged(KEYBOARD_INSETS(543)));
  check('המקלדת דווחה (השוליים גדלו) — הריפוד הזמני יורד, והקו התחתון עולה אליה',
    !ta.classList.contains('ck-opening') && docEl.style.props['--ck-edit-bottom'] === '543px', [ta.className, docEl.style.props['--ck-edit-bottom']]);
  check('ומצב המדידה אומר שזה הגיע מדיווח', /kb=reported/.test(host.find('ck-debug').textContent) && /edit-bottom=543/.test(host.find('ck-debug').textContent),
    host.find('ck-debug').textContent);
  host.deliver(hostContextChanged(KEYBOARD_INSETS(195)));
  check('המקלדת נסגרה באמצע עריכה — הקו התחתון נשאר בגובה שלה', docEl.style.props['--ck-edit-bottom'] === '543px', docEl.style.props['--ck-edit-bottom']);
  host.deliver(hostContextChanged({ containerDimensions: { width: 1400, height: 924 }, ...KEYBOARD_INSETS(195) }));
  check('אותה מסגרת שנשלחה שוב עם השוליים — עדיין לא מתאפס', docEl.style.props['--ck-edit-bottom'] === '543px', docEl.style.props['--ck-edit-bottom']);
  host.deliver(hostContextChanged({ containerDimensions: { width: 924, height: 1400 }, ...KEYBOARD_INSETS(195) }));
  check('מסגרת בגודל אחר (סיבוב) — הקו התחתון חוזר לשוליים של עכשיו', docEl.style.props['--ck-edit-bottom'] === '195px', docEl.style.props['--ck-edit-bottom']);
  host.find('ck-cancel').dispatch('click');
  check('יציאה מהעריכה — בלי קו תחתון של עריכה', !host.find('ck-editor') && !('--ck-edit-bottom' in docEl.style.props), docEl.style.props);
}
{
  // **סיבוב שההודעה עליו אינה נושאת שוליים** — השוליים שבזיכרון הם של הכיוון הקודם. הם ממשיכים לשמש
  // לפריסה עד הדיווח הבא, אבל אינם רצפה לו: המקלדת של הכיוון החדש יכולה להיות נמוכה יותר.
  const host = touchEditor();
  const docEl = host.document.documentElement;
  host.deliver(hostContextChanged(KEYBOARD_INSETS(543)));
  host.deliver(hostContextChanged({ containerDimensions: { width: 924, height: 1400 } }));
  check('סיבוב בלי שוליים בהודעה — עד הדיווח הבא, הקו לפי השוליים הישנים', docEl.style.props['--ck-edit-bottom'] === '543px',
    docEl.style.props['--ck-edit-bottom']);
  host.deliver(hostContextChanged(KEYBOARD_INSETS(400)));
  check('והדיווח הבא נקבע גם כשהוא קטן מהם — המקלדת של הכיוון החדש', docEl.style.props['--ck-edit-bottom'] === '400px',
    docEl.style.props['--ck-edit-bottom']);
  host.deliver(hostContextChanged(KEYBOARD_INSETS(195)));
  check('ומשם הזיכרון עובד כרגיל — המקלדת נסגרה, הקו נשאר', docEl.style.props['--ck-edit-bottom'] === '400px',
    docEl.style.props['--ck-edit-bottom']);
}
{
  const host = touchEditor({ debug: true });
  const ta = host.find('ck-editor');
  host.fire(KEYBOARD_DEADLINE);
  check('בלי דיווח על מקלדת (מקלדת פיזית) — הריפוד הזמני יורד בתקרת הזמן', !ta.classList.contains('ck-opening'), ta.className);
  check('ומצב המדידה אומר שזו הייתה התקרה', /kb=deadline/.test(host.find('ck-debug').textContent), host.find('ck-debug').textContent);
}
{
  const host = touchEditor();
  const timer = host.timers.find((t) => t.ms === KEYBOARD_DEADLINE);
  host.find('ck-cancel').dispatch('click');
  check('יציאה מהעריכה בזמן ההמתנה — הטיימר מתבטל', !!timer && timer.cleared === true, timer);
}
{
  const host = touchEditor({ coarse: false });
  const ta = host.find('ck-editor');
  check('מחשב (מצביע מדויק) — אין ריפוד זמני ואין תקרת זמן', ta &&!/\bck-opening\b/.test(ta.classAtFocus || '') && !host.timers.some((t) => t.ms === KEYBOARD_DEADLINE),
    ta && ta.classAtFocus);
}
{
  const host = load({ coarse: true });
  initialize(host, { ...EDIT_CTX, containerDimensions: { width: 1400, maxHeight: 6000 } }, EDIT_CAPS);
  host.deliver(toolResult(editNote()));
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[2] });
  answer(host, host.last('ui/request-display-mode'), { mode: 'fullscreen' });
  answer(host, toolCalls(host, 'codekeeper_show_note').pop(), toolAnswer(editNote()));
  const ta = host.find('ck-editor');
  check('מסך מלא בגובה גמיש (ck-expanded) — אין ריפוד זמני גם במסך מגע', ta && !/\bck-opening\b/.test(ta.classAtFocus || ''), ta && ta.classAtFocus);
}

// ── סימון קטע (``highlight`` מ-``codekeeper_show_note``) ─────────────────────────────────

const SECTION_LINES = ['# מדריך', 'פתיחה', '## התקנה', 'שלב ראשון', '### פרטים', 'פרט פנימי', '## שימוש', 'הפעלה'];
const MARK_INVALID = 'הסימון שהתבקש לא הגיע בצורה תקינה, ולכן הפתק מוצג בלי סימון.';
/** פתק עם ``highlight`` — בצורה ש-``_note_highlight`` ב-``mcp_server/handlers.py`` מחזיר. */
const marked = (highlight, lines = SECTION_LINES, base = NOTE) => ({ ...base, note: { ...base.note, content: lines.join('\n') }, highlight });
const sectionMark = (a, b, title = 'התקנה') => ({ kind: 'section', title, line_range: [a, b] });
const queryMark = (query) => ({ kind: 'query', query });
const hlCalls = (host, fn) => host.hl.calls.filter((c) => c.fn === fn);

console.log('\nסימון קטע — section');
{
  const host = load();
  initialize(host);
  host.deliver(toolResult(marked(sectionMark(3, 6))));
  const rows = host.findAll('sticky-task-line');
  const content = host.find('ck-content');
  const opened = host.detailsCalls.map((c) => rows.indexOf(c.node));
  check('השורות 3–6 בדיוק (מהכותרת ועד לפני הכותרת הבאה ברמתה) — כל אחת עוברת ב-openDetailsAround, בתוך התוכן',
    JSON.stringify(opened) === '[2,3,4,5]' && host.detailsCalls.every((c) => c.root === content), opened);
  const frames = host.findAll('ck-section-frame');
  check('מסגרת אחת, בתוך מכל התוכן, מוסתרת מקורא מסך',
    frames.length === 1 && frames[0].parentNode === content && frames[0].getAttribute('aria-hidden') === 'true',
    frames.map((f) => [f.parentNode && f.parentNode.className, f.getAttribute('aria-hidden')]));
  check('הנייר נושא ck-has-frame — הגוף מפנה מקום למסגרת', host.find('ck-paper').classList.contains('ck-has-frame'), host.find('ck-paper').className);
  check('קטע אינו מדגיש טקסט, ואין "הקודם/הבא"', hlCalls(host, 'highlightWithin').length === 0 && host.find('ck-mark-nav').hidden === true,
    [hlCalls(host, 'highlightWithin').length, host.find('ck-mark-nav').hidden]);
  check('בלי הודעה מתחת לפתק', host.find('ck-notice').hidden === true, host.find('ck-notice').textContent);
}
{
  const host = load();
  initialize(host);
  host.deliver(toolResult(marked(sectionMark(7, 8, 'שימוש'))));
  const rows = host.findAll('sticky-task-line');
  check('קטע בסוף הפתק — שתי השורות האחרונות', JSON.stringify(host.detailsCalls.map((c) => rows.indexOf(c.node))) === '[6,7]',
    host.detailsCalls.map((c) => rows.indexOf(c.node)));
}
{
  const host = load();
  initialize(host);
  host.deliver(toolResult(marked(sectionMark(1, 8, 'מדריך'))));
  check('קטע מהשורה הראשונה ועד הסוף — כל השורות', host.detailsCalls.length === SECTION_LINES.length, host.detailsCalls.length);
}
{
  const host = load();
  initialize(host);
  host.deliver(toolResult(marked({ kind: 'section', title: 7, line_range: [3, 6] })));
  check('title שאינו מחרוזת אינו פוסל את הסימון — הוא רק לא מוצג', host.findAll('ck-section-frame').length === 1 && host.find('ck-notice').hidden === true,
    [host.findAll('ck-section-frame').length, host.find('ck-notice').textContent]);
}

console.log('\nסימון קטע — צורה שהשרת אינו מייצר');
{
  const BAD = ['x', 5, [1, 2], null, {},
    { kind: 'section', line_range: [0, 2] }, { kind: 'section', line_range: [3, 2] }, { kind: 'section', line_range: [1.5, 2] },
    { kind: 'section', line_range: ['1', 2] }, { kind: 'section', line_range: [1] }, { kind: 'section', line_range: [1, 2, 3] },
    { kind: 'section', line_range: [null, 2] }, { kind: 'section', line_range: '1-2' }, { kind: 'section' },
    { kind: 'query', query: '' }, { kind: 'query', query: 5 }, { kind: 'query' }, { kind: 'other', query: 'x' }];
  for (const bad of BAD) {
    const host = load();
    initialize(host);
    host.deliver(toolResult(marked(bad)));
    check(`highlight ${JSON.stringify(bad)} — הפתק מוצג בלי סימון, והודעה אומרת את זה`,
      !!host.find('ck-paper') && host.findAll('ck-section-frame').length === 0 && hlCalls(host, 'highlightWithin').length === 0
        && host.find('ck-notice').textContent === MARK_INVALID && host.find('ck-notice').hidden === false,
      [!!host.find('ck-paper'), host.findAll('ck-section-frame').length, host.find('ck-notice') && host.find('ck-notice').textContent]);
  }
}
{
  const host = load();
  initialize(host);
  host.deliver(toolResult(NOTE));
  check('בלי highlight — בלי סימון ובלי הודעה', host.findAll('ck-section-frame').length === 0 && hlCalls(host, 'highlightWithin').length === 0
    && host.find('ck-notice').hidden === true, host.find('ck-notice').textContent);
}

console.log('\nסימון קטע — query, והקודם/הבא');
{
  const host = load();
  initialize(host);
  host.deliver(toolResult(marked(queryMark('tool'), ['Tool אחד', 'בלי', 'tool שני וגם TOOL'])));
  const content = host.find('ck-content');
  const body = host.find('ck-body');
  const call = hlCalls(host, 'highlightWithin')[0];
  check('highlightWithin על התוכן — אותה מחלקה ואותו דילוג כמו בחיפוש בתוך פתק בוובאפ',
    call && call.root === content && call.term === 'tool' && call.opts.className === 'sticky-note-search-hit' && call.opts.skip === '.sticky-md-generated',
    call && [call.term, call.opts]);
  const hits = host.findAll('sticky-note-search-hit');
  check('שלוש התאמות; הראשונה פעילה', hits.length === 3 && hits[0].classList.contains('is-active') && !hits[1].classList.contains('is-active'),
    hits.map((h) => h.className));
  check('בלוק מתקפל סביב הראשונה נפתח, והגוף נגלל אליה', host.detailsCalls.length === 1 && host.detailsCalls[0].node === hits[0]
    && hlCalls(host, 'scrollIntoViewWithin').length === 1 && hlCalls(host, 'scrollIntoViewWithin')[0].root === body
    && hlCalls(host, 'scrollIntoViewWithin')[0].hit === hits[0], hlCalls(host, 'scrollIntoViewWithin').length);
  check('"הקודם/הבא" מוצגים עם מונה 1/3, והשורה מוצגת בגללם', host.find('ck-mark-nav').hidden === false && host.find('ck-mark-count').textContent === '1/3'
    && host.find('ck-controls').hidden === false, [host.find('ck-mark-nav').hidden, host.find('ck-mark-count').textContent, host.find('ck-controls').hidden]);
  check('כפתורי טקסט, עם הסבר ב-title', host.find('ck-mark-prev').textContent === 'הקודם' && host.find('ck-mark-next').textContent === 'הבא'
    && host.find('ck-mark-prev').getAttribute('title') === 'ההתאמה הקודמת' && host.find('ck-mark-next').getAttribute('title') === 'ההתאמה הבאה',
    [host.find('ck-mark-prev').textContent, host.find('ck-mark-next').textContent]);
  host.find('ck-mark-next').dispatch('click');
  const scrolls = hlCalls(host, 'scrollIntoViewWithin');
  check('"הבא" — 2/3, השנייה פעילה, הבלוק שלה נפתח והגוף נגלל אליה', host.find('ck-mark-count').textContent === '2/3'
    && hits[1].classList.contains('is-active') && !hits[0].classList.contains('is-active')
    && host.detailsCalls[host.detailsCalls.length - 1].node === hits[1] && scrolls[scrolls.length - 1].hit === hits[1],
    host.find('ck-mark-count').textContent);
  host.find('ck-mark-prev').dispatch('click');
  host.find('ck-mark-prev').dispatch('click');
  check('"הקודם" מהראשונה — חוזר לאחרונה (3/3), במעגל', host.find('ck-mark-count').textContent === '3/3' && hits[2].classList.contains('is-active'),
    host.find('ck-mark-count').textContent);
  host.find('ck-mark-next').dispatch('click');
  check('"הבא" מהאחרונה — חוזר לראשונה (1/3)', host.find('ck-mark-count').textContent === '1/3' && hits[0].classList.contains('is-active'),
    host.find('ck-mark-count').textContent);
}
{
  const host = load();
  initialize(host);
  host.deliver(toolResult(marked(queryMark('שני'), ['tool אחד', 'tool שני'])));
  check('התאמה אחת — מסומנת, בלי "הקודם/הבא", ובלי שורת כפתורים', host.findAll('sticky-note-search-hit').length === 1
    && host.find('ck-mark-nav').hidden === true && host.find('ck-controls').hidden === true,
    [host.findAll('sticky-note-search-hit').length, host.find('ck-mark-nav').hidden, host.find('ck-controls').hidden]);
}

console.log('\nסימון קטע — במסך מלא: שורה רק עם "הקודם/הבא"');
{
  const host = load();
  initialize(host, { availableDisplayModes: ['inline', 'fullscreen'], displayMode: 'fullscreen' }, EDIT_CAPS);
  host.deliver(toolResult(marked(queryMark('tool'), ['tool אחד', 'tool שני'], editNote())));
  check('כמה התאמות — השורה מוצגת, ובה רק "הקודם/הבא"', host.find('ck-controls').hidden === false && host.find('ck-mark-nav').hidden === false
    && host.find('ck-expand').hidden === true && host.find('ck-edit').hidden === true && host.find('ck-scroll-btns').hidden === true,
    ['ck-controls', 'ck-mark-nav', 'ck-expand', 'ck-edit', 'ck-scroll-btns'].map((c) => host.find(c).hidden));
}
{
  const host = load();
  initialize(host, { availableDisplayModes: ['inline', 'fullscreen'], displayMode: 'fullscreen' }, EDIT_CAPS);
  host.deliver(toolResult(marked(queryMark('אחד'), ['tool אחד', 'tool שני'], editNote())));
  check('התאמה אחת — אין שורה במסך מלא, כמו בלי סימון', host.find('ck-controls').hidden === true, host.find('ck-controls').hidden);
}

console.log('\nסימון קטע — לא נמצא בטקסט המוצג');
{
  const host = load();
  initialize(host);
  // השרת מצא את "tool" בכתובת של הקישור; בתצוגה רק התווית.
  host.deliver(toolResult(marked(queryMark('tool'), ['[קישור](https://example.com/tool)', 'שורה'])));
  const notice = host.find('ck-notice');
  check('הודעה מתחת לפתק, בלי "הקודם/הבא"', notice.hidden === false && notice.textContent === '"tool" לא נמצא בטקסט המוצג, ולכן הפתק מוצג בלי סימון.'
    && /\bis-error\b/.test(notice.className) && host.find('ck-mark-nav').hidden === true, [notice.textContent, notice.className]);
  const ctx = host.sent.filter((s) => s.message.method === 'ui/update-model-context');
  const text = ctx.length === 1 ? ctx[0].message.params.content[0].text : '';
  check('Claude לומד שהסימון לא עבד (ui/update-model-context) — המזהה, ה-query, ומה לעשות',
    ctx.length === 1 && text.indexOf('note_id: ' + NOTE.note.id) !== -1 && text.indexOf('"tool"') !== -1 && text.indexOf('codekeeper_show_note') !== -1
      && text.indexOf('section=') !== -1, text);
  check('בלי גלילה ובלי פתיחת בלוקים', hlCalls(host, 'scrollIntoViewWithin').length === 0 && host.detailsCalls.length === 0,
    [hlCalls(host, 'scrollIntoViewWithin').length, host.detailsCalls.length]);
}
{
  const host = load();
  initialize(host);
  host.deliver(toolResult(marked(sectionMark(20, 21, 'פרק'))));
  check('קטע שאין לו שורות בתצוגה — הודעה עם שם הקטע, ובלי מסגרת', host.find('ck-notice').textContent === '"פרק" לא נמצא בטקסט המוצג, ולכן הפתק מוצג בלי סימון.'
    && host.findAll('ck-section-frame').length === 0 && !host.find('ck-paper').classList.contains('ck-has-frame'),
    host.find('ck-notice').textContent);
}
{
  // אחרי שמירה המקום של הדף אצל המודל תפוס בגוף העדכני — הודעה על סימון הייתה מוחקת אותו.
  const host = editableView();
  const ta = openEditorAt(host, 1);
  ta.value = 'שורה ראשונה\nערוכה\nשורה שלישית';
  host.find('ck-save').dispatch('click');
  answer(host, toolCalls(host, 'codekeeper_note_view_save')[0], savedAnswer(ta.value));
  const before = host.sent.filter((s) => s.message.method === 'ui/update-model-context').length;
  host.deliver(toolResult(marked(queryMark('tool'), ['[קישור](https://example.com/tool)'], editNote())));
  check('אחרי שמירה — ההודעה למשתמש מוצגת, ו-Claude אינו מקבל עדכון שידרוס את הגוף השמור',
    before === 1 && host.sent.filter((s) => s.message.method === 'ui/update-model-context').length === 1
      && host.find('ck-notice').textContent.indexOf('לא נמצא בטקסט המוצג') !== -1,
    [before, host.sent.filter((s) => s.message.method === 'ui/update-model-context').length, host.find('ck-notice').textContent]);
}

console.log('\nסימון קטע — עריכה מסירה אותו');
{
  const host = editableView({ note: marked(sectionMark(1, 2, 'x'), LINES, editNote()) });
  check('לפני העריכה — מסגרת', host.findAll('ck-section-frame').length === 1, host.findAll('ck-section-frame').length);
  openEditorAt(host, 1, marked(undefined, LINES, editNote()));
  check('בכניסה לעריכה — המסגרת יוצאת, והגוף כבר לא מפנה לה מקום', host.findAll('ck-section-frame').length === 0
    && !host.find('ck-paper').classList.contains('ck-has-frame'), [host.findAll('ck-section-frame').length, host.find('ck-paper').className]);
  host.find('ck-cancel').dispatch('click');
  check('ביציאה מהעריכה — הפתק בלי סימון', !host.find('ck-editor') && host.findAll('ck-section-frame').length === 0,
    [!!host.find('ck-editor'), host.findAll('ck-section-frame').length]);
}
{
  const host = editableView({ note: marked(queryMark('שורה'), LINES, editNote()) });
  check('לפני העריכה — שלוש התאמות ו"הקודם/הבא"', host.findAll('sticky-note-search-hit').length === 3 && host.find('ck-mark-nav').hidden === false,
    host.findAll('sticky-note-search-hit').length);
  const ta = openEditorAt(host, 0, marked(undefined, LINES, editNote()));
  check('בכניסה לעריכה — ההדגשות יוצאות מהתוכן', host.findAll('sticky-note-search-hit').length === 0
    && hlCalls(host, 'clearHighlights').some((c) => c.root === host.find('ck-content')), host.findAll('sticky-note-search-hit').length);
  ta.value = LINES.join('\n') + '\nעוד';
  host.deliver({ jsonrpc: '2.0', method: 'ui/notifications/host-context-changed', params: { displayMode: 'inline' } });
  check('יציאה ממסך מלא עם שינוי שלא נשמר — הגוף חוזר בלי הדגשות ובלי "הקודם/הבא"', host.find('ck-body').hidden === false
    && host.findAll('sticky-note-search-hit').length === 0 && host.find('ck-mark-nav').hidden === true,
    [host.find('ck-body').hidden, host.findAll('sticky-note-search-hit').length, host.find('ck-mark-nav').hidden]);
}
{
  // הקריאה הטרייה של העריכה הראתה שהפתק השתנה, ו-Claude לא פתח מסך מלא — הפתק החדש מוצג בלי הסימון.
  const host = editableView({ note: marked(sectionMark(1, 2, 'x'), LINES, editNote()) });
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[0] });
  answer(host, host.last('ui/request-display-mode'), { mode: 'inline' });
  answer(host, toolCalls(host, 'codekeeper_show_note').pop(), toolAnswer({ ...editNote(), note: { ...editNote().note, content: 'אחר\nלגמרי', content_sha256: SHA2 } }));
  check('גרסה אחרת — בלי מסגרת, ובלי הודעה שהסימון "לא נמצא"', host.mdCalls[host.mdCalls.length - 1].text === 'אחר\nלגמרי'
    && host.findAll('ck-section-frame').length === 0 && host.find('ck-notice').textContent.indexOf('לא נמצא') === -1,
    [host.findAll('ck-section-frame').length, host.find('ck-notice').textContent]);
}
{
  const host = editableView({ note: marked(sectionMark(1, 2, 'x'), LINES, editNote()) });
  host.find('ck-body').dispatch('click', { target: host.findAll('sticky-task-line')[0] });
  answer(host, host.last('ui/request-display-mode'), { mode: 'inline' });
  answer(host, toolCalls(host, 'codekeeper_show_note').pop(), toolAnswer(editNote()));
  check('אותה גרסה, והעריכה לא נפתחה — הסימון נשאר', !host.find('ck-editor') && host.findAll('ck-section-frame').length === 1,
    [!!host.find('ck-editor'), host.findAll('ck-section-frame').length]);
}

console.log('\nסימון קטע — סירובים של השרת');
{
  const TEXTS = {
    section_not_found: 'הכותרת שהתבקשה לסימון לא נמצאה בפתק.',
    ambiguous_section: 'הכותרת שהתבקשה לסימון מופיעה בפתק יותר מפעם אחת.',
    no_match: 'הטקסט שהתבקש לסימון לא מופיע בפתק.',
    section_and_query: 'אפשר לסמן כותרת או טקסט, לא את שניהם יחד.',
  };
  for (const [code, text] of Object.entries(TEXTS)) {
    const host = load();
    initialize(host);
    host.deliver(toolResult({ ok: false, error: code, suggestions: ['התקנה'] }));
    check(`${code} — הודעה בעברית, בלי פתק`, host.main.textContent === text && !host.find('ck-paper'), host.main.textContent);
  }
}

console.log('\nסימון קטע — בלי מודול ההדגשה');
{
  const host = load({ noHighlighter: true });
  initialize(host);
  host.deliver(toolResult(NOTE));
  check('בלי TextHighlight — הודעה, כמו בלי המנוע', host.main.textContent.indexOf('לא נטענה במלואה') !== -1 && !host.find('ck-paper'), host.main.textContent);
  for (const missing of ['highlightWithin', 'hitsWithin', 'setActive', 'clearHighlights', 'scrollIntoViewWithin', 'isRendered']) {
    const h = load({ highlighterOmit: [missing] });
    initialize(h);
    h.deliver(toolResult(NOTE));
    check(`TextHighlight בלי ${missing} — הודעה`, h.main.textContent.indexOf('לא נטענה במלואה') !== -1 && !h.find('ck-paper'), h.main.textContent);
  }
}

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
