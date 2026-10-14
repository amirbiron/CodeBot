/**
 * שרשורי התגובות ב-``sticky-notes.js`` — הלוגיקה, בלי דפדפן.
 *
 * הרצה:  node tests/sticky-notes-threads.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * **למה קובץ כזה, כשיש טסטי דפדפן.** ``tests/test_note_threads_browser.py`` עובר דרך
 * הממשק האמיתי מול שרת ומונגו אמיתיים — והוא לא רץ ב-CI (אין שם Chromium ואין מונגו נגיש,
 * ``docs/testing.rst``). מה שכאן כן רץ שם, על הקוד עצמו: הנוסחה של "+N" מהעיצוב, בדיקת
 * הטיפוסים של מה שהגיע מהשרת (U3), "הצלחה רק כשהשרת אמר הצלחה" ותקרת הזמן של כל בקשה
 * (K11, ``wait-without-own-deadline``), המונה שסופר נקודות קוד כמו השרת, ומה כל כפתור
 * בחלונית שולח — כולל "שליחה בלי פתיחה".
 *
 * המתודות נקראות על ה-prototype עם ``this`` מדומה: הן אינן נוגעות במנהל מעבר למה שמועבר
 * להן, ובנייה של מנהל אמיתי הייתה דורשת עמוד שלם.
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'sticky-notes.js');

/** אלמנט מדומה — מספיק ל-``createEl`` ולמה שתיבת הכתיבה עושה בו. */
function fakeEl(tag) {
  const classes = new Set();
  let text = '';
  const el = {
    tagName: String(tag || 'div').toUpperCase(),
    children: [], attributes: {}, dataset: {}, style: {}, listeners: {},
    disabled: false, hidden: false,
    get className() { return [...classes].join(' '); },
    set className(v) { classes.clear(); String(v).split(/\s+/).filter(Boolean).forEach((c) => classes.add(c)); },
    // ``textContent = ''`` מרוקן ילדים, כמו ב-DOM — ``_syncThreadComposer`` נשען על זה.
    get textContent() { return text; },
    set textContent(v) { text = String(v); el.children.length = 0; },
    classList: {
      add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c),
      toggle: (c, force) => {
        const on = force === undefined ? !classes.has(c) : !!force;
        if (on) classes.add(c); else classes.delete(c);
        return on;
      },
    },
    setAttribute(k, v) { el.attributes[k] = String(v); },
    getAttribute(k) { return k in el.attributes ? el.attributes[k] : null; },
    appendChild(c) { el.children.push(c); return c; },
    addEventListener(type, fn) { el.listeners[type] = fn; },
    removeEventListener() {},
    querySelector: () => null, querySelectorAll: () => [],
    getBoundingClientRect: () => ({ left: 0, top: 0, width: 0, height: 0 }),
  };
  return el;
}

/** הטיימרים של 15 שניות נלכדים (התקרה של בקשת שרשור) ומופעלים ביד; כל השאר אמיתיים. */
const timers = [];
const THREAD_DEADLINE_MS = 15 * 1000;

function makeSandbox() {
  const sandbox = {
    console,
    document: {
      body: fakeEl('body'),
      getElementById: () => null,
      createElement: (tag) => fakeEl(tag),
      createElementNS: (_ns, tag) => fakeEl(tag),
      addEventListener() {}, removeEventListener() {},
      querySelectorAll: () => [], querySelector: () => null,
      get activeElement() { return null; },
    },
    window: {
      addEventListener() {}, removeEventListener() {},
      innerWidth: 1024, innerHeight: 768,
      matchMedia: () => ({ matches: false }),
      location: { href: 'https://example.test/boards/b1', search: '', hash: '' },
    },
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    fetch: async () => ({ ok: true, status: 200, json: async () => ({ ok: true, notes: [] }) }),
    HTMLElement: function HTMLElement() {},
    AbortController,
    setTimeout: (fn, ms, ...rest) => {
      if (ms === THREAD_DEADLINE_MS) { const t = { fn, cleared: false }; timers.push(t); return t; }
      return setTimeout(fn, ms, ...rest);
    },
    clearTimeout: (t) => { if (t && typeof t === 'object' && 'cleared' in t) t.cleared = true; else clearTimeout(t); },
    setInterval, clearInterval,
    MutationObserver: undefined, ResizeObserver: undefined, IntersectionObserver: undefined,
    URL,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox;
}

const sandbox = makeSandbox();
const P = sandbox.window.StickyNotesManager.prototype;
const NOTE_ID = '64b7f1d2e3a4b5c6d7e8f901';
const THREAD_ID = '64b7f1d2e3a4b5c6d7e8f902';

let passed = 0, failed = 0;
// **בדיקה אחת בכל פעם, לפי הסדר** — גם האסינכרוניות. הן חולקות את ``sandbox.fetch`` ואת
// רשימת הטיימרים, ובדיקות שרצות במקביל היו קוראות את הטיימר של שכנה.
let chain = Promise.resolve();
function check(name, fn) {
  chain = chain.then(async () => {
    try { await fn(); passed += 1; }
    catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
  });
}
function eq(actual, expected, what) {
  const a = JSON.stringify(actual), b = JSON.stringify(expected);
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${b}, קיבלתי ${a}`);
}

// ── "+N": הנוסחה מהעיצוב ────────────────────────────────────────────────────
// "מספר הבועות הגלויות הוא floor((רוחב הפתק − 20) / 44) − 1. האחרונה מתחלפת ב-'+N'."
// ``capacity`` הוא ה-floor; ``_threadRowCapacity`` גוזר אותו מה-CSS ונמדד בדפדפן.
const capacityOf = (width) => Math.floor((width - 20) / 44);
const threads = (n) => Array.from({ length: n }, (_, i) => ({ id: `t${i + 1}`, number: i + 1 }));
const ids = (list) => list.map((t) => t.id);

check('פתק של 260 עם שבעה שרשורים — ארבע בועות ו-"+3" (העיצוב, מצב 7)', () => {
  eq(capacityOf(260), 5, 'הנוסחה');
  const layout = P._threadRowLayout(threads(7), capacityOf(260), false);
  eq(ids(layout.shown), ['t1', 't2', 't3', 't4']);
  eq(ids(layout.hidden), ['t5', 't6', 't7']);
  eq(layout.chip, true);
});

check('כשהכול נכנס — הכול מוצג, ואין "+N" (גם בדיוק בגבול)', () => {
  eq(capacityOf(196), 4, '196 = 20 + 4·44');
  const layout = P._threadRowLayout(threads(4), capacityOf(196), false);
  eq([ids(layout.shown), layout.hidden, layout.chip], [['t1', 't2', 't3', 't4'], [], false]);
  const short = P._threadRowLayout(threads(4), capacityOf(195), false);
  eq([ids(short.shown), ids(short.hidden), short.chip], [['t1', 't2'], ['t3', 't4'], true]);
});

check('שרשור חדש תופס את התא שלפני "+N" — והחלונית שלו תמיד מצביעה על בועה', () => {
  const fits = P._threadRowLayout(threads(4), 5, true);
  eq([ids(fits.shown), fits.chip], [['t1', 't2', 't3', 't4'], false], 'ארבעה ועוד החדש — חמישה תאים');
  const over = P._threadRowLayout(threads(5), 5, true);
  eq([ids(over.shown), ids(over.hidden), over.chip], [['t1', 't2', 't3'], ['t4', 't5'], true]);
});

check('פתק צר מתא אחד: הכול בתוך "+N", ובלי מספר שלילי של בועות', () => {
  const layout = P._threadRowLayout(threads(3), 1, false);
  eq([layout.shown, ids(layout.hidden), layout.chip], [[], ['t1', 't2', 't3'], true]);
  const withNew = P._threadRowLayout(threads(3), 1, true);
  eq([withNew.shown, withNew.hidden.length], [[], 3]);
});

check('בלי CSS (תקרה אינסופית) — הכול מוצג', () => {
  eq(P._threadRowLayout(threads(9), Infinity, false).chip, false);
});

// ── מה שהגיע מהשרת נבדק בטיפוס שלו (U3) ─────────────────────────────────────
check('תקצירים: לא-רשימה היא "לא ידוע" (null), ולא "אין שרשורים"', () => {
  for (const bad of [undefined, null, {}, 'x', 3]) eq(P._threadsFromServer(bad), null, JSON.stringify(bad));
  eq(P._threadsFromServer([]), []);
});

check('תקצירים: שורה בלי מזהה או בלי מספר נזרקת, ושדות בטיפוס שגוי מתאפסים', () => {
  const rows = P._threadsFromServer([
    { id: 'a', number: 1, status: 'resolved', comment_count: 3, awaits_user: true },
    { id: 'b', number: 2, status: 'RESOLVED', comment_count: '7', awaits_user: 'true' },
    { id: 'c', number: 3, status: 'open', comment_count: -1, awaits_user: 1 },
    { id: 'd', number: 0 }, { id: '', number: 4 }, { number: 5 }, { id: 6, number: 6 }, null, 'x',
    { id: 'e', number: 2.5 },
  ]);
  eq(rows, [
    { id: 'a', number: 1, resolved: true, count: 3, awaitsUser: true },
    { id: 'b', number: 2, resolved: false, count: 0, awaitsUser: false },
    { id: 'c', number: 3, resolved: false, count: 0, awaitsUser: false },
  ]);
});

check('תגובה: כל שדה שאינו מחרוזת מוצג ריק — לא "undefined" ולא אובייקט', () => {
  eq(P._commentFromServer(null), null);
  eq(P._commentFromServer('x'), null);
  eq(P._commentFromServer({ id: 5, author_label: ['x'], author_initials: 'CC', author_tone: 'cc',
                             working_on: null, body: 'גוף', created_at: 12 }),
     { id: '', label: '', initials: 'CC', tone: 'cc', workingOn: '', body: 'גוף', createdAt: '' });
});

check('מצב שרשור: התגובות רק כשנשאו אותן, ומי סגר — רק כמחרוזת', () => {
  const t = P._threadStateFromServer.call(P, {
    id: 'a', number: 2, status: 'resolved', comment_count: 1, awaits_user: false,
    resolved_by_label: 'CC', resolved_at: '2026-10-13T10:00:00+00:00',
    comments: [{ id: 'c1', body: 'סיכום' }, null, 'x'],
  });
  eq([t.resolved, t.resolvedBy, t.resolvedAt, t.comments.length, t.comments[0].body],
     [true, 'CC', '2026-10-13T10:00:00+00:00', 1, 'סיכום']);
  const write = P._threadStateFromServer.call(P, { id: 'a', number: 1, resolved_by_label: {}, status: 'open' });
  eq([write.comments, write.resolvedBy], [null, '']);
  eq(P._threadStateFromServer.call(P, { number: 1 }), null, 'בלי מזהה — אין מצב');
});

check('התווית הנגישה של בועה: מספר, כמה תגובות (יחיד ורבים), ומה המצב', () => {
  eq(P._threadBubbleLabel({ number: 1, count: 1, resolved: false, awaitsUser: false }), 'שרשור 1 · 1 תגובה');
  eq(P._threadBubbleLabel({ number: 2, count: 1234, resolved: true, awaitsUser: true }),
     'שרשור 2 · 1,234 תגובות · נפתר · מחכה לך');
});

// ── מקור אחד לתקצירים, והקאש בלעדיהם ────────────────────────────────────────
check('אחרי הרינדור המקור הוא entry.threads — העותק על אובייקט הפתק נמחק, ולא נשאר להתיישן', () => {
  const el = fakeEl('div');
  el.dataset.noteId = NOTE_ID;
  const entry = { el };
  const mgr = { _getEntry: () => entry, _threadsFromServer: P._threadsFromServer,
                _renderThreadRow() {}, _syncThreadsButton() {} };
  const note = { id: NOTE_ID, threads: [{ id: 'a', number: 1, status: 'open', comment_count: 2, awaits_user: true }] };
  P._initNoteThreads.call(mgr, el, note);
  eq(['threads' in note, entry.threads.list.map((t) => [t.id, t.count, t.awaitsUser])], [false, [['a', 2, true]]]);
});

check('הקאש המקומי אינו שומר תקצירים — גם כשהפתק שנשלח לשמירה עוד נושא אותם', () => {
  let written = null;
  const saved = sandbox.localStorage.setItem;
  sandbox.localStorage.setItem = (key, value) => { written = [key, value]; };
  try {
    const notes = [{ id: 'n1', content: 'x', threads: [{ id: 'a', number: 1 }] }, { id: 'n2', content: 'y' }];
    P._saveCache.call({ _cacheKey: 'sticky-notes:board:b1' }, notes);
    const payload = JSON.parse(written[1]);
    eq([written[0], payload.notes.map((n) => Object.keys(n).sort())],
       ['sticky-notes:board:b1', [['content', 'id'], ['content', 'id']]]);
    eq('threads' in notes[0], true, 'מה שנשלח לשמירה לא שונה — הקאש מקבל עותק');
  } finally { sandbox.localStorage.setItem = saved; }
});

// ── הודעות למשתמש ────────────────────────────────────────────────────────────
check('קוד שגיאה מהשרת הופך להודעה בעברית — עם התקרה מהתשובה, כשיש', () => {
  const msg = (data, status, sending) => P._threadErrorMessage({ ok: false, status, data }, sending);
  eq(msg({ error: 'body_too_long', max: 4000 }, 400, true), 'התגובה ארוכה מ-4,000 תווים.');
  eq(msg({ error: 'body_too_long', max: '4000' }, 400, true), 'התגובה ארוכה מהמותר.', 'max שאינו מספר שלם');
  eq(msg({ error: 'already_resolved' }, 409, true), 'השרשור כבר נסגר בינתיים.');
  eq(msg({ error: 'not_resolved' }, 409, true), 'השרשור כבר פתוח.');
  eq(msg({ error: 'conflict' }, 409, true), 'השרשור השתנה בזמן השליחה — נסו שוב.');
  eq(msg({ error: 'thread_full' }, 409, true), 'השרשור הגיע למספר התגובות המרבי — אפשר לפתוח שרשור חדש.');
  eq(msg({ error: 'thread_not_found' }, 404, false), 'השרשור הזה כבר לא קיים.');
  eq(msg({ error: 'note_not_found' }, 404, false), 'הפתק כבר לא קיים.');
  eq(msg({ error: 'Unauthorized' }, 401, true), 'החיבור פג — יש לרענן את העמוד ולהתחבר שוב.');
  eq(msg({ error: 'Rate limited' }, 429, true), 'יותר מדי פעולות ברצף — נסו שוב בעוד רגע.');
  eq(msg(null, 0, true), 'השליחה לא הגיעה לשרת — הטקסט נשאר בתיבה, נסו שוב.');
  eq(msg(null, 0, false), 'לא הצלחנו להגיע לשרת.');
  eq(msg(null, 502, true), 'השליחה נכשלה — הטקסט נשאר בתיבה, נסו שוב.');
  eq(msg({ error: 7 }, 500, false), 'משהו השתבש בטעינה.', 'קוד שאינו מחרוזת אינו מוצג');
});

// ── הבקשה: הצלחה רק כשהשרת אמר הצלחה, ותקרת זמן משלה ────────────────────────
const response = (status, body, { notJson = false } = {}) => ({
  ok: status >= 200 && status < 300, status,
  json: async () => { if (notJson) throw new SyntaxError('Unexpected token <'); return body; },
});
async function fetchWith(fake) {
  sandbox.fetch = fake;
  return P._threadFetch.call(P, '/api/x').result;
}

check('K11: 2xx עם {ok: true} — הצלחה; כל השאר כשל עם הסטטוס האמיתי', async () => {
  eq(await fetchWith(async () => response(200, { ok: true, a: 1 })), { ok: true, status: 200, data: { ok: true, a: 1 } });
  eq((await fetchWith(async () => response(200, { ok: false, error: 'x' }))).ok, false, '200 עם ok:false');
  eq((await fetchWith(async () => response(500, { ok: true }))).ok, false, '500 עם ok:true');
  eq(await fetchWith(async () => response(200, null, { notJson: true })), { ok: false, status: 200, data: null },
     'דף שגיאה שאינו JSON');
  eq((await fetchWith(async () => response(200, [{ ok: true }]))).data, null, 'רשימה אינה תשובה');
  eq(await fetchWith(async () => { throw new TypeError('Failed to fetch'); }), { ok: false, status: 0, data: null },
     'כשל רשת');
});

check('בקשה שאינה חוזרת נגמרת בתקרה של 15 שניות — ומבטלת את עצמה', async () => {
  timers.length = 0;
  let signal = null;
  sandbox.fetch = (_url, init) => { signal = init.signal; return new Promise(() => {}); };   // לא חוזרת לעולם
  const req = P._threadFetch.call(P, '/api/x', { method: 'POST' });
  eq(timers.length, 1, 'נרשמה תקרה אחת, של 15 שניות');
  eq(signal.aborted, false);
  timers[0].fn();
  eq(await req.result, { ok: false, status: 0, data: null });
  eq(signal.aborted, true, 'הבקשה בוטלה, ולא רק ננטשה');
});

check('תשובה שהגיעה לפני התקרה מבטלת את הטיימר; ו-abort() מבטל את הבקשה (סגירת חלונית)', async () => {
  timers.length = 0;
  sandbox.fetch = async () => response(200, { ok: true });
  const res = await P._threadFetch.call(P, '/api/x').result;
  eq([res.ok, timers[0].cleared], [true, true]);
  let signal = null;
  sandbox.fetch = (_url, init) => new Promise((_, reject) => {
    signal = init.signal;
    init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  });
  const req = P._threadFetch.call(P, '/api/x');
  req.abort();
  eq([(await req.result).status, signal.aborted], [0, true]);
});

// ── תיבת הכתיבה: המונה והכפתורים ─────────────────────────────────────────────

/** מנהל מדומה: פתק אחד, חלונית פתוחה, ורישום של כל פעולה שנשלחה. */
function composer({ value = '', isNew = false, resolved = false, busy = false } = {}) {
  const el = fakeEl('div');
  el.dataset.noteId = NOTE_ID;
  const ui = { input: fakeEl('textarea'), counter: fakeEl('span'), actions: fakeEl('div'), panel: fakeEl('div') };
  ui.input.value = value;
  const entry = {
    el,
    threads: {
      list: [], drafts: new Map(),
      open: { id: isNew ? null : THREAD_ID, isNew, busy, error: '', phase: 'ready',
              thread: isNew ? null : { resolved, comments: [], count: 0 } },
      panel: ui,
    },
  };
  const sent = [];
  const mgr = {
    _getEntry: () => entry,
    _closeThreadPanel: () => sent.push(['cancel']),
    _sendThreadAction: (_el, kind, opts) => sent.push([kind, opts || null]),
  };
  P._syncThreadComposer.call(mgr, el);
  const buttons = ui.actions.children.filter((c) => c !== ui.counter);
  const click = (label) => {
    const b = buttons.find((x) => x.textContent === label);
    if (!b) throw new Error(`אין כפתור "${label}" — יש ${JSON.stringify(buttons.map((x) => x.textContent))}`);
    b.listeners.click({ stopPropagation() {} });
  };
  return { ui, buttons: buttons.map((b) => [b.textContent, b.disabled]), sent, click };
}

check('המונה סופר נקודות קוד (``[...s].length``), כמו השרת — אימוג\'י הוא תו אחד', () => {
  sandbox.window.NOTE_THREAD_MAX_CHARS = 4000;
  const c = composer({ value: '😀😀😀' });
  eq(c.ui.counter.textContent, '3 / 4,000');
  eq(c.ui.counter.classList.contains('is-over'), false);
  eq(c.ui.actions.children[0], c.ui.counter, 'המונה ראשון בשורה');
});

check('מעל התקרה: המונה מסומן, ושני הכפתורים מושבתים; בדיוק בתקרה — מותר', () => {
  sandbox.window.NOTE_THREAD_MAX_CHARS = 4000;
  const over = composer({ value: '😀'.repeat(4001) });
  eq([over.ui.counter.textContent, over.ui.counter.classList.contains('is-over')], ['4,001 / 4,000', true]);
  eq(over.buttons, [['✓ נפתר', true], ['שליחה', true]]);
  const at = composer({ value: '😀'.repeat(4000) });
  eq([at.ui.counter.classList.contains('is-over'), at.buttons], [false, [['✓ נפתר', false], ['שליחה', false]]]);
});

check('ריק או רווחים בלבד — "שליחה" מושבתת (השרת בודק ריקות אחרי strip), "✓ נפתר" לא', () => {
  sandbox.window.NOTE_THREAD_MAX_CHARS = 4000;
  eq(composer({ value: '' }).buttons, [['✓ נפתר', false], ['שליחה', true]]);
  eq(composer({ value: ' \n\t ' }).buttons, [['✓ נפתר', false], ['שליחה', true]]);
});

check('בלי תקרה מהשרת: המונה בלי "/ N", ואין "מעל התקרה" — השרת הוא שיסרב', () => {
  delete sandbox.window.NOTE_THREAD_MAX_CHARS;
  const c = composer({ value: '😀'.repeat(5000) });
  eq([c.ui.counter.textContent, c.ui.counter.classList.contains('is-over')], ['5,000', false]);
  sandbox.window.NOTE_THREAD_MAX_CHARS = 4000;
});

check('הכפתורים לפי המצב — ומה כל אחד שולח (העיצוב, מצבים 4, 8, 9)', () => {
  const open = composer({ value: 'טקסט' });
  eq(open.buttons, [['✓ נפתר', false], ['שליחה', false]]);
  open.click('✓ נפתר'); open.click('שליחה');
  eq(open.sent, [['resolve', null], ['reply', { reopen: true }]]);

  const resolved = composer({ value: 'לתיעוד', resolved: true });
  eq(resolved.buttons, [['שליחה בלי פתיחה', false], ['שליחה ופתיחה מחדש', false]]);
  resolved.click('שליחה בלי פתיחה'); resolved.click('שליחה ופתיחה מחדש');
  eq(resolved.sent, [['reply', { reopen: false }], ['reply', { reopen: true }]]);

  const fresh = composer({ value: 'על מה?', isNew: true });
  eq(fresh.buttons, [['ביטול', false], ['שליחה', false]]);
  fresh.click('ביטול'); fresh.click('שליחה');
  eq(fresh.sent, [['cancel'], ['create', null]]);
});

check('בזמן שליחה הכול נעול — גם "ביטול" של שרשור חדש', () => {
  eq(composer({ value: 'x', busy: true }).buttons, [['✓ נפתר', true], ['שליחה', true]]);
  eq(composer({ value: 'x', busy: true, isNew: true }).buttons, [['ביטול', true], ['שליחה', true]]);
});

// ── שליחת פעולה: מה יוצא לשרת, ומה מוצג אחרי ──────────────────────────────────
/** מנהל מדומה ל-``_sendThreadAction``: הבקשה נרשמת, והתשובה היא ``answer``. */
function sender({ value = '', isNew = false, resolved = false, comments = [], answer }) {
  const el = fakeEl('div');
  el.dataset.noteId = NOTE_ID;
  const ui = { input: fakeEl('textarea') };
  ui.input.value = value;
  const open = { id: isNew ? null : THREAD_ID, isNew, busy: false, error: '', phase: 'ready',
                 thread: isNew ? null : { resolved, comments, count: comments.length, number: 1 } };
  const st = { list: [], drafts: new Map([[isNew ? 'new' : THREAD_ID, value]]), open, panel: ui };
  const entry = { el, threads: st };
  const log = { requests: [], reloads: 0, refreshed: 0, busyDuring: null };
  const mgr = {
    _destroyed: false,
    _getEntry: () => entry,
    _threadUrl: P._threadUrl,
    _threadsFromServer: P._threadsFromServer,
    _threadStateFromServer: P._threadStateFromServer,
    _commentFromServer: P._commentFromServer,
    _threadErrorMessage: P._threadErrorMessage,
    _threadFetch(url, init) {
      log.requests.push([url, JSON.parse(init.body)]);
      log.busyDuring = open.busy;
      return { result: Promise.resolve(answer), abort() {} };
    },
    _renderThreadPanel() {}, _renderThreadRow() {}, _syncThreadsButton() {},
    _loadThread() { log.reloads += 1; },
    _reloadThreadKeepingError() { log.reloads += 1; },
    _refreshThreadSummaries() { log.refreshed += 1; },
  };
  return { el, mgr, open, st, ui, log, run: (kind, opts) => P._sendThreadAction.call(mgr, el, kind, opts) };
}
const BASE = `/api/sticky-notes/note/${NOTE_ID}/threads`;
const FAIL = { ok: false, status: 0, data: null };

check('מה כל פעולה שולחת: הכתובת והגוף', async () => {
  const reply = sender({ value: 'לתיעוד', resolved: true, answer: FAIL });
  await reply.run('reply', { reopen: false });
  eq(reply.log.requests, [[`${BASE}/${THREAD_ID}/comments`, { body: 'לתיעוד', reopen: false }]]);

  const resolve = sender({ value: 'סיכום', answer: FAIL });
  await resolve.run('resolve');
  eq(resolve.log.requests, [[`${BASE}/${THREAD_ID}/resolve`, { body: 'סיכום' }]], 'סיכום באותה כתיבה (2-א)');

  const bare = sender({ value: '  \n ', answer: FAIL });
  await bare.run('resolve');
  eq(bare.log.requests, [[`${BASE}/${THREAD_ID}/resolve`, {}]], 'רווחים בלבד — סגירה בלי סיכום');

  const reopen = sender({ value: 'נשאר בתיבה', resolved: true, answer: FAIL });
  await reopen.run('reopen');
  eq(reopen.log.requests, [[`${BASE}/${THREAD_ID}/reopen`, {}]], 'פתיחה מחדש אינה שולחת את הטקסט');

  const create = sender({ value: 'על מה השרשור', isNew: true, answer: FAIL });
  await create.run('create');
  eq(create.log.requests, [[BASE, { body: 'על מה השרשור' }]]);
});

check('כשל: הטקסט והטיוטה נשארים, ההודעה מוצגת, ו-busy נכבה', async () => {
  const s = sender({ value: 'לא יאבד', answer: FAIL });
  await s.run('reply', { reopen: true });
  eq([s.log.busyDuring, s.open.busy], [true, false], 'נעול בזמן הבקשה, ומשוחרר אחריה');
  eq([s.ui.input.value, s.st.drafts.get(THREAD_ID)], ['לא יאבד', 'לא יאבד']);
  eq(s.open.error, 'השליחה לא הגיעה לשרת — הטקסט נשאר בתיבה, נסו שוב.');
});

check('סירוב 409 (נסגר בינתיים) — ההודעה, וטעינה מחדש של מה שבמסד', async () => {
  const s = sender({ value: 'סיכום שאיחר', answer: { ok: false, status: 409, data: { ok: false, error: 'already_resolved' } } });
  await s.run('resolve');
  eq([s.open.error, s.log.reloads, s.ui.input.value], ['השרשור כבר נסגר בינתיים.', 1, 'סיכום שאיחר']);
});

const COMMENT = (id, body) => ({ id, body, author_label: 'אני', author_initials: 'אנ', author_tone: 'user',
                                  working_on: '', created_at: '2026-10-13T10:00:00+00:00' });
const STATE = (count, status = 'open') => ({ id: THREAD_ID, number: 1, status, comment_count: count, awaits_user: false,
                                             resolved_by_label: '', resolved_at: null });

check('הצלחה: מוצג מה שהשרת החזיר — המצב, התגובה כפי שנשמרה, והתקצירים — והתיבה מתרוקנת', async () => {
  const before = [P._commentFromServer(COMMENT('c1', 'שאלה'))];
  const s = sender({
    value: 'תשובה', comments: before,
    answer: { ok: true, status: 200, data: {
      ok: true, action: 'replied', thread_id: THREAD_ID, thread: STATE(2),
      comment: COMMENT('c2', 'תשובה כפי שנשמרה'),
      threads: [{ id: THREAD_ID, number: 1, status: 'open', comment_count: 2, awaits_user: false }],
    } },
  });
  await s.run('reply', { reopen: true });
  eq(s.open.thread.comments.map((c) => c.body), ['שאלה', 'תשובה כפי שנשמרה'], 'הגוף מהשרת, לא מהתיבה');
  eq([s.open.thread.count, s.st.list[0].count, s.ui.input.value, s.st.drafts.has(THREAD_ID), s.log.reloads],
     [2, 2, '', false, 0]);
});

check('המספר מהשרת אינו מה שמוצג (סוכן כתב בינתיים) — נטען מחדש מהמסד', async () => {
  const s = sender({
    value: 'תשובה', comments: [P._commentFromServer(COMMENT('c1', 'שאלה'))],
    answer: { ok: true, status: 200, data: {
      ok: true, thread_id: THREAD_ID, thread: STATE(3), comment: COMMENT('c3', 'תשובה'), threads: [],
    } },
  });
  await s.run('reply', { reopen: true });
  eq(s.log.reloads, 1);
});

check('הכתיבה הצליחה אבל הקריאה החוזרת בשרת לא (threads: null) — התקצירים נקראים שוב', async () => {
  const s = sender({
    value: 'x', comments: [],
    answer: { ok: true, status: 200, data: { ok: true, thread_id: THREAD_ID, thread: null, comment: null, threads: null } },
  });
  await s.run('reply', { reopen: true });
  eq([s.log.refreshed, s.log.reloads], [1, 1]);
});

check('שרשור חדש שנוצר: מקבל את המזהה מהשרת ומפסיק להיות "חדש"', async () => {
  const s = sender({
    value: 'ראשונה', isNew: true,
    answer: { ok: true, status: 201, data: {
      ok: true, action: 'created', thread_id: THREAD_ID, thread: STATE(1),
      comment: COMMENT('c1', 'ראשונה'), threads: [{ id: THREAD_ID, number: 1, status: 'open', comment_count: 1 }],
    } },
  });
  await s.run('create');
  eq([s.open.isNew, s.open.id, s.open.thread.comments.length, s.st.drafts.has('new')], [false, THREAD_ID, 1, false]);
});

await chain;
console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
