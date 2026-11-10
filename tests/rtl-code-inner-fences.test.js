'use strict';
/**
 * בדיקות לחלוקה של בלוק עברי לקטעים — ``innerFences`` ו-``innerFenceRanges`` ב-
 * ``webapp/static/js/utils/rtl-code.js``. דוגמת קוד — גדר פנימית (```` ```python ````)
 * עד הגדר הסוגרת שלה — מוצגת משמאל לימין; כל השאר נשאר בכיוון הבלוק, כולל גדר
 * פנימית שהיא טקסט לפי אותו כלל של בלוק רגיל (``hasExplicitLanguageName`` ו-
 * ``isHebrewMajority``).
 *
 * הרצה:  node tests/rtl-code-inner-fences.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * **מה הבדיקות האלה כן מוכיחות:** איפה גדר נפתחת ואיפה היא נגמרת, לפי
 * CommonMark 0.31.2 סעיף 4.5 (הדוגמאות שמצוטטות במספרן, מ-``spec.json`` של
 * הגרסה); ש**markdown-it עצמו** מסכים עם החלוקה על 30,000 מסמכים אקראיים — הוא
 * הפרסר שמרנדר את המסמכים. הוא נטען מ-``node_modules`` שבגיט, בגרסה ש-
 * ``package-lock.json`` נועל גם לבניית הבאנדל; שבלוק פנימי מוכרע **בדיוק** כמו
 * שהיה מוכרע כבלוק רגיל — שם השפה כפי ש-markdown-it מפיק אותו למחלקה, והתוכן
 * כפי שהוא שם אותו ב-``code`` — על אלפי בלוקים אקראיים; שבתוך בלוק פנימי שהוא
 * טקסט אותה חלוקה חלה שוב; שטווחי התווים מכסים בדיוק את שורות הקטע, עם ירידת
 * השורה שאחרי הגדר הסוגרת; ושהחלוקה לינארית באורך הקלט, גם בשרשרת של גדרות
 * מקוננות.
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
  // התוכן לועזי בכוונה: ``md`` בלי עברית הוא קוד, ולכן הקטע נראה כאן כולו —
  // ומה שנבדק הוא איפה הוא נגמר. עם תוכן עברי הוא טקסט, ואין קטע לראות.
  eq(parts(['טקסט לפני', '````md', '```', 'inside', '```', '````', 'טקסט אחרי']),
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

// ---------- גדר פנימית שהיא טקסט ----------
//
// גדר פנימית מוכרעת באותו כלל כמו בלוק רגיל: שם שפה שאינו מצהיר על קוד
// (``hasExplicitLanguageName``) ותוכן שעובר את ``isHebrewMajority`` — טקסט, ונשאר
// עם הבלוק, כולל שורות הגדר שלו. כל השאר קוד, כמו קודם.

check('גדר פנימית בלי שם שפה, עם תוכן עברי — טקסט, כולל שורות הגדר', () => {
  eq(parts(['## כותרת', '```', 'הסבר בעברית', 'ועוד שורה', '```', 'סוף']), [['rtl', 0, 6]]);
});

check('כל שם ב-plainLanguageNames, עם תוכן עברי — טקסט; עם תוכן לועזי — קוד', () => {
  ok(R.plainLanguageNames.length > 0, 'הרשימה ריקה — הבדיקה לא בודקת כלום');
  for (const name of R.plainLanguageNames) {
    eq(parts(['לפני', '```' + name, 'הסבר בעברית', '```', 'אחרי']), [['rtl', 0, 5]], name);
    eq(parts(['לפני', '~~~ ' + name + ' כותרת', 'הסבר בעברית', '~~~', 'אחרי']), [['rtl', 0, 5]], name + ' בטילדות');
    eq(parts(['לפני', '```' + name, 'npm install', '```', 'אחרי']),
      [['rtl', 0, 1], ['ltr', 1, 4], ['rtl', 4, 5]], name + ' לועזי');
  }
});

check('שם שפה מוצהר — קוד גם כשהתוכן עברי, באותה השוואה כמו בבלוק רגיל', () => {
  // ``Text`` רגיש לרישיות ו-``mdx`` אינו ``md`` — ההסבר ב-``hasExplicitLanguageName``.
  for (const name of ['python', 'js', 'Text', 'MD', 'mdx', 'texture', 'textעברית']) {
    eq(parts(['לפני', '```' + name, 'הסבר בעברית', '```', 'אחרי']),
      [['rtl', 0, 1], ['ltr', 1, 4], ['rtl', 4, 5]], name);
  }
  // והגבול אחרי השם: ``md,`` ו-``md-x`` הם ``md``.
  for (const name of ['md,', 'md-x', 'text.']) {
    eq(parts(['לפני', '```' + name, 'הסבר בעברית', '```', 'אחרי']), [['rtl', 0, 5]], name);
  }
});

check('הספירה היא של התוכן בלבד, לא של שורות הגדר', () => {
  // ``markdown`` בשורת הגדר הוא שמונה אותיות לטיניות. אילו נספרו, שלוש האותיות
  // העבריות היו פחות מ-30%, והבלוק היה קוד.
  eq(parts(['לפני', '```markdown', 'אבג', '```']), [['rtl', 0, 4]]);
  eq(R.isHebrewMajority('```markdown\nאבג\n```'), false, 'בקרה: עם שורות הגדר הסף לא עובר');
});

check('גדר טקסט שלא נסגרה — התוכן שלה עד סוף הבלוק', () => {
  eq(parts(['לפני', '```', 'הסבר בעברית', 'עוד']), [['rtl', 0, 4]]);
  eq(parts(['לפני', '```', 'npm install', 'עוד']), [['rtl', 0, 1], ['ltr', 1, 4]]);
});

check('בתוך גדר טקסט, דוגמת קוד שוב משמאל לימין', () => {
  eq(parts(['א', '````md', 'ב עברית', '```python', 'x', '```', '````', 'ג']),
    [['rtl', 0, 3], ['ltr', 3, 6], ['rtl', 6, 8]]);
  eq(parts(['```', 'עברית כאן', '~~~python', 'print(1)', '~~~', '```']),
    [['rtl', 0, 2], ['ltr', 2, 5], ['rtl', 5, 6]]);
  // שלוש רמות: טקסט בתוך טקסט, וקוד בפנים.
  eq(parts(['`````', 'עברית', '````text', 'עוד עברית', '```js', 'x', '```', '````', '`````']),
    [['rtl', 0, 4], ['ltr', 4, 7], ['rtl', 7, 9]]);
});

check('בתוך דוגמת קוד לא נשאל דבר — גם גדר טקסט בתוכה היא חלק מהקוד', () => {
  eq(parts(['לפני', '````js', '```', 'הסבר בעברית', '```', '````', 'אחרי']),
    [['rtl', 0, 1], ['ltr', 1, 6], ['rtl', 6, 7]]);
});

check('שורה שסוגרת כמה גדרות פתוחות סוגרת את החיצונית, והפנימית נגמרת לפניה', () => {
  // ``````` סוגרת גם את ```js (3) וגם את ````text (4); החיצונית מנצחת, ו-```js
  // נגמרת בשורה שלפני — כמו גדר שלא נסגרה עד סוף התוכן של ````text.
  eq(parts(['````text', 'עברית', '```js', 'x', '````', 'אחרי']),
    [['rtl', 0, 2], ['ltr', 2, 4], ['rtl', 4, 6]]);
  // ``` קצרה מ-````, ולכן היא סוגרת רק את ```md שבפנים.
  eq(parts(['````md', 'עברית', '```python', 'x', '```', 'שוב עברית', '````', 'אחרי']),
    [['rtl', 0, 2], ['ltr', 2, 5], ['rtl', 5, 8]]);
  // ~~~ פתוחה בפנים, ``` סוגרת את החיצונית — אותו תו בלבד.
  eq(parts(['```', 'עברית', '~~~python', 'x', '```', 'אחרי']),
    [['rtl', 0, 2], ['ltr', 2, 4], ['rtl', 4, 6]]);
});

check('ההבדל המתועד מ-markdown-it: שם שפה עם ישות HTML אינו מפוענח', () => {
  // markdown-it 14.1.0 מעביר את ``info`` דרך ``unescapeAll``, ולכן ``&#116;ext``
  // הוא ``text`` שם (בקרה), וכאן הוא נשאר שם אחר — קוד. ההסבר ב-``fenceOpening``.
  // מי שיוסיף פענוח יפיל את הבדיקה הזו, וזה המקום לעדכן גם את ההסבר.
  const html = new MarkdownIt().render('```&#116;ext\nx\n```\n');
  ok(html.includes('class="language-text"'), `בקרה: markdown-it לא פענח — ${html}`);
  eq(R.fenceOpening('```&#116;ext').lang, '&#116;ext');
  eq(parts(['לפני', '```&#116;ext', 'הסבר בעברית', '```']), [['rtl', 0, 1], ['ltr', 1, 4]]);
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

// ---------- השוואה מול markdown-it: איפה גדר נגמרת ----------
//
// **הכלל כתוב כאן פעם שנייה, ולכן מישהו צריך לצעוק כשהוא נסחף.** markdown-it
// הוא הפרסר שמחליט איפה בלוק קוד נגמר במסמך, ו-``innerFences`` מחליטה איפה קטע
// נגמר בתוך בלוק. אילו נפרדו, שורה שהפרסר רואה בתוך בלוק הייתה מוצגת כאילו היא
// כבר מחוצה לו. לכל מסמך אקראי שואלים את שניהם: האם השורה הראשונה פותחת גדר,
// ואם כן — עד איזו שורה היא נמשכת. **ההשוואה עוברת דרך ``innerFences`` עצמה ולא
// דרך פונקציית עזר**, כי הסגירה שם נעשית במחסנית של כל הגדרות הפתוחות, וגדרות
// שנפתחות בתוך גדר בלי שם שפה הן בדיוק מה שיכול היה להסיט אותה. אין עברית
// במסמכים, ולכן כל גדר כאן היא קוד, והקטע הראשון הוא הגדר שנפתחה בשורה 0.
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

check(`markdown-it ${MD_IT_VERSION} מסכים עם fenceOpening ועם innerFences על 30,000 מסמכים אקראיים`, () => {
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
    const [head] = R.innerFences(lines.join('\n'));
    if (head.ltr !== mdOpens || (mdOpens && head.from !== 0)) {
      throw new Error(`קטע ראשון: markdown-it פותח=${mdOpens}, שלנו=${JSON.stringify(head)} על ${JSON.stringify(lines)}`);
    }
    if (!open) continue;
    fences += 1;
    if (first.map[1] !== head.to) {
      throw new Error(`סגירה: markdown-it עד ${first.map[1]}, שלנו עד ${head.to} על ${JSON.stringify(lines)}`);
    }
  }
  // אם המחולל הפסיק לייצר גדרות, ההשוואה הייתה עוברת בלי לבדוק כלום.
  ok(fences > 5000, `רק ${fences} מסמכים נפתחו בגדר`);
});

// ---------- השוואה מול markdown-it: בלוק פנימי מוכרע כמו בלוק רגיל ----------
//
// **ההחלטה על בלוק פנימי היא עותק של ההחלטה על בלוק רגיל**, ולכן גם היא צריכה
// מישהו שיצעק. בלוק רגיל מוכרע ב-``applyRtlIfHebrew``: ``hasExplicitLanguage`` על
// המחלקה ש-markdown-it כותב, ו-``isHebrewMajority`` על התוכן שהוא שם ב-``code``.
// לכל בלוק אקראי — שורת גדר, תוכן, גדר סוגרת — markdown-it מרנדר אותו כמסמך
// בפני עצמו, ומשם נגזרת ההחלטה הצפויה: המחלקה מה-HTML (שם השפה עובר דרך
// ה-renderer של markdown-it, לא דרך הקוד שנבדק) והתוכן מ-``token.content``. אחר
// כך אותו בלוק מוכנס לתוך טקסט עברי, ו-``innerFences`` צריכה להחליט אותו דבר.
//
// אין ``\`` ו-``&`` בשמות: שם ``unescapeAll`` של markdown-it משנה את השם, וזה
// ההבדל המתועד שיש לו בדיקה משלו למעלה. האפשרויות של הצרכנים (``breaks``,
// ``linkify``, ``typographer``) חלות על טקסט בשורה ולא על גדר, ולכן המופע כאן
// בלי אפשרויות.

const INFOS = [
  '', 'text', 'md', 'markdown', 'plaintext', 'txt', 'none', 'nohighlight', 'python', 'js', 'bash',
  'Text', 'MD', 'mdx', 'texture', 'md,', 'md-x', '-x', 'text.', 'textעברית', 'עברית',
  'text title', '  md  כותרת', 'python {1,3}', 'md\u00a0x', '\u00a0text',
];
const CONTENT = [
  'שלום עולם', 'הסבר קצר על הדוגמה', '- פריט ראשון', 'npm install', 'x = 1', 'const a = b;',
  'עברית and some English', 'A', 'ב', '', '   ', '1234', '→ ←',
];
const MARKERS = ['```', '````', '~~~'];

function pick(random, list) {
  return list[Math.floor(random() * list.length)];
}

check(`בלוק פנימי מוכרע כמו בלוק רגיל ב-markdown-it ${MD_IT_VERSION} — 20,000 בלוקים אקראיים`, () => {
  const md = new MarkdownIt();
  const random = rng(20261110);
  const seen = { text: 0, code: 0 };
  for (let n = 0; n < 20000; n++) {
    const marker = pick(random, MARKERS);
    const body = [];
    for (let k = 0, count = 1 + Math.floor(random() * 4); k < count; k++) body.push(pick(random, CONTENT));
    const block = [marker + pick(random, INFOS), ...body, marker];

    const html = md.render(block.join('\n') + '\n');
    const tokens = md.parse(block.join('\n') + '\n', {});
    if (tokens.length !== 1 || tokens[0].type !== 'fence') {
      throw new Error(`המחולל ייצר משהו שאינו בלוק אחד: ${JSON.stringify(block)}`);
    }
    const cls = /<code(?: class="([^"]*)")?>/.exec(html);
    const className = (cls && cls[1] ? cls[1] : '').replace(/&quot;/g, '"').replace(/&amp;/g, '&');
    const expected = !R.hasExplicitLanguage({ className }) && R.isHebrewMajority(tokens[0].content);

    const doc = ['טקסט עברי לפני הבלוק', ...block, 'טקסט עברי אחרי הבלוק'];
    const inner = R.innerFences(doc.join('\n')).filter((p) => p.ltr);
    const ours = inner.length === 0;
    if (!ours && JSON.stringify(inner) !== JSON.stringify([{ ltr: true, from: 1, to: block.length + 1 }])) {
      throw new Error(`הקטע אינו הבלוק כולו: ${JSON.stringify(inner)} על ${JSON.stringify(block)}`);
    }
    if (ours !== expected) {
      throw new Error(`בלוק רגיל=${expected ? 'טקסט' : 'קוד'}, פנימי=${ours ? 'טקסט' : 'קוד'} `
        + `(מחלקה ${JSON.stringify(className)}) על ${JSON.stringify(block)}`);
    }
    seen[expected ? 'text' : 'code'] += 1;
  }
  // שני הצדדים צריכים להופיע הרבה, אחרת ההשוואה בודקת רק אחד מהם.
  ok(seen.text > 3000 && seen.code > 3000, `טקסט ${seen.text}, קוד ${seen.code}`);
});

// ---------- אותה חלוקה בכל רמה ----------
//
// בתוך בלוק פנימי שהוא טקסט, הקטעים הם בדיוק מה ש-``innerFences`` הייתה נותנת
// על התוכן שלו לבד. כך "אותה שאלה בכל רמה" נבדקת כתכונה, ולא רק בשלוש הדוגמאות
// שכתובות ביד למעלה. אין בתוכן שורה של ארבעה גרשיים ומעלה בלבד — היא הייתה
// סוגרת את הבלוק החיצוני, וזו כבר שאלה אחרת.

const NESTED_LINES = [
  'שלום עולם', 'הסבר בעברית', 'x', 'npm install', '', '```', '```python', '```md', '~~~', '~~~js',
  '```text', '~~~~', '``', '- פריט',
];

check('בתוך בלוק פנימי שהוא טקסט — אותם קטעים כמו על התוכן שלו לבד, 10,000 מסמכים', () => {
  const random = rng(20261111);
  let textBlocks = 0;
  for (let n = 0; n < 10000; n++) {
    const content = [];
    for (let k = 0, count = 1 + Math.floor(random() * 8); k < count; k++) content.push(pick(random, NESTED_LINES));
    const doc = ['מבוא', '````' + pick(random, ['', 'md', 'text']), ...content, '````', 'סוף'];
    const all = R.innerFences(doc.join('\n'));
    if (all.some((p) => p.ltr && p.from === 1)) continue;  // הבלוק החיצוני הוא קוד — אין כאן מה להשוות
    textBlocks += 1;
    const inside = all.filter((p) => p.ltr).map((p) => [p.from - 2, p.to - 2]);
    const alone = R.innerFences(content.join('\n')).filter((p) => p.ltr).map((p) => [p.from, p.to]);
    eq(inside, alone, JSON.stringify(doc));
  }
  ok(textBlocks > 3000, `רק ${textBlocks} בלוקים חיצוניים היו טקסט`);
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

check('שרשרת של גדרות פתוחות זו בתוך זו — לינארי במספר השורות', () => {
  // כל ```md פותחת גדר בתוך הקודמת (יש לה שם, ולכן אינה סוגרת), והשורה העברית
  // בסוף הופכת כל אחת מהן לטקסט — כלומר ההחלטה נשאלת בכל רמה. רקורסיה שסורקת כל
  // רמה מחדש הייתה ריבועית כאן. בבקרה: הקוד שלפני השינוי עובר גם הוא, כי לא נכנס
  // לגדרות בכלל — זו בדיקה של "לא לשבור", לא של התיקון.
  const g = growth((k) => ('```md\n'.repeat(2000 * k)) + 'א'.repeat(12000 * k) + '\n');
  ok(g < GROWTH_LIMIT, `הזמן גדל פי ${g.toFixed(1)} על קלט גדול פי 4`);
  const depth = 50;
  eq(R.innerFences('```md\n'.repeat(depth) + 'א'.repeat(6 * depth) + '\n').filter((p) => p.ltr), [],
    'בקרה: כל הגדרות בשרשרת הן טקסט');
});

console.log(`rtl-code inner fences: ${passed} passed, ${failed} failed`);
process.exit(failed === 0 ? 0 : 1);
