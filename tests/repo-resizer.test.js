'use strict';
// בדיקות על שינוי רוחב הסיידבר בדפדפן הריפו.
//
// **מה נשמר כאן:** שהמפריד עובד גם במגע ולא רק בעכבר. הצורה הקודמת קשרה
// ``mousedown``/``mousemove``/``mouseup`` בלבד, ולכן באצבע לא קרה כלום —
// כשל שנראה זהה ל"הפיצ'ר לא קיים" ולא מייצר שום שגיאה.
//
// הבדיקות מריצות את ``initResizer`` האמיתי מול DOM מדומה. הן בודקות
// התנהגות ולא מחרוזות: איזה אירועים נקשרו זה פרט מימוש, מה שקורה כשגוררים
// זה החוזה. החריג היחיד הוא בדיקת ``touch-action`` ב-CSS, שאין דרך לאמת
// אותה בלי מנוע פריסה — ובלעדיה גרירת המגע מתה בדפדפן אמיתי.

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const JS = path.join(__dirname, '..', 'webapp', 'static', 'js', 'repo-browser.js');
const CSS = path.join(__dirname, '..', 'webapp', 'static', 'css', 'repo-browser.css');

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(a, b, what) {
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${JSON.stringify(b)}, קיבלתי ${JSON.stringify(a)}`);
}

/** מחלץ את גוף ``initResizer`` לפי ספירת סוגריים, ולא לפי מספר שורות. */
function extractInitResizer() {
  const src = fs.readFileSync(JS, 'utf8');
  const start = src.indexOf('function initResizer()');
  if (start < 0) throw new Error('initResizer לא נמצאה');
  let i = src.indexOf('{', start), depth = 0;
  for (; i < src.length; i += 1) {
    if (src[i] === '{') depth += 1;
    else if (src[i] === '}') { depth -= 1; if (depth === 0) return src.slice(start, i + 1); }
  }
  throw new Error('לא נמצא סוף הפונקציה');
}

const MIN = 200, MAX = 500;

/** DOM מדומה מינימלי: רק מה ש-``initResizer`` באמת נוגע בו. */
/**
 * ``side`` הוא צד הסיידבר ביחס למפריד: ``'right'`` כמו בפריסת RTL של
 * הפרויקט, ``'left'`` כמו ב-LTR. הסימן של הגרירה נגזר מזה בקוד, ולכן
 * הבדיקות חייבות לכסות את שניהם.
 */
function makeHarness(startWidth = 280, captureFails = false, side = 'right') {
  const listeners = {};
  const onResizer = {};
  const captured = [];
  const classes = new Set();

  // גאומטריה מדומה, מספיקה בדיוק לשאלה שהקוד שואל: **באיזה צד של המפריד
  // יושב הסיידבר**. שני ה-``getBoundingClientRect`` שלמטה נצרכים ישירות
  // על ידי ``sidebarSign`` ב-``repo-browser.js`` — בלעדיהם הגרירה זורקת
  // ו-11 מ-16 הבדיקות נופלות. הם לא עזר של הבדיקות, הם הקלט של הקוד.
  //
  // מה שהיא **אינה** מדמה: הפיזיקה המלאה — קצה נעוץ מול קצה שזז — ולכן
  // אין כאן בדיקה על מיקום הקצה. את זה מודדים בדפדפן, ואת התוצאה רשמנו
  // ב-PR: האצבע ב-1038 והמפריד ב-1038, צעד אחר צעד.
  const RX = 1000, RW = 4;
  const rect = (left, width) => ({ left, right: left + width, width });
  const resizer = {
    getBoundingClientRect: () => rect(RX, RW),
    addEventListener: (t, fn) => {
      onResizer[t] = true;
      (listeners[t] = listeners[t] || []).push(fn);
    },
    setPointerCapture: (id) => {
      if (captureFails) throw new Error('capture unavailable');
      captured.push(id);
    },
    classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c) },
  };
  const sidebar = {
    style: { width: `${startWidth}px` },
    getBoundingClientRect: () => {
      const w = parseInt(sidebar.style.width, 10);
      return side === 'right' ? rect(RX + RW, w) : rect(RX - w, w);
    },
  };
  Object.defineProperty(sidebar, 'offsetWidth', {
    get: () => parseInt(sidebar.style.width, 10),
  });

  const documentElement = {};
  const body = { style: { cursor: '', userSelect: '' } };
  const onDocument = {};
  const sandbox = {
    document: {
      documentElement, body,
      // המאזינים על ``document`` נאספים לאותה מפה: בדפדפן אירוע לכוד
      // מבעבע לכאן, ולכן שני המקורות מגיעים לאותו handler.
      addEventListener: (t, fn) => {
        onDocument[t] = true;
        (listeners[t] = listeners[t] || []).push(fn);
      },
      getElementById: (id) => (id === 'sidebar-resizer' ? resizer : id === 'repo-sidebar' ? sidebar : null),
    },
    getComputedStyle: (el) => ({
      getPropertyValue: (p) => (p === '--sidebar-min-width' ? `${MIN}px`
                             : p === '--sidebar-max-width' ? `${MAX}px` : ''),
    }),
    Number, Math, parseInt, parseFloat,
  };
  vm.createContext(sandbox);
  vm.runInContext(extractInitResizer() + '\ninitResizer();', sandbox);

  const prevented = [];
  const fire = (type, ev) => (listeners[type] || []).forEach((fn) => fn(ev));
  const pt = (pointerId, clientX, extra) =>
    Object.assign(
      { pointerId, clientX, button: 0, pointerType: 'touch',
        preventDefault() { prevented.push(pointerId); } },
      extra || {},
    );

  return {
    fire, pt, listeners, captured, classes, body, prevented, onResizer, onDocument,
    width: () => parseInt(sidebar.style.width, 10),
    types: () => Object.keys(listeners).sort(),
  };
}

// ─── קשירת האירועים ─────────────────────────────────────────────────────

check('נקשרים אירועי pointer, ולא אירועי עכבר בלבד', () => {
  // **זה הכשל המקורי.** רק mouse* היו קשורים, ולכן באצבע לא קרה דבר.
  const h = makeHarness();
  const t = h.types();
  ['pointerdown', 'pointermove', 'pointerup', 'pointercancel'].forEach((e) => {
    if (!t.includes(e)) throw new Error(`חסר מאזין ל-${e}. קשורים: ${t.join(', ')}`);
  });
  t.forEach((e) => {
    if (e.startsWith('mouse')) throw new Error(`נשאר מאזין עכבר נפרד: ${e}`);
  });
});

check('הגרירה לוכדת את המצביע', () => {
  // בלי לכידה האצבע מאבדת את המפריד ברגע שהיא יוצאת מרצועת 4 הפיקסלים.
  const h = makeHarness();
  h.fire('pointerdown', h.pt(1, 1000));
  eq(h.captured.length, 1, 'קריאות setPointerCapture');
  eq(h.captured[0], 1, 'ה-pointerId שנלכד');
});

// ─── הגרירה עצמה ────────────────────────────────────────────────────────

check('pointerdown קורא ל-preventDefault', () => {
  // בלעדיו העכבר בוחר טקסט תוך כדי גרירה, והדפדפן עלול להתחיל גרירת
  // ברירת מחדל משלו.
  const h = makeHarness();
  h.fire('pointerdown', h.pt(1, 1000));
  eq(h.prevented.length, 1, 'קריאות preventDefault');
});

check('ההמשך מאזין על document, לא רק על המפריד', () => {
  // עם לכידה האירוע ממוען למפריד ומבעבע ל-``document``; בלי לכידה הוא
  // מגיע ל-``document`` ישירות. מאזין רק על המפריד היה מאבד את הגרירה
  // בדיוק במקרה שבו הלכידה נכשלה.
  const h = makeHarness();
  eq(h.onResizer.pointerdown, true, 'pointerdown על המפריד');
  ['pointermove', 'pointerup', 'pointercancel'].forEach((e) => {
    if (!h.onDocument[e]) throw new Error(`${e} אינו מאזין על document`);
  });
});

check('כשל בלכידה אינו מקפיא את הגרירה', () => {
  // ``setPointerCapture`` יכול לזרוק. הגרירה חייבת להמשיך לעבוד, ובעיקר
  // להסתיים כמו שצריך — אחרת ה-UI נשאר במצב פעיל עד רענון.
  const h = makeHarness(280, /* captureFails */ true);
  h.fire('pointerdown', h.pt(1, 1000));
  eq(h.captured.length, 0, 'לא נלכד דבר');
  h.fire('pointermove', h.pt(1, 1050));
  eq(h.width(), 230, 'הגרירה בכל זאת עובדת');
  h.fire('pointerup', h.pt(1, 1050));
  eq(h.classes.has('active'), false, 'הסתיימה ונוקתה');
  eq(h.body.style.cursor, '', 'הסמן שוחזר');
});

check('גרירה משנה את הרוחב', () => {
  const h = makeHarness(280);
  h.fire('pointerdown', h.pt(1, 1000));
  h.fire('pointermove', h.pt(1, 1060));   // 60 ימינה, והסיידבר מימין ← מצטמצם
  eq(h.width(), 220, 'הרוחב אחרי גרירה של 60');
});

check('הסיידבר מימין: גרירה שמאלה מרחיבה', () => {
  // **זה הבאג שתוקן.** הנוסחה ``startWidth + dx`` היא נוסחת LTR; בפריסת
  // RTL היא הזיזה את הקצה הפוך מהאצבע, והמפריד ברח ממנה.
  const h = makeHarness(280, false, 'right');
  h.fire('pointerdown', h.pt(1, 1002));
  h.fire('pointermove', h.pt(1, 942));          // 60 שמאלה
  eq(h.width(), 340, 'התרחב');
  h.fire('pointermove', h.pt(1, 1062));         // 60 ימינה מנקודת ההתחלה
  eq(h.width(), 220, 'הצטמצם');
});

check('הסיידבר משמאל: גרירה ימינה מרחיבה', () => {
  // הצד השני של אותו כלל. הסימן נגזר מהפריסה, ולכן אינו מניח RTL.
  const h = makeHarness(280, false, 'left');
  h.fire('pointerdown', h.pt(1, 1002));
  h.fire('pointermove', h.pt(1, 1062));         // 60 ימינה
  eq(h.width(), 340, 'התרחב');
  h.fire('pointermove', h.pt(1, 942));          // 60 שמאלה
  eq(h.width(), 220, 'הצטמצם');
});

check('הרוחב מהודק לגבולות ולא נזרק', () => {
  // הצורה הקודמת התעלמה מערך שחרג, ולכן קפיצה אחת מעבר לגבול הותירה את
  // הסיידבר על הערך התקין האחרון במקום על הגבול עצמו.
  const h = makeHarness(280);
  h.fire('pointerdown', h.pt(1, 1000));
  h.fire('pointermove', h.pt(1, -9999));
  eq(h.width(), MAX, 'מעבר למקסימום');
  h.fire('pointermove', h.pt(1, 9999));
  eq(h.width(), MIN, 'מתחת למינימום');
});

check('אצבע שנייה אינה חוטפת את הגרירה', () => {
  const h = makeHarness(280);
  h.fire('pointerdown', h.pt(1, 1000));
  h.fire('pointermove', h.pt(1, 1030));
  eq(h.width(), 250, 'אחרי האצבע הראשונה');
  h.fire('pointerdown', h.pt(2, 1000));
  h.fire('pointermove', h.pt(2, 1400));
  eq(h.width(), 250, 'אצבע שנייה לא משנה דבר');
  h.fire('pointermove', h.pt(1, 1060));
  eq(h.width(), 220, 'האצבע המקורית ממשיכה');
});

check('לחצן שאינו ראשי אינו מתחיל גרירה', () => {
  const h = makeHarness(280);
  h.fire('pointerdown', h.pt(9, 1000, { button: 2, pointerType: 'mouse' }));
  h.fire('pointermove', h.pt(9, 1400));
  eq(h.width(), 280, 'הרוחב לא זז');
});

// ─── סיום וניקוי ────────────────────────────────────────────────────────

check('pointerup מסיים ומנקה', () => {
  const h = makeHarness(280);
  h.fire('pointerdown', h.pt(1, 1000));
  eq(h.classes.has('active'), true, 'active בזמן הגרירה');
  h.fire('pointermove', h.pt(1, 1030));
  h.fire('pointerup', h.pt(1, 1030));
  eq(h.classes.has('active'), false, 'active הוסר');
  eq(h.body.style.cursor, '', 'הסמן שוחזר');
  h.fire('pointermove', h.pt(1, 1400));
  eq(h.width(), 250, 'תזוזה אחרי הסיום אינה משנה דבר');
});

check('pointercancel מסיים בדיוק כמו pointerup', () => {
  // **מחווה של המערכת שקוטעת את הגרירה שולחת cancel ולא up.** בלי מאזין
  // לו הדגל היה נשאר דלוק, והסיידבר היה משתנה בכל תזוזה עתידית.
  const h = makeHarness(280);
  h.fire('pointerdown', h.pt(1, 1000));
  h.fire('pointermove', h.pt(1, 1030));
  h.fire('pointercancel', h.pt(1, 1030));
  eq(h.classes.has('active'), false, 'active הוסר');
  eq(h.body.style.cursor, '', 'הסמן שוחזר');
  h.fire('pointermove', h.pt(1, 1400));
  eq(h.width(), 250, 'תזוזה אחרי הביטול אינה משנה דבר');
});

check('אחרי סיום אפשר לגרור שוב', () => {
  const h = makeHarness(280);
  h.fire('pointerdown', h.pt(1, 1000));
  h.fire('pointerup', h.pt(1, 1000));
  h.fire('pointerdown', h.pt(2, 1000));
  h.fire('pointermove', h.pt(2, 1040));
  eq(h.width(), 240, 'גרירה שנייה עובדת');
});

// ─── ה-CSS שבלעדיו כל זה מת בדפדפן ─────────────────────────────────────

check('ל-.resizer יש touch-action: pan-y', () => {
  // בלי הכרזה כלשהי הדפדפן בולע את התנועה כגלילה וגרירת המגע מתה. עם
  // ``none`` היא עובדת, אבל גם החלקה אנכית שמתחילה על הרצועה מתה — ולרצועה
  // יש אב גליל. ``pan-y`` מחלק לפי ציר ומשאיר את שניהם.
  const css = fs.readFileSync(CSS, 'utf8');
  const i = css.indexOf('.resizer {');
  if (i < 0) throw new Error('בלוק .resizer לא נמצא');
  const block = css.slice(i, css.indexOf('}', i));
  const m = block.match(/touch-action\s*:\s*([a-z- ]+)/);
  if (!m) throw new Error('touch-action חסר — גרירת מגע לא תעבוד בדפדפן');
  const value = m[1].trim();
  if (value === 'none') {
    throw new Error('touch-action: none חוסם גם גלילה אנכית על הרצועה — צריך pan-y');
  }
  if (value !== 'pan-y') throw new Error(`ציפיתי ל-pan-y, יש ${value}`);
});

check('אזור המגע רחב מהקו הנראה', () => {
  // 4px הם יעד סביר לעכבר ובלתי אפשרי לאצבע.
  const css = fs.readFileSync(CSS, 'utf8');
  const i = css.indexOf('.resizer::before');
  if (i < 0) throw new Error('.resizer::before חסר — אין הרחבת אזור מגע');
  const block = css.slice(i, css.indexOf('}', i));
  const neg = block.match(/-(\d+)px/g) || [];
  if (neg.length < 2) throw new Error(`ציפיתי להרחבה לשני הצדדים, מצאתי: ${neg.join(', ') || 'כלום'}`);
});

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
