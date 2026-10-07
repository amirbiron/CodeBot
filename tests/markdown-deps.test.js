'use strict';
/**
 * בדיקות ל-``webapp/static/js/markdown-deps.js`` — הטוען של הבאנדל ``md_preview.bundle.js``.
 *
 * הרצה:  node tests/markdown-deps.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * הקובץ נטען כמו בדפדפן, כסקריפט קלאסי, בתוך sandbox של vm עם DOM מינימלי: תגית script
 * מדומה שאפשר להפעיל עליה ``load`` או ``error``, ושעון ידני, כדי לבדוק את הדדליין בלי לחכות לו.
 *
 * **מה הבדיקות האלה כן מוכיחות:** את הכתובת שנגזרת מהתגית של הטוען, את השחרור של ההמתנה
 * בכשל, ניסיון חוזר אמיתי אחרי כשל, את הבדיקה שהבאנדל באמת הגדיר את מה שחיכו לו, ואת הדדליין.
 *
 * **ומה לא:** שהדפדפן מגדיר ``document.currentScript`` לתגית עצמה, ושהבאנדל האמיתי נטען ורץ.
 * את זה מוכיחים טסטי הדפדפן של דפדפן הקוד ושל כרטיסי התיעוד.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'markdown-deps.js');
const SRC = fs.readFileSync(MODULE_PATH, 'utf8');

const OWN_TAG = 'https://ck.example/static/js/markdown-deps.js?v=abc12345';
const BUNDLE = 'https://ck.example/static/js/md_preview.bundle.js?v=abc12345';

// הטעינה האיטית שנמדדה (7.10.2026, Chromium מול הוובאפ: 400kbps, השהיה 400ms, ‏CPU פי 4).
// דדליין קצר ממנה מפיל טעינה תקינה ברשת איטית — זה מה שה-8 שניות הישנות היו עושות.
const SLOW_LOAD_MS = 23545;

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
function eq(actual, expected, what) {
  if (actual !== expected) {
    throw new Error(
      `${what || ''} — ציפיתי ל-${JSON.stringify(expected)}, קיבלתי ${JSON.stringify(actual)}`);
  }
}
function ok(value, what) { if (!value) throw new Error(what || 'ציפיתי לאמת'); }
const tick = () => new Promise((resolve) => setImmediate(resolve));

/** מצב ההבטחה בלי לחכות לה: 'pending', 'resolved', או ההודעה של השגיאה. */
function track(promise) {
  const state = { value: 'pending' };
  promise.then(() => { state.value = 'resolved'; }, (e) => { state.value = e && e.message; });
  return state;
}

function makeScript() {
  const listeners = { load: [], error: [] };
  const el = {
    src: '',
    removed: false,
    addEventListener(type, fn, opts) { listeners[type].push({ fn, once: !!(opts && opts.once) }); },
    removeEventListener(type, fn) { listeners[type] = listeners[type].filter((l) => l.fn !== fn); },
    remove() { el.removed = true; },
    fire(type) {
      const current = listeners[type];
      listeners[type] = current.filter((l) => !l.once);
      current.forEach((l) => l.fn({ type }));
    },
  };
  return el;
}

function load({ ownTag = OWN_TAG } = {}) {
  const appended = [];
  const timers = [];
  const patched = [];
  const sandbox = {
    document: {
      currentScript: ownTag === null ? null : { src: ownTag },
      createElement(tag) {
        eq(tag, 'script', 'סוג התגית');
        return makeScript();
      },
      head: { appendChild(el) { appended.push(el); return el; } },
    },
    URL,
    console,
    setTimeout(fn, ms) { const t = { fn, ms, cleared: false }; timers.push(t); return t; },
    clearTimeout(t) { if (t) t.cleared = true; },
    SafeHighlight: { patchHighlightAuto() { patched.push(sandbox.hljs); } },
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);
  return {
    sb: sandbox,
    appended,
    timers,
    patched,
    /** הבאנדל רץ: מגדיר את מה שהוא מגדיר בסוף ``md-preview-entry.js``, ואז ``load``. */
    runBundle(el) {
      sandbox.markdownit = () => ({});
      sandbox.hljs = { highlightElement() {} };
      el.fire('load');
    },
    liveTimers() { return timers.filter((t) => !t.cleared); },
  };
}

// ── הכתובת ─────────────────────────────────────────────────────────────────

check('הבאנדל נטען מאותה תיקייה ועם אותו ?v= כמו התגית של הטוען', async () => {
  const page = load();
  const done = track(page.sb.loadMarkdownDependencies());
  eq(page.appended.length, 1, 'מספר הבקשות');
  eq(page.appended[0].src, BUNDLE, 'הכתובת');
  page.runBundle(page.appended[0]);
  await tick();
  eq(done.value, 'resolved', 'הטעינה');
  eq(page.patched.length, 1, 'ה-patch של diff חל על ה-hljs של הבאנדל');
  eq(page.patched[0], page.sb.hljs, 'על המופע החדש');
});

check('התיקייה נלקחת מהתגית ולא מנתיב קבוע', async () => {
  // אילו הטוען היה מרכיב ``/static/js/`` בעצמו, אתר שמגיש את הנכסים מנתיב אחר (CDN, תת-תיקייה)
  // היה מבקש את הבאנדל ממקום שאינו קיים.
  const page = load({ ownTag: 'https://cdn.ck.example/assets/v2/markdown-deps.js?v=zz9' });
  page.sb.loadMarkdownDependencies().catch(() => {});
  eq(page.appended[0].src, 'https://cdn.ck.example/assets/v2/md_preview.bundle.js?v=zz9', 'הכתובת');
});

check('בלי תגית ידועה — דחייה מפורשת, ובלי בקשה לכתובת בלי גרסה', async () => {
  // הגיבוי הישן היה ``/static/js/md_preview.bundle.js`` בלי ``?v=`` — מול max-age של שנה,
  // עותק ישן של הבאנדל. עדיף כשל גלוי.
  const page = load({ ownTag: null });
  const done = track(page.sb.loadMarkdownDependencies());
  await tick();
  eq(done.value, 'markdown_bundle_url_unknown', 'הדחייה');
  eq(page.appended.length, 0, 'לא נשלחה בקשה');
});

check('כשהבאנדל כבר רץ — אין בקשה', async () => {
  const page = load();
  page.sb.markdownit = () => ({});
  page.sb.hljs = { highlightElement() {} };
  await page.sb.loadMarkdownDependencies();
  eq(page.appended.length, 0, 'מספר הבקשות');
  eq(page.patched.length, 1, 'ה-patch חל גם כך');
});

// ── המתנה משותפת ושחרור בכשל ────────────────────────────────────────────────

check('קריאות במקביל חולקות בקשה אחת', async () => {
  const page = load();
  const first = track(page.sb.loadMarkdownDependencies());
  const second = track(page.sb.loadMarkdownDependencies());
  eq(page.appended.length, 1, 'מספר הבקשות');
  page.runBundle(page.appended[0]);
  await tick();
  eq(first.value, 'resolved', 'הראשונה');
  eq(second.value, 'resolved', 'השנייה');
});

check('כשל טעינה: ההמתנה משתחררת, התגית יורדת, והניסיון הבא שולח בקשה חדשה', async () => {
  // בלי ההסרה, הניסיון הבא היה מצטרף לתגית שכבר נכשלה ומחכה לה עד הדדליין המלא, ונגמר
  // בכשל. כך בכל ניסיון, עד רענון העמוד.
  const page = load();
  const first = track(page.sb.loadMarkdownDependencies());
  const failedTag = page.appended[0];
  failedTag.fire('error');
  await tick();
  ok(String(first.value).startsWith('script_load_failed:'), `הדחייה: ${first.value}`);
  ok(failedTag.removed, 'התגית שנכשלה ירדה מהעמוד');
  eq(page.liveTimers().length, 0, 'הטיימר בוטל');

  const retry = track(page.sb.loadMarkdownDependencies());
  eq(page.appended.length, 2, 'ניסיון חוזר הוא בקשה חדשה');
  page.runBundle(page.appended[1]);
  await tick();
  eq(retry.value, 'resolved', 'הניסיון החוזר');
});

check('נטען אבל לא הגדיר את מה שחיכו לו — נדחה, והניסיון הבא אמיתי', async () => {
  // למשל עמוד שגיאה שהוגש עם 200. בלי הבדיקה החוזרת ההמתנה הייתה מצליחה, והתצוגה הייתה
  // מגלה רק אחר כך שאין לה renderer.
  const page = load();
  const first = track(page.sb.loadMarkdownDependencies());
  const emptyTag = page.appended[0];
  emptyTag.fire('load');
  await tick();
  ok(String(first.value).startsWith('script_not_ready:'), `הדחייה: ${first.value}`);
  ok(emptyTag.removed, 'התגית ירדה מהעמוד');

  page.sb.loadMarkdownDependencies().catch(() => {});
  eq(page.appended.length, 2, 'ניסיון חוזר הוא בקשה חדשה');
});

// ── הדדליין ─────────────────────────────────────────────────────────────────

check('הדדליין ארוך מהטעינה האיטית שנמדדה, ומשחרר את ההמתנה כשהוא עובר', async () => {
  const page = load();
  const first = track(page.sb.loadMarkdownDependencies());
  const timers = page.liveTimers();
  eq(timers.length, 1, 'טיימר אחד להמתנה');
  ok(timers[0].ms > SLOW_LOAD_MS, `דדליין של ${timers[0].ms}ms קצר מהטעינה האיטית (${SLOW_LOAD_MS}ms)`);

  timers[0].fn();
  await tick();
  ok(String(first.value).startsWith('script_load_timeout:'), `הדחייה: ${first.value}`);
});

check('אחרי הדדליין התגית נשארת, והקריאה הבאה מצטרפת אליה ולא מורידה שוב', async () => {
  // הבקשה האיטית עוד יכולה להסתיים. תגית שנייה הייתה מורידה את הבאנדל פעם נוספת, ומריצה
  // אותו פעמיים.
  const page = load();
  page.sb.loadMarkdownDependencies().catch(() => {});
  const slowTag = page.appended[0];
  page.liveTimers()[0].fn();
  await tick();
  ok(!slowTag.removed, 'התגית נשארה');

  const second = track(page.sb.loadMarkdownDependencies());
  eq(page.appended.length, 1, 'אין בקשה שנייה');
  page.runBundle(slowTag);
  await tick();
  eq(second.value, 'resolved', 'הקריאה שהצטרפה');
});

check('תגית שנכשלה אחרי הדדליין, כשאיש לא מחכה לה, יורדת — והניסיון הבא אמיתי', async () => {
  const page = load();
  page.sb.loadMarkdownDependencies().catch(() => {});
  const slowTag = page.appended[0];
  page.liveTimers()[0].fn();
  await tick();
  slowTag.fire('error');
  ok(slowTag.removed, 'התגית ירדה');

  page.sb.loadMarkdownDependencies().catch(() => {});
  eq(page.appended.length, 2, 'ניסיון חוזר הוא בקשה חדשה');
});

// ── highlight.js ───────────────────────────────────────────────────────────

check('ensureHighlightJsLoaded: כש-hljs קיים — בלי בקשה, ועם ה-patch', async () => {
  const page = load();
  page.sb.hljs = { highlightElement() {} };
  await page.sb.ensureHighlightJsLoaded();
  eq(page.appended.length, 0, 'מספר הבקשות');
  eq(page.patched.length, 1, 'ה-patch');
});

check('ensureHighlightJsLoaded: בלי hljs — טוען את הבאנדל, באותה כתובת', async () => {
  const page = load();
  const done = track(page.sb.ensureHighlightJsLoaded());
  eq(page.appended.length, 1, 'מספר הבקשות');
  eq(page.appended[0].src, BUNDLE, 'הכתובת');
  page.runBundle(page.appended[0]);
  await tick();
  eq(done.value, 'resolved', 'הטעינה');
});

(async () => {
  await Promise.all(pending);
  console.log(`\n${passed} עברו, ${failed} נכשלו`);
  process.exit(failed === 0 ? 0 : 1);
})();
