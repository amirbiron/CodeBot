'use strict';
// שומר טקסטואלי על גובה עמודת העורך ב-Split View (עמודי העלאה ועריכת קובץ).
//
// **הבאג שהטסט הזה שומר מפניו:** גובה העורך נקבע בעבר בשני מקומות
// נפרדים, כל אחד לפי נוסחה אחרת של גובה החלון —
// ``.cm-editor { min-height: 400px; max-height: 60vh }`` ב-
// ``codemirror-custom.css`` מול ``.split-panels { max-height: calc(100vh - 200px) }``
// ב-``split-view.css``. אף אחד מהם לא הכיר את מה שיושב ביניהם בתוך
// ``#editorContainer``: התווית "קוד" ופס החלפת העורך (יחד כ-106px)
// וה-padding-bottom של הפאנל. מתחת לגובה חלון של כ-800px הסכום חרג
// מהתקרה, ו-``.split-view { overflow: hidden }`` בלע את העודף בשקט —
// השורות האחרונות של הקובץ נשארו מתחת לקצה התחתון ולא היו נגישות
// בשום גלילה, לא של העמוד ולא של העורך.
//
// נמדד בדפדפן (Chromium, /upload, מסמך של 200 שורות), לפני התיקון:
// חלון בגובה 600px הסתיר 5.4 שורות, 680px הסתיר 2.19 שורות,
// 768px הסתיר 0.62 שורה, ומ-840px ומעלה לא הסתיר כלום.
// אחרי התיקון: 0 בכל הגבהים שנבדקו, גם עם Live Preview דלוק.
//
// למה טסט טקסטואלי ולא מדידה: Playwright אינו בתלויות הפרויקט, אז
// הארנס שמרים שרת ודפדפן לא ירוץ ב-CI. הטסט הזה **לא מודד מחדש** —
// הוא שומר על ההחלטה של המדידה: שהתקרה הכפולה לא תחזור, ושהעורך
// יישאר מסוגל להתכווץ בתוך ה-Split View במקום לגלוש ממנו.
//
// **ובאג שני, הפוך (אוקטובר 2026):** כש-Live Preview דלוק, הגובה של
// ``.split-panels`` היה תקרה (``max-height``) ולא גובה, כלומר נקבע לפי אורך
// התוכן. מסמך ריק — אחרי "ניקוי", או מחיקה של כל הטקסט — כיווץ את שני
// הפאנלים ל-280px, והעורך ירד ל-89px (נמדד בעמוד העריכה, חלון 1100x760).
// מאז הגובה כשהתצוגה דלוקה הוא ``height``, וזה הכלל היחיד שקובע את גובה
// ``.split-panels``. ההתכווצות עצמה נבדקת בדפדפן
// (``test_an_empty_document_keeps_the_panels_full_height`` ב-
// ``tests/test_markdown_editor_browser.py`` וב-``tests/test_edit_page_frame_browser.py``).
//
// לכל טענה כאן יש מוטציה מובנית: הטסט מוודא שהוא מסוגל ליפול, על ידי
// הרצת אותה בדיקה בדיוק על גרסת CSS שהתיקון הוסר ממנה.

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CSS_PATH = path.join(__dirname, '..', 'webapp', 'static', 'css', 'split-view.css');
const CSS = fs.readFileSync(CSS_PATH, 'utf8');

let passed = 0, failed = 0;
function check(name, fn) {
  try { fn(); passed++; console.log(`  ✓ ${name}`); }
  catch (e) { failed++; console.error(`  ✗ ${name}\n    ${e.message}`); }
}
function ok(cond, msg) { if (!cond) throw new Error(msg); }

// ---------------------------------------------------------------------------
// הטענות עצמן, ככלים שאפשר להריץ על כל טקסט CSS — כדי שהמוטציות למטה
// יריצו *בדיוק* את אותה בדיקה על גרסה שהתיקון הוסר ממנה.
// ---------------------------------------------------------------------------

/** הקפאת ה-block של media query לפי סוגריים מאוזנים, לא לפי regex תמים. */
function extractBlock(css, startIndex) {
  const open = css.indexOf('{', startIndex);
  if (open === -1) return '';
  let depth = 0;
  for (let i = open; i < css.length; i++) {
    if (css[i] === '{') depth++;
    else if (css[i] === '}') { depth--; if (depth === 0) return css.slice(open + 1, i); }
  }
  return '';
}

/** 1. כש-Live Preview כבוי אין תקרה על ‎.split-panels‎ — אין מה לבלוע. כלל שקובע את הגובה שלו קיים רק
 *  עם ``.is-active`` בבורר. */
function assertNoCapWhenPreviewOff(css) {
  const offenders = parseRules(css).filter(
    (r) => r.selectors.some((s) => s.endsWith('.split-panels') && !s.includes('.is-active'))
      && /(?:^|[;\s])(?:max-)?height\s*:\s*(?!none\b)/.test(r.body),
  );
  ok(offenders.length === 0,
    'יש כלל שקובע גובה ל-.split-panels גם כשה-Preview כבוי: ' +
    offenders.map((r) => r.selectors.join(', ')).join(' | '));
}

/**
 * פירוק בלוק CSS שטוח לרשימת כללים {selectors[], body}.
 * נדרש כי regex תמים כמו ``\.codemirror-container\s*\{`` מפספס כלל שבו
 * ה-selector הזה הוא אחד מכמה ברשימה מופרדת בפסיקים — וזה בדיוק המקרה כאן.
 */
function parseRules(block) {
  const rules = [];
  const re = /([^{}]+)\{([^}]*)\}/g;
  // הערות לפני הפירוק: הערה שמצטטת כלל (``.split-panels { max-height: ... }``) הייתה נקראת ככלל
  const css = block.replace(/\/\*[\s\S]*?\*\//g, '');
  let m;
  while ((m = re.exec(css)) !== null) {
    rules.push({
      selectors: m[1].split(',').map((s) => s.trim()).filter(Boolean),
      body: m[2],
    });
  }
  return rules;
}

/**
 * האם קיים כלל שה-**נושא** שלו (ה-compound האחרון ב-selector) הוא ``needle``
 * וגוף הכלל מצהיר על ``decl``?
 *
 * דווקא הנושא ולא "מכיל": ``#editorContainer`` מופיע גם כאב בכללים של
 * ``> .codemirror-container``, ובדיקה לפי הכלה הייתה עוברת גם כשההצהרה
 * הנדרשת יושבת על הילד ולא על האב — כלומר בודקת כלום.
 */
function ruleDeclares(rules, needle, decl) {
  return rules.some(
    (r) => r.selectors.some((s) => s.endsWith(needle)) && decl.test(r.body),
  );
}

/** 2. כש-Live Preview דלוק התקרה נחוצה — ואז העורך חייב להיות מסוגל להתכווץ. */
function assertEditorCanShrinkWhenPreviewOn(css) {
  const mqIdx = css.indexOf('@media (min-width: 768px)');
  ok(mqIdx !== -1,
    'אין @media (min-width: 768px) — שרשרת ה-flex שמאפשרת לעורך להתכווץ נעלמה');
  const rules = parseRules(extractBlock(css, mqIdx));
  ok(rules.length > 0, 'ה-media query ריק');

  ok(ruleDeclares(rules, '#editorContainer', /min-height\s*:\s*0/),
    'ל-#editorContainer אין min-height: 0 — כ-flex item הוא לא יתכווץ, והתוכן יגלוש מהפאנל');
  ok(ruleDeclares(rules, '#editorContainer', /display\s*:\s*flex/),
    'ל-#editorContainer אין display: flex — הוא לא יחלק את הגובה בין הפס לעורך');
  ok(ruleDeclares(rules, '.codemirror-container', /min-height\s*:\s*0/),
    'ל-.codemirror-container אין min-height: 0 — הוא לא יתכווץ ויגלוש');
  ok(ruleDeclares(rules, '.cm-editor', /max-height\s*:\s*none/),
    'ל-.cm-editor לא בוטל ה-max-height — התקרה של 60vh חוזרת ומתנגשת בתקרה של הפאנל');
  ok(ruleDeclares(rules, '.cm-editor', /min-height\s*:\s*0/),
    'ל-.cm-editor אין min-height: 0 — ה-400px הקבועים ימשיכו לגלוש כשאין מספיק מקום');
}

/** 3. שרשרת ה-flex חייבת להישאר מגודרת ל-768px ומעלה. */
function assertShrinkChainIsDesktopOnly(css) {
  const mqIdx = css.indexOf('@media (min-width: 768px)');
  ok(mqIdx !== -1, 'אין @media (min-width: 768px)');
  const block = extractBlock(css, mqIdx);
  ok(ruleDeclares(parseRules(block), '.cm-editor', /flex\s*:\s*1/),
    'ה-flex: 1 על .cm-editor לא נמצא בתוך ה-media query. מתחת ל-768px ל-.split-panels‎ ' +
    'ממילא אין תקרה, ואז flex: 1 היה נותן לעורך לגדול בלי גבול לפי אורך הקובץ.');
  const outside = css.slice(0, mqIdx) + css.slice(mqIdx + block.length);
  ok(!ruleDeclares(parseRules(outside), '.cm-editor', /flex\s*:\s*1/),
    'יש flex: 1 על .cm-editor גם מחוץ ל-media query — הוא יחול גם במובייל');
}

/** 4. כש-Live Preview דלוק לפאנלים יש **גובה**, לא תקרה — אחרת מסמך ריק מכווץ אותם. */
function assertDefiniteHeightWhenPreviewOn(css) {
  const mqIdx = css.indexOf('@media (min-width: 768px)');
  ok(mqIdx !== -1, 'אין @media (min-width: 768px)');
  const rules = parseRules(extractBlock(css, mqIdx));
  ok(ruleDeclares(rules, '.split-view.is-active .split-panels', /(?:^|[;\s])height\s*:/),
    'ל-".split-view.is-active .split-panels" אין height — הגובה שוב נקבע לפי התוכן, ומסמך ריק מכווץ את הפאנלים');
}

const ASSERTIONS = [
  ['אין תקרת גובה על .split-panels כש-Live Preview כבוי', assertNoCapWhenPreviewOff],
  ['כש-Live Preview דלוק לפאנלים יש גובה קבוע, לא תקרה', assertDefiniteHeightWhenPreviewOn],
  ['העורך מסוגל להתכווץ בתוך הפאנל כש-Live Preview דלוק', assertEditorCanShrinkWhenPreviewOn],
  ['שרשרת ההתכווצות מגודרת ל-768px ומעלה בלבד', assertShrinkChainIsDesktopOnly],
];

console.log('split-view.css — גובה עמודת העורך:');
for (const [name, fn] of ASSERTIONS) check(name, () => fn(CSS));

// ---------------------------------------------------------------------------
// מוטציות: האם הבדיקות למעלה בכלל מסוגלות ליפול?
// כל מוטציה מאמתת קודם שההחלפה **באמת תפסה** (assert על מספר ההופעות
// ועל כך שהתוכן השתנה), ורק אז מריצה את הטענה ומצפה שהיא תיפול.
// ---------------------------------------------------------------------------

function mutate(css, find, replaceWith) {
  const count = css.split(find).length - 1;
  ok(count > 0, `המוטציה לא תפסה: "${find}" לא נמצא ב-CSS`);
  const out = css.split(find).join(replaceWith);
  ok(out !== css, 'המוטציה לא שינתה את התוכן');
  return out;
}

function expectFails(name, mutatedCss, fn) {
  let threw = false;
  try { fn(mutatedCss); } catch (_) { threw = true; }
  check(name, () => ok(threw, 'הבדיקה עברה על CSS פגום — כלומר היא לא בודקת כלום'));
}

console.log('מוטציות (הבדיקות חייבות ליפול על CSS פגום):');

expectFails(
  'החזרת התקרה ל-.split-panels (בלי .is-active) מפילה את בדיקת ה-Preview הכבוי',
  mutate(CSS, '.split-panels {\n  display: flex;\n  flex-direction: row;\n  min-height: 280px;\n}',
              '.split-panels {\n  display: flex;\n  flex-direction: row;\n  min-height: 280px;\n  max-height: calc(100vh - 200px);\n}'),
  assertNoCapWhenPreviewOff,
);

expectFails(
  'תקרה במקום גובה כשה-Preview דלוק מפילה את בדיקת הגובה הקבוע',
  mutate(CSS, '  .split-view.is-active .split-panels {\n    height: calc(100vh - 200px);',
              '  .split-view.is-active .split-panels {\n    max-height: calc(100vh - 200px);'),
  assertDefiniteHeightWhenPreviewOn,
);

expectFails(
  'הסרת min-height: 0 מ-#editorContainer מפילה את בדיקת ההתכווצות',
  mutate(CSS,
    '  .split-view.is-active .split-panel--editor > #editorContainer {\n' +
    '    display: flex;\n    flex-direction: column;\n    flex: 1 1 auto;\n    min-height: 0;\n  }',
    '  .split-view.is-active .split-panel--editor > #editorContainer {\n' +
    '    display: flex;\n    flex-direction: column;\n    flex: 1 1 auto;\n  }'),
  assertEditorCanShrinkWhenPreviewOn,
);

expectFails(
  'החזרת max-height ל-.cm-editor מפילה את בדיקת ההתכווצות',
  mutate(CSS, '    max-height: none;\n  }\n}', '    max-height: 60vh;\n  }\n}'),
  assertEditorCanShrinkWhenPreviewOn,
);

expectFails(
  'שינוי ה-media query ל-max-width מפיל את בדיקת הגידור',
  mutate(CSS, '@media (min-width: 768px) {', '@media (max-width: 767px) {'),
  assertShrinkChainIsDesktopOnly,
);

console.log(`${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
