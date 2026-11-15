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
  dispatch(type) { for (const fn of this.listeners[type] || []) fn({ type }); }
  scrollBy(options) { this.scrolls.push(options); this.scrollTop += options.top; }
  set textContent(value) { this.children = []; this._text = String(value); }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(''); }
  appendChild(child) { this.children.push(child); return child; }
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
  const win = {
    document,
    parent,
    innerWidth: 600,
    addEventListener(type, fn) {
      if (type === 'message') listeners.push(fn);
      if (type === 'resize') resizeListeners.push(fn);
    },
    setTimeout(fn, ms) { timers.push({ fn, ms, cleared: false }); return timers.length; },
    clearTimeout(handle) { if (timers[handle - 1]) timers[handle - 1].cleared = true; },
  };
  if (opts.resizeObserver) {
    win.ResizeObserver = class { constructor(cb) { this.cb = cb; } observe(el) { observed.push(el); } };
  }
  const sandbox = { window: win, JSON, Object, Array, Math, String };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  const host = {
    win, document, main, sent, created, timers, observed, parent,
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

function initialize(host, hostContext) {
  const init = host.sent[0].message;
  host.deliver({ jsonrpc: '2.0', id: init.id, result: { protocolVersion: '2026-01-26', hostInfo: { name: 'test-host', version: '1' }, hostCapabilities: {}, hostContext: hostContext || {} } });
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
  const title = paper.children[0];
  check('הכותרת ב-h1 עם dir=auto', title.tagName === 'H1' && title.getAttribute('dir') === 'auto' && title.textContent === 'רשימת קניות', title.textContent);
  const body = paper.children[1];
  check('שורה לכל שורת מקור', body.children.length === 4, body.children.length);
  check('כל שורה עם dir=auto', body.children.every((r) => r.getAttribute('dir') === 'auto'), body.children.map((r) => r.getAttribute('dir')));
  check('השורות בטקסט המקור, ושורה ריקה נושאת רווח קשיח',
    body.children.map((r) => r.textContent).join('|') === '# כותרת|\u00a0|English line|שורה בעברית',
    body.children.map((r) => r.textContent));
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
    check(`צבע ${JSON.stringify(color)} אינו מוצב`, paper.style.backgroundColor === '' && paper.className === 'ck-paper', [paper.style.backgroundColor, paper.className]);
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

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
