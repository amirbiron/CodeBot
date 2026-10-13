'use strict';
/**
 * בדיקות לחלוקה של בלוק עברי לקטעים — ``innerFences`` ו-``innerFenceRanges`` ב-
 * ``webapp/static/js/utils/rtl-code.js``. קטע שמתחיל בגדר פנימית (```` ```python ````)
 * ונגמר בגדר הסוגרת שלה מוצג משמאל לימין; כל השאר נשאר בכיוון הבלוק.
 *
 * הרצה:  node tests/rtl-code-inner-fences.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * **מה הבדיקות האלה כן מוכיחות:** איפה גדר נפתחת ואיפה היא נגמרת, לפי
 * CommonMark 0.31.2 סעיף 4.5 (הדוגמאות שמצוטטות במספרן, מ-``spec.json`` של
 * הגרסה); ש**markdown-it עצמו** מסכים עם הכלל על 30,000 מסמכים אקראיים — הוא
 * הפרסר שמרנדר את המסמכים. הוא נטען מ-``node_modules`` שבגיט, בגרסה ש-
 * ``package-lock.json`` נועל גם לבניית הבאנדל; שטווחי התווים מכסים בדיוק את
 * שורות הקטע, עם ירידת השורה שאחרי הגדר הסוגרת; ושהחלוקה לינארית באורך הקלט.
 *
 * **ומה לא:** שהעטיפה נבנית נכון ב-DOM ושהקטע באמת מצויר משמאל לימין. ``vm``
 * אינו דפדפן, ואין בריפו DOM לבדיקות Node. את זה מוכיחה
 * ``tests/test_rtl_inner_fences_browser.py``, בשלושת המשטחים.
 */

import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';
import MarkdownIt from 'markdown-it';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(__dirname, '..', 'webapp', 'static', 'js', 'utils', 'rtl-code.js');

// הקובץ הוא script קלאסי שמגדיר ``window.RtlCode`` — ``package.json`` מוגדר
// ``"type": "module"``, ולכן ``require()`` עליו לא היה עובד.
function loadRtlCode() {
  const sandbox = { window: {} };
  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox);
  return sandbox.window.RtlCode;
}

const R = loadRtlCode();

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed += 1; }
  catch (e) { failed += 1; console.error(`✗ ${name}\n    ${e && e.message}`); }
}
function eq(actual, expected, what) {
  const a = JSON.stringify(actual), b = JSON.stringify(expected);
  if (a !== b) throw new Error(`${what || ''} — ציפיתי ל-${b}, קיבלתי ${a}`);
}
function ok(value, what) { if (!value) throw new Error(what || 'ציפיתי לאמת'); }

/** הקטעים כרשימה קריאה: ``['rtl', 0, 3]`` לכל קטע. */
function parts(lines) {
  return R.innerFences(lines.join('\n')).map((p) => [p.ltr ? 'ltr' : 'rtl', p.from, p.to]);
}

// ---------- החלוקה לקטעים ----------

check('דוגמת קוד בתוך בלוק עברי היא קטע ltr אחד, מגדר לגדר, כולל שתיהן', () => {
  eq(parts(['## התקנה', 'הריצו את הפקודה:', '', '```python', 'def greet(name):',
    '    return f"שלום {name}"', '```', '', 'סוף הדוגמה.']),
  [['rtl', 0, 3], ['ltr', 3, 7], ['rtl', 7, 9]]);
});

check('בלוק בלי גדר פנימית הוא קטע אחד, בלי ltr', () => {
  // הרשימה מ"המיפוי השלם בייבוא ערכת VS Code": שורה שמתחילה במזהה לועזי,
  // ופריט שכולו באנגלית. הכיוון נקבע לפי סוג התוכן ולא לפי האותיות, ולכן
  // שתיהן נשארות עם הבלוק.
  eq(parts(['**מה המייבא לוקח:** ב-`theme_parser_service.py` רק שלושה צבעים מגיעים:',
    '- `editor.background` → רקע המסמך (`--md-surface`)', '- `editor.foreground`']),
  [['rtl', 0, 3]]);
});

check('גדר שלא נסגרה נמשכת עד סוף הבלוק', () => {
  eq(parts(['שורה ראשונה', '```js', 'עדיין בתוך אותו בלוק']), [['rtl', 0, 1], ['ltr', 1, 3]]);
});

check('דוגמה 124: ```` אינה נסגרת ב-``` שבתוכה', () => {
  eq(parts(['טקסט לפני', '````md', '```', 'בתוך', '```', '````', 'טקסט אחרי']),
    [['rtl', 0, 1], ['ltr', 1, 6], ['rtl', 6, 7]]);
});

check('דוגמה 147: שורה עם שם שפה אינה סוגרת', () => {
  eq(parts(['```', '``` aaa', '```']), [['ltr', 0, 3]]);
});

check('דוגמה 145: גרש בשארית של גדר גרשיים — אין גדר', () => {
  eq(parts(['``` aa ```', 'foo']), [['rtl', 0, 2]]);
});

check('דוגמה 146: בגדר טילדות השארית יכולה להכיל גרשיים', () => {
  eq(parts(['~~~ aa ``` ~~~', 'foo', '~~~']), [['ltr', 0, 3]]);
});

check('דוגמה 121: שני גרשיים אינם גדר', () => {
  eq(parts(['``', 'foo', '``']), [['rtl', 0, 3]]);
});

check('גדר נסגרת רק באותו תו', () => {
  eq(parts(['```', 'x', '~~~', 'y', '```', 'אחרי']), [['ltr', 0, 5], ['rtl', 5, 6]]);
  eq(parts(['~~~~', 'x', '````', '~~~', 'y', '~~~~~', 'אחרי']), [['ltr', 0, 6], ['rtl', 6, 7]]);
});

check('סגירה עם רווחים או טאב אחרי הגדר — כן; עם טקסט — לא', () => {
  eq(parts(['```js', 'x', '```   ', 'אחרי']), [['ltr', 0, 3], ['rtl', 3, 4]]);
  eq(parts(['```js', 'x', '```\t', 'אחרי']), [['ltr', 0, 3], ['rtl', 3, 4]]);
  eq(parts(['```js', 'x', '``` y', 'עוד']), [['ltr', 0, 4]]);
});

check('הזחה לפני הגדר אינה נבדקת, בכוונה: דוגמה בתוך פריט רשימה היא קוד', () => {
  // CommonMark מגביל לשלושה רווחים, אבל הטקסט של הבלוק מנותק מהרשימה שהוא
  // נכתב בה. זו הסטייה היחידה מ-markdown-it, ולכן ההשוואה למטה מדלגת עליה.
  eq(parts(['1. התקינו:', '    ```bash', '    npm install', '    ```', '2. הפעילו']),
    [['rtl', 0, 1], ['ltr', 1, 4], ['rtl', 4, 5]]);
  eq(parts(['\t```', 'x', '\t```']), [['ltr', 0, 3]]);
});

check('שתי דוגמאות באותו בלוק — שני קטעים, והטקסט ביניהם נשאר בחוץ', () => {
  eq(parts(['א', '```js', 'x', '```', 'ב', '~~~py', 'y', '~~~', 'ג']),
    [['rtl', 0, 1], ['ltr', 1, 4], ['rtl', 4, 5], ['ltr', 5, 8], ['rtl', 8, 9]]);
});

check('ירידת השורה בסוף הבלוק נשארת קטע משלה', () => {
  // markdown-it מסיים את התוכן של בלוק ב-"\n", ולכן השורה האחרונה ב-split ריקה.
  eq(R.innerFences('```js\nx\n```\n').map((p) => [p.ltr, p.from, p.to]),
    [[true, 0, 3], [false, 3, 4]]);
});

// ---------- טווחי התווים ----------

check('הטווח מכסה את שורות הקטע ואת ירידת השורה שאחרי הגדר הסוגרת', () => {
  const text = 'הריצו:\n\n```python\nprint(1)\n```\n\nסוף\n';
  const ranges = R.innerFenceRanges(text);
  eq(ranges.length, 1, 'קטע אחד');
  eq(text.slice(ranges[0].start, ranges[0].end), '```python\nprint(1)\n```\n');
  // ירידת השורה שלפני הגדר הפותחת נשארת בחוץ — השורה הריקה לא נעלמת.
  eq(text.slice(0, ranges[0].start), 'הריצו:\n\n');
  eq(text.slice(ranges[0].end), '\nסוף\n');
});

check('גדר אחרונה בלי ירידת שורה אחריה — הטווח עד סוף הטקסט', () => {
  const text = 'א\n```\nx\n```';
  const [r] = R.innerFenceRanges(text);
  eq([r.start, r.end], [2, text.length]);
});

check('גדר שלא נסגרה — הטווח עד סוף הטקסט, כולל ירידת השורה האחרונה', () => {
  const text = 'א\n```js\nx\n';
  const [r] = R.innerFenceRanges(text);
  eq(text.slice(r.start, r.end), '```js\nx\n');
});

check('בלי גדר — אין טווחים', () => {
  eq(R.innerFenceRanges('שורה\n- `editor.foreground`\n'), []);
  eq(R.innerFenceRanges(''), []);
});

check('הטווחים אינם חופפים, ממוינים, ובגבולות של שורות', () => {
  const text = ['א', '```js', 'x', '```', 'ב', '````', '```', 'y', '```', '````', 'ג'].join('\n');
  const ranges = R.innerFenceRanges(text);
  eq(ranges.length, 2, 'שני קטעים');
  ranges.forEach((r, k) => {
    ok(r.start < r.end, 'טווח לא ריק');
    ok(r.start === 0 || text[r.start - 1] === '\n', 'מתחיל בתחילת שורה');
    ok(r.end === text.length || text[r.end - 1] === '\n', 'נגמר אחרי ירידת שורה');
    if (k) ok(ranges[k - 1].end <= r.start, 'אחרי הקודם');
  });
});

// ---------- השוואה מול markdown-it ----------
//
// **הכלל כתוב כאן פעם שנייה, ולכן מישהו צריך לצעוק כשהוא נסחף.** markdown-it
// הוא הפרסר שמחליט איפה בלוק קוד נגמר במסמך, ו-``fenceOpening``/``fenceEnd``
// מחליטים איפה קטע נגמר בתוך בלוק. אילו נפרדו, שורה שהפרסר רואה בתוך בלוק
// הייתה מוצגת כאילו היא כבר מחוצה לו. לכל מסמך אקראי שואלים את שניהם: האם
// השורה הראשונה פותחת גדר, ואם כן — באיזו שורה היא נסגרת, או שאינה נסגרת.
//
// שורת ``SENTINEL`` בסוף מבחינה בין "נסגרה בשורה האחרונה" ל"לא נסגרה": היא
// לעולם אינה סוגרת, ולכן גדר שלא נסגרה בולעת אותה ו-``map[1]`` מגיע לסוף.
//
// השורות בלי הזחה, או עם עד שלושה רווחים — שם שני הכללים אמורים להסכים.
// הזחה של ארבעה רווחים או טאב היא הסטייה המכוונת (ראו למעלה), ואינה כאן.

const LINES = [
  '```', '````', '`````', '~~~', '~~~~', '```js', '```` md', '~~~ a`b', '``` a`', '``` ```',
  '``', '~~', '`~~', '~`~', 'x', '', '```   ', '````  ', '```\t', '``` x', '~~~x',
  '  ```', ' ~~~', '   ````', ' ```', '``` ', '- ```', '> ```',
];

// PRNG קבוע (mulberry32), כדי שכישלון ישוחזר בדיוק באותו מסמך.
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// הגרסה נקראת מהחבילה ולא נכתבת בשם הבדיקה, כדי ששדרוג לא ישאיר שם שמתאר גרסה אחרת.
const MD_IT_VERSION = JSON.parse(fs.readFileSync(
  path.join(__dirname, '..', 'node_modules', 'markdown-it', 'package.json'), 'utf8')).version;

check(`markdown-it ${MD_IT_VERSION} מסכים עם fenceOpening ו-fenceEnd על 30,000 מסמכים אקראיים`, () => {
  const md = new MarkdownIt();
  const random = rng(20261013);
  let fences = 0;
  for (let n = 0; n < 30000; n++) {
    const count = 1 + Math.floor(random() * 7);
    const lines = [];
    for (let k = 0; k < count; k++) lines.push(LINES[Math.floor(random() * LINES.length)]);
    lines.push('SENTINEL');
    const tokens = md.parse(lines.join('\n'), {});
    const first = tokens[0];
    const mdOpens = !!first && first.type === 'fence' && first.map[0] === 0;
    const open = R.fenceOpening(lines[0]);
    if (mdOpens !== !!open) {
      throw new Error(`פתיחה: markdown-it=${mdOpens}, שלנו=${!!open} על ${JSON.stringify(lines)}`);
    }
    if (!open) continue;
    fences += 1;
    const mdEnd = first.map[1] === lines.length ? 'לא נסגרה' : first.map[1] - 1;
    const end = R.fenceEnd(lines, 0, open);
    const ours = end === lines.length ? 'לא נסגרה' : end;
    if (mdEnd !== ours) {
      throw new Error(`סגירה: markdown-it=${mdEnd}, שלנו=${ours} על ${JSON.stringify(lines)}`);
    }
  }
  // אם המחולל הפסיק לייצר גדרות, ההשוואה הייתה עוברת בלי לבדוק כלום.
  ok(fences > 5000, `רק ${fences} מסמכים נפתחו בגדר`);
});

// ---------- לינאריות ----------
//
// **זמן מול זמן, ולא תקרה בשניות** — אותה צורה כמו
// ``test_many_style_blocks_with_an_unterminated_region_stay_linear``: אותה
// עבודה על רבע מהקלט ועל כולו, הזמן הקצר ביותר מכל גודל בשלושה סבבים לסירוגין,
// וזמן המעבד של התהליך. ב-Markdown-Docs ביטוי שפיצל את מה שאחרי הגרשיים בתוך
// עצמו ניסה כל חלוקה של רצף רווחים: 400 רווחים — 43ms, 1,600 — 1.6 שניות.
// לינארי נותן פי 4 בערך, וריבועי פי 16.

const GROWTH_LIMIT = 8;

function growth(build) {
  const inputs = [build(1), build(4)];
  const fastest = [Infinity, Infinity];
  for (let round = 0; round < 3; round++) {
    inputs.forEach((text, slot) => {
      const started = process.cpuUsage();
      for (let rep = 0; rep < 5; rep++) R.innerFences(text);
      const used = process.cpuUsage(started);
      fastest[slot] = Math.min(fastest[slot], used.user + used.system);
    });
  }
  return fastest[1] / Math.max(fastest[0], 1);
}

check('שורת גדר עם רצף רווחים ארוך — לינארית באורך השורה', () => {
  // "```" ואחריו רווחים וגרש בסוף: השורה נכשלת בבדיקת הגרש, ובביטוי שמפצל
  // את הרווחים בתוכו זה הקלט שמנסה את כל החלוקות.
  const g = growth((k) => 'כותרת\n```' + ' '.repeat(100000 * k) + '`\nסוף');
  ok(g < GROWTH_LIMIT, `הזמן גדל פי ${g.toFixed(1)} על קלט גדול פי 4`);
});

check('הרבה גדרות במסמך — לינארי במספר השורות', () => {
  const block = 'טקסט\n```js\nx\n````\nעוד\n~~~\ny\n';
  const g = growth((k) => block.repeat(3000 * k));
  ok(g < GROWTH_LIMIT, `הזמן גדל פי ${g.toFixed(1)} על קלט גדול פי 4`);
});

console.log(`rtl-code inner fences: ${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
