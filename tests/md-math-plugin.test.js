/**
 * טסטים ל-webapp/static/js/md-math-plugin.js — זיהוי נוסחאות בתוך הפענוח של markdown-it.
 *
 * הרצה:  node tests/md-math-plugin.test.js
 * (קובץ עצמאי שמריץ את הבדיקות בעצמו ויוצא בקוד 1 בכישלון, כמו ``tests/md-mark-plugin.test.js``:
 *  ``.github/workflows/ci.yml`` מריץ את ``tests/*.test.js`` בלולאה עם ``node "$f"``.)
 *
 * **מה הטסט הזה שומר עליו.** עד התוסף, ``renderMathInElement`` של KaTeX רץ על ה-HTML שאחרי
 * markdown-it. כל זוג ``$`` בטקסט רגיל הפך לנוסחה (מחירים, אופרטורים של מונגו), ו-Markdown השחית את
 * הנוסחה לפני ש-KaTeX ראה אותה: ``\\`` של מטריצה הפך ל-``\``, ובלוק ``$$`` על כמה שורות לא נמצא בכלל.
 *
 * **החוזה הוא מה ש-KaTeX מקבל, ולא איך הוא מצייר.** כל נוסחה בפלט נקראת מה-MathML ש-KaTeX כותב:
 * ``<annotation encoding="application/x-tex">`` מחזיק את המקור בדיוק כמו שהועבר ל-``renderToString``
 * (``buildMathML`` ב-KaTeX 0.16.25), ו-``display="block"`` על ``<math>`` מסמן נוסחת תצוגה. מקרה שאין בו
 * נוסחה נבדק על הפלט המדויק.
 *
 * **בקרה.** אותם מקרים עוברים גם במסלול הישן: markdown-it בלי התוסף, ועל כל צומת טקסט שמחוץ ל-``code``
 * ו-``pre`` — ``splitAtDelimiters`` של KaTeX, עם המפרידים שבשני אתרי הקריאה. זו הפונקציה ש-
 * ``renderMathInElement`` מריץ (``contrib/auto-render``), ונקראת כאן מהקובץ שלו. ההליכה על ה-DOM היא
 * חיקוי: הפלט נחתך לצמתי טקסט לפי התגיות, כי אין כאן DOM. בדיקה שאינה נופלת על המסלול הישן אינה
 * בודקת כלום, ולכן הבקרה סופרת אותן.
 *
 * הקבצים הנבדקים נטענים כמו בדפדפן — script קלאסי שמגדיר ``window.MdMathPlugin`` — כי ``package.json``
 * מוגדר ``"type": "module"``, ולכן ``require()`` רגיל לא היה עובד עליהם.
 */
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';
import MarkdownIt from 'markdown-it';
import markdownItAnchor from 'markdown-it-anchor';
import markdownItTocDoneRight from 'markdown-it-toc-done-right';
import katex from 'katex';
import splitAtDelimiters from 'katex/contrib/auto-render/splitAtDelimiters.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const JS_DIR = path.join(ROOT, 'webapp', 'static', 'js');
const MATH_PATH = path.join(JS_DIR, 'md-math-plugin.js');
const MARK_PATH = path.join(JS_DIR, 'md-mark-plugin.js');
const MD_PREVIEW = path.join(ROOT, 'webapp', 'templates', 'md_preview.html');
const LIVE_PREVIEW = path.join(JS_DIR, 'live-preview.js');

let passed = 0;
let failed = 0;

function check(name, fn) {
  try { fn(); passed += 1; console.log('  ✅', name); }
  catch (e) { failed += 1; console.log('  ❌', name, '\n     ', e.message); }
}

function eq(actual, expected, label) {
  const a = JSON.stringify(actual);
  const b = JSON.stringify(expected);
  if (a !== b) {
    throw new Error(`${label}\n      ציפיתי: ${b}\n      קיבלתי: ${a}`);
  }
}

function read(file) { return fs.readFileSync(file, 'utf8'); }

/** script קלאסי בסנדבוקס טרי, כמו בדפדפן. ``null`` כשהקובץ חסר — כך הבקרה רצה גם על הקוד הישן. */
function loadBrowserScript(file, globalName) {
  if (!fs.existsSync(file)) return null;
  const sandbox = { window: {}, console };
  vm.createContext(sandbox);
  vm.runInContext(read(file), sandbox);
  return sandbox.window[globalName] || null;
}

/**
 * אפשרויות markdown-it **משני אתרי הקריאה**, ולא מוקלדות כאן. אם הן יסטו זו מזו, אחד מהם מריץ
 * תצורה שהטסט לא בודק — וזה נכשל כאן במפורש.
 */
function markdownItOptions(file, marker) {
  const src = read(file);
  const start = src.indexOf(marker);
  if (start < 0) throw new Error(`לא נמצאה יצירת markdown-it ב-${path.basename(file)}`);
  const call = src.slice(start, src.indexOf('});', start));
  const options = {};
  for (const key of ['breaks', 'linkify', 'typographer', 'html']) {
    const m = new RegExp(`\\b${key}:\\s*(true|false)`).exec(call);
    if (!m) throw new Error(`האפשרות ${key} לא נמצאה ב-${path.basename(file)}`);
    options[key] = m[1] === 'true';
  }
  return options;
}

const OPTIONS = markdownItOptions(MD_PREVIEW, 'window.markdownit ? window.markdownit');
const LIVE_OPTIONS = markdownItOptions(LIVE_PREVIEW, 'window.markdownit({');
const markPlugin = loadBrowserScript(MARK_PATH, 'MdMarkPlugin');
const mathPlugin = loadBrowserScript(MATH_PATH, 'MdMathPlugin');

/** המסלול החדש: כמו בשני אתרי הקריאה — המארקר, ואחריו הנוסחאות עם KaTeX. */
function newMd() {
  if (!mathPlugin) throw new Error('webapp/static/js/md-math-plugin.js לא נמצא, או שאינו מגדיר window.MdMathPlugin');
  return new MarkdownIt(OPTIONS).use(markPlugin).use(mathPlugin, { katex });
}

// ---------------------------------------------------------------------------
// קריאת הנוסחאות מהפלט
// ---------------------------------------------------------------------------

function unescapeHtml(s) {
  return s.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'").replace(/&#39;/g, "'").replace(/&amp;/g, '&');
}

/** כל נוסחה שרונדרה: המקור כמו ש-KaTeX קיבל אותו, האם תצוגה, וכמה שורות טבלה (``mtr``) יש בה. */
function formulasIn(html) {
  const out = [];
  for (const m of html.matchAll(/<math\b([^>]*)>([\s\S]*?)<\/math>/g)) {
    const tex = /<annotation encoding="application\/x-tex">([\s\S]*?)<\/annotation>/.exec(m[2]);
    out.push({
      tex: tex ? unescapeHtml(tex[1]) : null,
      display: /display="block"/.test(m[1]),
      rows: (m[2].match(/<mtr>/g) || []).length,
    });
  }
  return out;
}

const OLD_DELIMITERS = [
  { left: '$$', right: '$$', display: true },
  { left: '$', right: '$', display: false },
];

/**
 * המסלול הישן: markdown-it בלי התוסף, ואחריו החיפוש של ``renderMathInElement`` על צמתי הטקסט.
 * ``code`` ו-``pre`` מוחלפים בתגית ריקה ולא נמחקים, כי בדפדפן הם מפרידים בין צמתי הטקסט שמשני
 * צדיהם (``ignoredTags`` של auto-render). כל נוסחה שנמצאה עוברת ב-KaTeX, כמו שם.
 *
 * ``console.warn`` מושתק בזמן הרינדור כאן בלבד: הנוסחאות המדומות של המסלול הישן הן טקסט עברי,
 * ו-KaTeX מזהיר על כל אות ("Unrecognized Unicode character", "No character metrics"). האזהרות הן
 * התסמין שהבקרה מדגימה, והן היו קוברות את הדוח שלה.
 */
function oldFormulas(src) {
  const html = new MarkdownIt(OPTIONS).use(markPlugin).render(src);
  const texts = html
    .replace(/<pre\b[\s\S]*?<\/pre>/g, '<x>')
    .replace(/<code\b[\s\S]*?<\/code>/g, '<x>')
    .split(/<[^>]*>/)
    .map(unescapeHtml);
  const out = [];
  const originalWarn = console.warn;
  console.warn = () => {};
  try {
    for (const text of texts) {
      for (const part of splitAtDelimiters(text, OLD_DELIMITERS)) {
        if (part.type !== 'math') continue;
        const rendered = katex.renderToString(part.data, { displayMode: part.display, throwOnError: false });
        out.push({ tex: part.data, display: part.display, rows: (rendered.match(/<mtr>/g) || []).length });
      }
    }
  } finally {
    console.warn = originalWarn;
  }
  return out;
}

// ---------------------------------------------------------------------------
// החוזה: קלט ← הנוסחאות שמגיעות ל-KaTeX. אותה רשימה בדיוק מורצת אחר כך על המסלול הישן.
// ---------------------------------------------------------------------------

const MATRIX = [
  '$$',
  '\\begin{bmatrix}',
  '1 & 2 \\\\',
  '3 & 4 \\\\',
  '5 & 6',
  '\\end{bmatrix}',
  '$$',
].join('\n');

/** המשפט עם האופרטורים מ-``sticky_notes_extending.md`` ב-Ck, תו בתו (שורה 869 בגרסה 1 של הקובץ). */
const REAL_MONGO_SENTENCE = '**חיתוך התצוגה המקדימה הוא \\`\\`$substrCP\\`\\`, ולעולם לא \\`\\`$substrBytes\\`\\`.** ' +
  'אות עברית היא שני בייטים, ואינדקס שנספר בתווים שנכנס לאופרטור שמודד בבייטים נוחת באמצע תו ומפיל את ' +
  'השאילתה (`Location28657`). זה בדיוק האירוע שקרה בחיפוש הקוד בריפו הזה: השגיאה נבלעה ב-`try`, מסלול ' +
  'חלופי יקר רץ במקומה, והמשתמש קיבל ”לא נמצאו תוצאות“ על חיפוש שמעולם לא רץ.';

/** סעיף הנוסחאות של ``CodeKeeper_Markdown.md`` ב-Ck, תו בתו — המסמך שבו המטריצה הוצגה ככותרת ענקית. */
const REAL_MATH_SECTION = [
  '### נוסחאות Inline',
  'הנוסחה המפורסמת של איינשטיין: $E = mc^2$',
  '',
  'משוואה ריבועית: $x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}$',
  '',
  '### נוסחאות Display',
  '',
  '$$',
  '\\int_{-\\infty}^{\\infty} e^{-x^2} dx = \\sqrt{\\pi}',
  '$$',
  '',
  '$$',
  '\\sum_{n=1}^{\\infty} \\frac{1}{n^2} = \\frac{\\pi^2}{6}',
  '$$',
  '',
  '### מטריצה',
  '',
  '$$',
  '\\begin{bmatrix}',
  'a_{11} & a_{12} & a_{13} \\\\',
  'a_{21} & a_{22} & a_{23} \\\\',
  'a_{31} & a_{32} & a_{33}',
  '\\end{bmatrix}',
  '\\times',
  '\\begin{bmatrix}',
  'x_1 \\\\ x_2 \\\\ x_3',
  '\\end{bmatrix}',
  '=',
  '\\begin{bmatrix}',
  'b_1 \\\\ b_2 \\\\ b_3',
  '\\end{bmatrix}',
  '$$',
  '',
  '---',
].join('\n');

const inline = (tex) => ({ tex, display: false, rows: 0 });
const display = (tex, rows = 0) => ({ tex, display: true, rows });

/** מקרים שהמסלול הישן הציג לא נכון — נוסחה שלא הייתה, או נוסחה שהושחתה או נעלמה. */
const BROKEN_BEFORE = [
  ['מחירים בטקסט רגיל', 'עולה $5 ובפרימיום $10', []],
  ['שני אופרטורים של מונגו באותה פסקה', 'האופרטורים $substrCP ו-$substrBytes חותכים טקסט', []],
  ['המשפט האמיתי מ-sticky_notes_extending.md', REAL_MONGO_SENTENCE, []],
  ['$$ROOT ו-$$CURRENT של מונגו', 'משתמשים ב-$$ROOT או ב-$$CURRENT בתוך $group', []],
  ['אופרטור ואחריו $$ROOT — ה-$ הראשון של $$ אינו סוגר', 'השתמשו ב-$substrBytes ולא ב-$$ROOT', []],
  ['מחיר בשני הסגנונות באותה פסקה — עברית חשופה אינה נוסחה', 'עולה $10, ולפעמים 5$.', []],
  // כל כלל לבד, בלי עברית בין שני ה-$ — אחרת הכלל של העברית תופס לפניו, והמקרה לא בודק אותו
  ['אות אחרי ה-$ הסוגר — $HOME:$PATH', 'use $HOME:$PATH here', []],
  ['ספרה לפני ה-$ הפותח — מחיר שהדולר אחריו', 'costs 5$, or 10$.', []],
  ['$ ואחריו $ אינו סוגר — $$ROOT', 'divide $total/$$ROOT.count', []],
  ['רווח לפני ה-$ הסוגר', 'x $a $ y', []],
  ['סימן דולר עם escape', 'המחיר הוא \\$5 ולא \\$10', []],
  ['מטריצה בבלוק $$ — שלוש שורות', MATRIX,
    [display('\n\\begin{bmatrix}\n1 & 2 \\\\\n3 & 4 \\\\\n5 & 6\n\\end{bmatrix}\n', 3)]],
  ['מטריצה בשורה אחת — \\\\ מגיע ל-KaTeX', '$$\\begin{bmatrix} a & b \\\\ c & d \\\\ e & f \\end{bmatrix}$$',
    [display('\\begin{bmatrix} a & b \\\\ c & d \\\\ e & f \\end{bmatrix}', 3)]],
  ['כוכביות בתוך נוסחה, עם הדגשה ומארקר באותה פסקה', '**מודגש** ו-==מארקר== ו-$a*b*c$',
    [inline('a*b*c')]],
  ['גרש בודד בנוסחה נשאר גרש (טיפוגרפיה)', "הנגזרת $f'(x)$ כאן", [inline("f'(x)")]],
  ['סעיף הנוסחאות של CodeKeeper_Markdown.md', REAL_MATH_SECTION, [
    inline('E = mc^2'),
    inline('x = \\frac{-b \\pm \\sqrt{b^2 - 4ac}}{2a}'),
    display('\n\\int_{-\\infty}^{\\infty} e^{-x^2} dx = \\sqrt{\\pi}\n'),
    display('\n\\sum_{n=1}^{\\infty} \\frac{1}{n^2} = \\frac{\\pi^2}{6}\n'),
    display('\n\\begin{bmatrix}\na_{11} & a_{12} & a_{13} \\\\\na_{21} & a_{22} & a_{23} \\\\\n' +
      'a_{31} & a_{32} & a_{33}\n\\end{bmatrix}\n\\times\n\\begin{bmatrix}\nx_1 \\\\ x_2 \\\\ x_3\n' +
      '\\end{bmatrix}\n=\n\\begin{bmatrix}\nb_1 \\\\ b_2 \\\\ b_3\n\\end{bmatrix}\n', 9),
  ]],
];

/** מקרים שעבדו כבר קודם — כאן כדי לוודא שהמעבר לא שינה כלום. */
const WORKED_BEFORE = [
  ['נוסחה בתוך שורה', '$x^2$', [inline('x^2')]],
  ['עברית בתוך \\text היא נוסחה', 'מהירות: $v = \\frac{\\text{מרחק}}{\\text{זמן}}$',
    [inline('v = \\frac{\\text{מרחק}}{\\text{זמן}}')]],
  ['דולר בתוך קוד נשאר טקסט', 'מחיר `$x$` וגם:\n\n```\n$y$\n```', []],
  ['נוסחת תצוגה בתוך פסקה', 'טקסט $$x+1$$ ועוד טקסט', [display('x+1')]],
  ['$$ שלא נסגר אינו בולע את המשך המסמך', '$$ הוא מספר התהליך\n\nפסקה אחרת עם $x$', [inline('x')]],
  ['שורה ריקה בתוך $$ — אין נוסחה', '$$\na\n\nb\n$$', []],
];

const ALL = [...BROKEN_BEFORE, ...WORKED_BEFORE];

console.log('\nנוסחאות — התנהגות מול markdown-it 14.1.0 ו-KaTeX 0.16.25:');

check('הקובץ מייצא את window.MdMathPlugin', () => {
  if (typeof mathPlugin !== 'function') {
    throw new Error('window.MdMathPlugin אינו פונקציה — אתרי הקריאה עושים md.use עליו');
  }
});

check('שני אתרי הקריאה בונים את markdown-it עם אותן אפשרויות', () => {
  eq(LIVE_OPTIONS, OPTIONS, 'live-preview.js מול md_preview.html');
});

for (const [name, src, expected] of ALL) {
  check(name, () => eq(formulasIn(newMd().render(src)), expected, `קלט: ${JSON.stringify(src)}`));
}

// ---------------------------------------------------------------------------
// מה שסביב הנוסחה: הטקסט, הקוד והעיצוב נשארים כמו שהם.
// ---------------------------------------------------------------------------

const EXACT = [
  ['מחירים — הטקסט כמו שהוא', 'עולה $5 ובפרימיום $10', '<p>עולה $5 ובפרימיום $10</p>'],
  ['escape — סימן דולר רגיל', 'המחיר הוא \\$5 ולא \\$10', '<p>המחיר הוא $5 ולא $10</p>'],
  ['קוד שמתחיל אחרי $ פותח אינו נבלע', 'עולה $5, ראה `$PRICE` ו-`a$` כאן',
    '<p>עולה $5, ראה <code>$PRICE</code> ו-<code>a$</code> כאן</p>'],
  // בלי עברית ובלי אות אחרי ה-$ שבתוך הקוד — רק הגרש ההפוך עוצר כאן את הנוסחה
  ['קוד אחרי $ פותח, כשרק הגרש עוצר', 'x $a `b$` c', '<p>x $a <code>b$</code> c</p>'],
  ['$$ROOT ו-$$CURRENT — הטקסט כמו שהוא', 'משתמשים ב-$$ROOT או ב-$$CURRENT',
    '<p>משתמשים ב-$$ROOT או ב-$$CURRENT</p>'],
];

for (const [name, src, expected] of EXACT) {
  check(name, () => eq(newMd().render(src).trim(), expected, `קלט: ${JSON.stringify(src)}`));
}

check('הדגשה, מארקר ונוסחה באותה פסקה — שלושתם בפלט', () => {
  const html = newMd().render('**מודגש** ו-==מארקר== ו-$a*b*c$');
  for (const part of ['<strong>מודגש</strong>', '<mark>מארקר</mark>', '<span class="md-math" dir="ltr">']) {
    if (!html.includes(part)) throw new Error(`חסר בפלט: ${part}\n      ${html}`);
  }
});

check('כל נוסחה עטופה ב-dir="ltr" — בעמוד עברי היא הוצגה מימין לשמאל', () => {
  const html = newMd().render(REAL_MATH_SECTION);
  const wrappers = html.match(/class="md-math"[^>]*>/g) || [];
  eq(wrappers.length, 5, 'מספר העטיפות');
  for (const w of wrappers) {
    if (!/\bdir="ltr"/.test(w)) throw new Error(`עטיפה בלי dir="ltr": ${w}`);
  }
});

check('המטריצה של CodeKeeper_Markdown.md אינה הופכת לכותרת', () => {
  const html = newMd().render(REAL_MATH_SECTION);
  // כל כותרת, גם כזו שיש בה תגיות: הכותרת השבורה הייתה ``<h1>`` עם ``<br>`` בתוכה
  const headings = [...html.matchAll(/<h([1-6])\b[^>]*>([\s\S]*?)<\/h\1>/g)].map((m) => `h${m[1]}: ${m[2]}`);
  eq(headings, ['h3: נוסחאות Inline', 'h3: נוסחאות Display', 'h3: מטריצה'], 'הכותרות');
  if (!/<hr>/.test(html)) throw new Error('ה---- שאחרי המטריצה לא הפך לקו מפריד');
});

check('בלוק $$ בתוך ציטוט — בלי סימני >, וברשימה', () => {
  eq(formulasIn(newMd().render('> $$\n> x^2\n> $$')), [display('\nx^2\n')], 'ציטוט');
  const list = newMd().render('- פריט\n\n  $$\n  y\n  $$');
  eq(formulasIn(list), [display('\ny\n')], 'רשימה');
  if (!/<li>[\s\S]*class="md-math"[\s\S]*<\/li>/.test(list)) throw new Error(`הבלוק יצא מהרשימה: ${list}`);
});

check('בלוק $$ קוטע פסקה, ושורה שמתחילה ב-$$ ואינה נוסחה לא קוטעת', () => {
  const html = newMd().render('לפני\n$$\nx\n$$\nאחרי');
  eq(formulasIn(html), [display('\nx\n')], 'הנוסחה');
  if (!/<p>לפני<\/p>/.test(html) || !/<p>אחרי<\/p>/.test(html)) throw new Error(`הפסקאות: ${html}`);
  eq(newMd().render('שורה\n$$ROOT הוא משתנה').trim(), '<p>שורה<br>\n$$ROOT הוא משתנה</p>', 'פסקה אחת');
});

check('הבלוק נושא map — מיפוי המקור של md_preview.html מצמיד ממנו data-source-line', () => {
  const tokens = newMd().parse('טקסט\n\n$$\nx\n$$\n', {});
  const block = tokens.find((t) => t.type === 'math_block');
  if (!block) throw new Error('אין טוקן math_block');
  eq(block.map, [2, 5], 'map');
  const md = newMd();
  const original = md.renderer.rules.math_block;
  md.renderer.rules.math_block = (toks, idx, options, env, self) => {
    toks[idx].attrSet('data-source-line', String(toks[idx].map[0]));
    return original(toks, idx, options, env, self);
  };
  if (!/<div class="md-math" dir="ltr" data-source-line="2">/.test(md.render('טקסט\n\n$$\nx\n$$\n'))) {
    throw new Error('המאפיין שהוצמד לטוקן לא הגיע לפלט');
  }
});

check('שגיאת TeX מוצגת כשגיאה של KaTeX, ולא מפילה את הרינדור', () => {
  const html = newMd().render('לפני $\\frac{a$ אחרי');
  if (!/class="katex-error"/.test(html)) throw new Error(`אין katex-error: ${html}`);
  if (!/אחרי/.test(html)) throw new Error('הטקסט שאחרי הנוסחה נעלם');
});

check('חריגה שאינה ParseError (קינון עמוק) — מצב משלה לנוסחה, והמסמך ממשיך', () => {
  const deep = '{'.repeat(5000) + 'x' + '}'.repeat(5000);
  // ודא שזו באמת חריגה שאינה ParseError, אחרת המקרה לא בודק את מה שהוא אומר שהוא בודק
  let thrown = null;
  try { katex.renderToString(deep, { throwOnError: false }); } catch (e) { thrown = e; }
  if (!thrown || thrown instanceof katex.ParseError) throw new Error('KaTeX לא זרק כאן חריגה שאינה ParseError');
  const errors = [];
  const originalError = console.error;
  console.error = (...args) => { errors.push(args); };
  let html;
  try { html = newMd().render(`לפני $${deep}$\n\nפסקה שאחרי $y$`); }
  finally { console.error = originalError; }
  if (!/class="md-math-error" title="RangeError/.test(html)) throw new Error('אין md-math-error עם הודעת החריגה');
  eq(formulasIn(html), [inline('y')], 'הנוסחה שאחרי');
  eq(errors.length, 1, 'console.error');
  if (!(errors[0][1] instanceof RangeError)) throw new Error('החריגה לא נרשמה במלואה');
});

check('\\gdef משותף לנוסחאות של אותו מסמך, ולא בין מסמכים', () => {
  const md = newMd();
  const same = md.render('$\\gdef\\myvec{\\mathbf{v}}$ ואז $\\myvec$');
  if (/mathcolor="#cc0000"/.test(same)) throw new Error('\\myvec לא הוגדר בנוסחה השנייה');
  const other = md.render('$\\myvec$');
  if (!/mathcolor="#cc0000"/.test(other)) throw new Error('ההגדרה דלפה למסמך אחר');
});

check('${toc} של תוכן העניינים אינו נוסחה', () => {
  const html = new MarkdownIt(OPTIONS).use(markPlugin).use(mathPlugin, { katex })
    .use(markdownItTocDoneRight).render('${toc}\n\n# כותרת');
  if (!/<nav class="table-of-contents">/.test(html)) throw new Error(`אין תוכן עניינים: ${html}`);
  eq(formulasIn(html), [], 'נוסחאות');
});

/**
 * ``markdown-it-anchor`` (``getTokensText``) ו-``markdown-it-toc-done-right`` (``generateTocAst``) לוקחים
 * מהכותרת רק טוקנים של טקסט ושל קוד, ולכן שניהם משמיטים את הנוסחה באותה צורה. זה מה שמחזיק את
 * הקישור מתוכן העניינים לכותרת, ו-``markdown_style_guide.rst`` נשען על זה. אותו ``slugify`` לשניהם,
 * כמו בשני אתרי הקריאה.
 */
check('כותרת עם נוסחה — הקישור מתוכן העניינים מגיע לעוגן שלה', () => {
  const slugify = (s) => encodeURIComponent(String(s).trim().toLowerCase().replace(/\s+/g, '-'));
  const html = new MarkdownIt(OPTIONS).use(markPlugin).use(mathPlugin, { katex })
    .use(markdownItAnchor, { slugify }).use(markdownItTocDoneRight, { slugify })
    .render('[[toc]]\n\n## משפט $a^2+b^2=c^2$ הידוע');
  const id = /<h2 id="([^"]+)"/.exec(html);
  const href = /<nav class="table-of-contents"><ol><li><a href="#([^"]+)">([^<]*)<\/a>/.exec(html);
  if (!id || !href) throw new Error(`חסרים עוגן או קישור: ${html}`);
  eq(href[1], id[1], 'הקישור מול העוגן');
  eq(href[2], 'משפט  הידוע', 'הטקסט בתוכן העניינים');
  eq(formulasIn(html), [inline('a^2+b^2=c^2')], 'הנוסחה בכותרת');
});

// ---------------------------------------------------------------------------
// המנגנון ואתרי הקריאה
// ---------------------------------------------------------------------------

check('אין פרסור מקונן — inline.parse הפיל את כל התצוגה בתוסף המארקר', () => {
  const codeOnly = read(MATH_PATH).split('\n').filter((l) => !/^\s*(\*|\/\*|\/\/)/.test(l)).join('\n');
  if (/inline\s*\.\s*parse\s*\(/.test(codeOnly)) {
    throw new Error('קריאה ל-inline.parse מתוך התוסף. ראו את ההסבר בראש md-mark-plugin.js.');
  }
});

check('שני אתרי הקריאה רושמים את התוסף עם KaTeX, ואינם מריצים renderMathInElement', () => {
  for (const file of [MD_PREVIEW, LIVE_PREVIEW]) {
    const src = read(file);
    if (!/md\.use\(window\.MdMathPlugin,\s*\{\s*katex:\s*window\.katex\s*\}\)/.test(src)) {
      throw new Error(`${path.basename(file)} אינו עושה md.use(window.MdMathPlugin, { katex: window.katex })`);
    }
    if (/renderMathInElement\s*\(/.test(src)) {
      throw new Error(`${path.basename(file)} עדיין מריץ את renderMathInElement על ה-HTML`);
    }
  }
});

check('כל תבנית שטוענת את md-mark-plugin.js טוענת גם את md-math-plugin.js, לפני live-preview.js', () => {
  const templates = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.name.endsWith('.html')) templates.push(full);
    }
  };
  walk(path.join(ROOT, 'webapp', 'templates'));
  const missing = [];
  for (const file of templates) {
    const src = read(file);
    const mark = src.search(/<script[^>]*js\/md-mark-plugin\.js/);
    if (mark < 0) continue;
    const math = src.search(/<script[^>]*js\/md-math-plugin\.js'\) \}\}\?v=\{\{ static_version \}\}/);
    const live = src.search(/<script[^>]*js\/live-preview\.js/);
    if (math < 0 || (live >= 0 && math > live)) missing.push(path.relative(ROOT, file));
  }
  if (missing.length) throw new Error('חסר, בלי ?v={{ static_version }}, או אחרי live-preview.js: ' + missing.join(', '));
});

check('הבאנדל שבריפו חושף את window.katex — אחרת אין לתוסף במה לרנדר', () => {
  const entry = read(path.join(ROOT, 'webapp', 'static_build', 'md-preview-entry.js'));
  if (!/window\.katex\s*=\s*katex/.test(entry)) throw new Error('md-preview-entry.js אינו מגדיר window.katex');
  const bundle = read(path.join(JS_DIR, 'md_preview.bundle.js'));
  if (!/window\.katex\s*=/.test(bundle)) {
    throw new Error('md_preview.bundle.js לא נבנה מחדש: npm run build-md');
  }
});

// ---------------------------------------------------------------------------
// בקרה: אותן טענות בדיוק, על המסלול הישן. בדיקה שאינה נופלת שם אינה בודקת כלום.
// ---------------------------------------------------------------------------

console.log('\nבקרה — אותם מקרים במסלול הישן (renderMathInElement על ה-HTML):');

const unexpectedlyPassed = [];
for (const [name, src, expected] of BROKEN_BEFORE) {
  const old = oldFormulas(src);
  if (JSON.stringify(old) === JSON.stringify(expected)) unexpectedlyPassed.push(name);
  else console.log(`     ${name}: ${JSON.stringify(old)}`);
}

check(`כל ${BROKEN_BEFORE.length} המקרים השבורים נכשלים במסלול הישן`, () => {
  if (unexpectedlyPassed.length) {
    throw new Error('המקרים האלה עברו גם במסלול הישן, כלומר הם לא מעידים על התיקון: ' +
      unexpectedlyPassed.join(', '));
  }
});

check(`כל ${WORKED_BEFORE.length} המקרים שעבדו קודם נותנים במסלול הישן את אותן נוסחאות`, () => {
  const changed = [];
  for (const [name, src, expected] of WORKED_BEFORE) {
    const old = oldFormulas(src);
    if (JSON.stringify(old) !== JSON.stringify(expected)) changed.push(`${name} (ישן: ${JSON.stringify(old)})`);
  }
  if (changed.length) {
    throw new Error('המעבר שינה התנהגות שעבדה קודם:\n      ' + changed.join('\n      '));
  }
});

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
