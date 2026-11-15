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
  const win = {
    document,
    parent,
    innerWidth: 600,
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
  const unobserved = [];
  if (opts.resizeObserver) {
    win.ResizeObserver = class {
      constructor(cb) { this.cb = cb; }
      observe(el) { observed.push(el); }
      unobserve(el) { unobserved.push(el); }
    };
  }
  // **דמה של מנוע התצוגה**, בחוזה שלו: ``render(container, text)`` מנקה את המכל ובונה אותו מהטקסט,
  // רק עם ``createElement`` ו-``textContent``. שורה שכולה ``[תווית](כתובת)`` הופכת לקישור, כמו במנוע.
  // המנוע האמיתי נבדק בדפדפן (``tests/test_mcp_note_view_browser.py``) ובבדיקות שלו; כאן — מה שהדף
  // עושה סביבו. ``opts.engineOmit`` — מנוע שחסר בו חלק מהחוזה (דף שנבנה עם מנוע אחר).
  const mdCalls = [];
  if (!opts.noEngine) {
    const engine = {
      MD_SAFE_LINK: /^https?:\/\//i,
      render(container, text) {
        mdCalls.push({ container, text });
        container.textContent = '';
        for (const line of String(text).split('\n')) {
          const row = document.createElement('div');
          row.className = 'sticky-task-line';
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
  const sandbox = { window: win, JSON, Object, Array, Math, String };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  const host = {
    win, document, main, sent, created, timers, observed, unobserved, parent, zoom, mdCalls,
    deliver(data, source = parent) { for (const fn of listeners) fn({ source, data }); },
    methods() { return sent.map((s) => s.message.method || (s.message.error ? 'error' : 'result')); },
    last(method) { return [...sent].reverse().find((s) => s.message.method === method); },
    fire(ms) { for (const t of timers) if (t.ms === ms && !t.cleared) t.fn(); },
    /** המארח משנה את המסגרת — מה שהדפדפן מודיע עליו ב-``resize`` של החלון שבתוכה. */
    resize() { for (const fn of resizeListeners) fn({ type: 'resize' }); },
    find(cls) {
      for (const el of html.walk()) if (el.className.split(/\s+/).indexOf(cls) !== -1) return el;
      return null;
    },
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
  const title = paper.children[0];
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
  check('בלי כותרת ריקה', !paper.children.some((c) => c.className === 'ck-title'), paper.children.map((c) => c.className));
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
  for (const missing of ['render', 'MD_SAFE_LINK']) {
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

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
