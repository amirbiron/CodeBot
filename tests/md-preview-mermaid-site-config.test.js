/**
 * טסטים ל-webapp/static_build/mermaid-site-config.mjs — התצורה של Mermaid באתר (רוחב הגלישה של התוויות,
 * ``securityLevel``), ולשימוש בה.
 *
 * הרצה:  node tests/md-preview-mermaid-site-config.test.js
 * (קובץ עצמאי שמריץ את הבדיקות בעצמו ויוצא בקוד 1 בכישלון: ``.github/workflows/ci.yml`` מריץ את
 *  ``tests/*.test.js`` בלולאה עם ``node "$f"``.)
 *
 * **מה נשמר כאן.** ``mermaid.initialize`` מחליף את כל התצורה בכל קריאה, ולכן כל מקום שמצייר תרשים מהבאנדל חייב
 * להעביר את התצורה של האתר — ואם אחד מהם יכתוב אותה בעצמו, הוא ייסחף מהשני בשקט (ההסבר בראש
 * ``mermaid-site-config.mjs``). הבדיקות כאן רצות ב-CI; התוויות עצמן נמדדות בדפדפן ב-
 * ``tests/test_mermaid_label_wrap_browser.py``, שאינו רץ ב-CI כי שם אין Chromium.
 *
 * **מה נבדק:**
 * - ``mermaidSiteConfig``: ``securityLevel: 'strict'``, ‏``startOnLoad: false``, הערכה שהועברה, ו-
 *   ``flowchart.wrappingWidth`` = ``MERMAID_WRAPPING_WIDTH``; ואובייקט חדש בכל קריאה.
 * - הבאנדל שבריפו נבנה עם התצורה, באותו רוחב (נבנה ביד ב-``npm run build-md`` ונשמר בגיט).
 * - שני המקומות שמציירים מהבאנדל — ``md_preview.html`` ו-``live-preview.js`` — מאתחלים רק דרך
 *   ``window.mermaidSiteConfig``, ואינם כותבים תצורה משלהם. מצב הקריאה (``reader_mode.html``) מחוץ לבדיקה: הוא
 *   טוען Mermaid מ-CDN, ולא את הבאנדל.
 */
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import { MERMAID_WRAPPING_WIDTH, mermaidSiteConfig } from '../webapp/static_build/mermaid-site-config.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(__dirname, '..');
const read = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');

/** המקומות שמציירים תרשימים מהבאנדל. מקום חדש שמאתחל את Mermaid מהבאנדל נכנס לכאן. */
const CALL_SITES = ['webapp/templates/md_preview.html', 'webapp/static/js/live-preview.js'];

let passed = 0;
let failed = 0;

function check(name, fn) {
  try {
    fn();
    passed += 1;
    console.log(`  ✓ ${name}`);
  } catch (err) {
    failed += 1;
    console.log(`  ✗ ${name}\n      ${err && err.message ? err.message : err}`);
  }
}

function assertEqual(actual, expected, what) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`${what}: ${JSON.stringify(actual)} במקום ${JSON.stringify(expected)}`);
  }
}

console.log('mermaid-site-config:');

check('התצורה: strict, בלי startOnLoad, הערכה שהועברה, ורוחב הגלישה של האתר', () => {
  assertEqual(mermaidSiteConfig('dark'), {
    startOnLoad: false,
    securityLevel: 'strict',
    theme: 'dark',
    flowchart: { wrappingWidth: MERMAID_WRAPPING_WIDTH },
  }, 'mermaidSiteConfig("dark")');
  assertEqual(mermaidSiteConfig('default').theme, 'default', 'הערכה');
});

check('רוחב הגלישה של האתר רחב מברירת המחדל של Mermaid', () => {
  // ברירת המחדל של Mermaid — ``flowchart.wrappingWidth`` ב-``defaultConfig`` של mermaid@11.12.0 שבריפו.
  const chunkDir = path.join(ROOT, 'node_modules', 'mermaid', 'dist', 'chunks', 'mermaid.core');
  const defaults = fs.readdirSync(chunkDir)
    .filter((name) => name.endsWith('.mjs'))
    .map((name) => fs.readFileSync(path.join(chunkDir, name), 'utf8').match(/"wrappingWidth": (\d+),/))
    .filter(Boolean)
    .map((m) => Number(m[1]));
  if (defaults.length !== 1) throw new Error(`נמצאו ${defaults.length} ברירות מחדל של wrappingWidth ב-Mermaid`);
  if (!(MERMAID_WRAPPING_WIDTH > defaults[0])) {
    throw new Error(`MERMAID_WRAPPING_WIDTH (${MERMAID_WRAPPING_WIDTH}) אינו רחב מברירת המחדל (${defaults[0]})`);
  }
});

check('אובייקט חדש בכל קריאה — שינוי של קורא אחד לא מגיע לבא אחריו', () => {
  const first = mermaidSiteConfig('dark');
  first.flowchart.wrappingWidth = 1;
  first.securityLevel = 'loose';
  assertEqual(mermaidSiteConfig('dark').flowchart.wrappingWidth, MERMAID_WRAPPING_WIDTH, 'הקריאה השנייה');
  assertEqual(mermaidSiteConfig('dark').securityLevel, 'strict', 'הקריאה השנייה');
});

check('הבאנדל שבריפו חושף את window.mermaidSiteConfig, באותו רוחב', () => {
  const entry = read('webapp/static_build/md-preview-entry.js');
  if (!/window\.mermaidSiteConfig\s*=\s*mermaidSiteConfig\b/.test(entry)) {
    throw new Error('md-preview-entry.js אינו חושף את window.mermaidSiteConfig');
  }
  const bundle = read('webapp/static/js/md_preview.bundle.js');
  if (!/window\.mermaidSiteConfig\s*=\s*mermaidSiteConfig\d*;/.test(bundle)) {
    throw new Error('md_preview.bundle.js לא נבנה מחדש: npm run build-md');
  }
  const width = bundle.match(/var MERMAID_WRAPPING_WIDTH\d* = (\d+);/);
  if (!width) throw new Error('אין MERMAID_WRAPPING_WIDTH בבאנדל: npm run build-md');
  if (Number(width[1]) !== MERMAID_WRAPPING_WIDTH) {
    throw new Error(`בבאנדל ${width[1]}, במודול ${MERMAID_WRAPPING_WIDTH}: npm run build-md`);
  }
});

for (const rel of CALL_SITES) {
  check(`${path.basename(rel)} מאתחל את Mermaid רק דרך window.mermaidSiteConfig`, () => {
    const src = read(rel);
    const calls = src.match(/mermaid\.initialize\(([^;]*)\);/g) || [];
    if (calls.length === 0) throw new Error('אין קריאה ל-mermaid.initialize');
    const other = calls.filter((c) => !/^mermaid\.initialize\(window\.mermaidSiteConfig\(\w+\)\);$/.test(c));
    if (other.length) throw new Error(`אתחול שאינו דרך התצורה של האתר: ${other.join(' | ')}`);
    if (/securityLevel\s*:/.test(src)) throw new Error('securityLevel כתוב כאן — הוא חלק מהתצורה של האתר');
  });
}

console.log(`\n${passed} עברו, ${failed} נכשלו`);
process.exit(failed === 0 ? 0 : 1);
