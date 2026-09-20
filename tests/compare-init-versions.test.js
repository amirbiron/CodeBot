'use strict';
/**
 * בדיקות ל-``webapp/static/js/compare.js`` — מי קובע אילו שתי גרסאות מושוות.
 *
 * הרצה:  node tests/compare-init-versions.test.js
 * (הג'וב ``JS Tests (node)`` ב-CI מרים כל ``tests/*.test.js`` לבד.)
 *
 * **למה זה קיים.** קודם ``init`` חישב בעצמו ``currentVersion - 1`` ו-
 * ``currentVersion``, בזמן שהשרת והתבנית חישבו את אותו דבר בנפרד. שלוש
 * תשובות לאותה שאלה הן שלוש דרכים להיסחף, והסחיפה כאן נראית כרשימה
 * נפתחת שמסומנת על גרסה אחת ודיף שמציג אחרת. ``/compare/<id>?left=1&right=3``
 * פשוט לא עבד: הכתובת ביקשה 1 ו-3, והדיף הראה 2 ו-3.
 *
 * הבדיקה היא **התנהגותית ולא מבנית**: היא קוראת ל-``init`` ובודקת לאיזו
 * כתובת המודול פנה בפועל. בדיקה שרק מחפשת שורת קוד הייתה עוברת גם אם
 * החישוב יחזור במקום אחר בקובץ.
 *
 * הקובץ נטען כמו בדפדפן — script קלאסי שמגדיר ``window.CompareView`` — כי
 * ``package.json`` מוגדר ``"type": "module"``.
 */

import assert from 'assert';
import fs from 'fs';
import path from 'path';
import vm from 'vm';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const MODULE_PATH = path.join(
  __dirname, '..', 'webapp', 'static', 'js', 'compare.js');

/** טוען את המודול בסביבה מינימלית ומחזיר אותו יחד ברשימת הכתובות שנקראו. */
function loadCompareView() {
  const requested = [];
  const sandbox = {};
  sandbox.window = sandbox;
  sandbox.document = {
    // כל האלמנטים חסרים; המודול משתמש ב-``?.`` ולכן זה מסלול תקף.
    getElementById: () => null,
    querySelectorAll: () => [],
    querySelector: () => null,
    addEventListener: () => {},
    // ``remove`` נדרש כי ``showError`` מתזמן הסרה של ההודעה ב-``setTimeout``,
    // וחריגה בטיימר אחרי שהבדיקות הסתיימו מפילה את התהליך.
    createElement: () => ({ style: {}, classList: { add() {}, remove() {} },
                            appendChild() {}, setAttribute() {},
                            remove() {}, textContent: '', innerHTML: '' }),
  };
  const stubNode = { appendChild() {}, removeChild() {}, style: {},
                     classList: { add() {}, remove() {} } };
  sandbox.document.body = stubNode;
  sandbox.document.head = stubNode;
  sandbox.document.documentElement = stubNode;
  sandbox.fetch = (url) => {
    requested.push(url);
    // דחייה מיידית: הבדיקה היא על הכתובת, לא על הרינדור שאחריה.
    return Promise.reject(new Error('stub'));
  };
  sandbox.console = { error: () => {}, warn: () => {}, log: () => {} };
  sandbox.setTimeout = setTimeout;
  sandbox.clearTimeout = clearTimeout;
  sandbox.Map = Map;

  vm.createContext(sandbox);
  vm.runInContext(fs.readFileSync(MODULE_PATH, 'utf8'), sandbox,
                  { filename: 'compare.js' });
  return { view: sandbox.window.CompareView, requested };
}

const BASE = { fileId: 'abc123', fileName: 'test.py', language: 'python' };

function test_init_uses_the_versions_it_was_given() {
  const { view, requested } = loadCompareView();
  view.init({ ...BASE, currentVersion: 3, leftVersion: 1, rightVersion: 3 });
  assert.strictEqual(requested.length, 1, 'לא נשלחה בקשת השוואה כלל');
  assert.ok(
    requested[0].includes('left=1') && requested[0].includes('right=3'),
    `המודול חישב גרסאות בעצמו במקום להשתמש במה שקיבל: ${requested[0]}`
  );
}

function test_init_does_not_fall_back_to_previous_and_current() {
  /** הגרסאות שהשרת שלח שונות מברירת המחדל, ולכן הן ראיה ולא צירוף מקרים. */
  const { view, requested } = loadCompareView();
  view.init({ ...BASE, currentVersion: 9, leftVersion: 2, rightVersion: 5 });
  assert.ok(
    !requested[0].includes('left=8'),
    `המודול חזר ל-currentVersion-1 במקום לגרסה שביקשו: ${requested[0]}`
  );
  assert.ok(requested[0].includes('left=2') && requested[0].includes('right=5'),
            `כתובת לא צפויה: ${requested[0]}`);
}

const tests = [
  test_init_uses_the_versions_it_was_given,
  test_init_does_not_fall_back_to_previous_and_current,
];

let failed = 0;
for (const t of tests) {
  try {
    t();
    console.log(`  ok  ${t.name}`);
  } catch (err) {
    failed += 1;
    console.error(`  FAIL ${t.name}: ${err.message}`);
  }
}
if (failed) {
  console.error(`${failed} בדיקות נכשלו`);
  process.exit(1);
}
console.log(`${tests.length} בדיקות עברו`);
