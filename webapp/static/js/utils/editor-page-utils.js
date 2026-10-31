/**
 * עזרים לעמודים שיש בהם עורך קוד וטיוטה מקומית — מקור אחד במקום עותק בכל עמוד.
 *
 * הצרכנים: ``edit-draft.js`` (עמוד העריכה ועמוד הצפייה), ``upload-page.js`` (עמוד ההעלאה),
 * ``file-form-manager.js`` (העריכה וההעלאה) ו-``markdown-editor.js`` (העורך הציבורי,
 * ``/markdown-editor``). עד העורך הציבורי לכל אחד מהם היה עותק משלו: ``edit-draft.js``
 * ו-``upload-page.js`` החזיקו את אותו בלוק בדיוק, ו-``file-form-manager.js`` את ``sleep`` ואת
 * ``waitFor``.
 *
 * נטען בתגית ``<script defer>`` לפני כל צרכן, באותו עמוד: סקריפטים עם ``defer`` רצים לפי סדר
 * התגיות, והצרכנים קוראים את ``window.EditorPageUtils`` כבר בזמן הטעינה שלהם.
 * ``tests/editor-page-utils.test.js`` בודק את הפונקציות, ואת הסדר בכל תבנית שטוענת צרכן.
 */
(function () {
  'use strict';

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, ms));
  }

  /**
   * מחכה עד ש-``fn()`` מחזיר ערך אמיתי, ומחזיר אותו; ``null`` אם עבר ``timeoutMs``.
   *
   * "עוד לא" הוא ערך ריק, לא חריגה. חריגה מ-``fn`` היא באג, והיא עולה הלאה: עד המעבר לכאן היא נבלעה,
   * וכך באג ב-``fn`` נראה בדיוק כמו "לא נטען בזמן" — העורך פשוט לא עלה, בלי שום שגיאה
   * (``RECURRING-PATTERNS.md`` R10 ב-amir-bug-patterns). הצרכנים מעבירים קריאה של שדה ב-``window``.
   */
  async function waitFor(fn, { timeoutMs = 2500, intervalMs = 100 } = {}) {
    const started = Date.now();
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const value = fn();
      if (value) return value;
      if (Date.now() - started > timeoutMs) return null;
      // eslint-disable-next-line no-await-in-loop
      await sleep(intervalMs);
    }
  }

  function debounce(fn, wait) {
    let timeout;
    return (...args) => {
      clearTimeout(timeout);
      timeout = setTimeout(() => fn(...args), wait);
    };
  }

  /** שעה:דקה לתצוגה, לפי השעון של הדפדפן ("נשמר לאחרונה ב-..."). */
  function formatTime(value) {
    try {
      return new Intl.DateTimeFormat('he-IL', { hour: '2-digit', minute: '2-digit' }).format(new Date(value));
    } catch (_) {
      const date = new Date(value);
      const h = String(date.getHours()).padStart(2, '0');
      const m = String(date.getMinutes()).padStart(2, '0');
      return `${h}:${m}`;
    }
  }

  /**
   * התוכן שבעורך: מ-CodeMirror אם הוא עלה, אחרת מה-textarea. כשהעורך עובר לעורך הפשוט, ``EditorManager``
   * מעתיק את התוכן ל-textarea ומאפס את ``cmInstance``, ולכן התנאי כאן מספיק ואין ``catch``: חריגה בקריאה
   * היא באג, ולא סיבה לקרוא תוכן אחר בשקט.
   */
  function getEditorContent(fallbackTextarea) {
    if (window.editorManager && window.editorManager.cmInstance && window.editorManager.cmInstance.state) {
      return window.editorManager.cmInstance.state.doc.toString();
    }
    const target = (window.editorManager && window.editorManager.textarea) || fallbackTextarea;
    return (target && target.value) || '';
  }

  /**
   * מחליף את כל התוכן שבעורך, ומודיע עליו ב-``input`` כדי שהתצוגה החיה והטיוטה יתעדכנו.
   *
   * בלי ``catch`` סביב CodeMirror: עד המעבר לכאן כשל שם נבלע, וה-textarea התעדכן לבד — כלומר העורך
   * הציג טקסט אחד, ו-``getEditorContent`` (שקורא מ-CodeMirror) החזיר אותו טקסט ישן לטיוטה. עכשיו החריגה
   * עולה לפני שמשהו השתנה.
   */
  function setEditorContent(nextValue, fallbackTextarea) {
    const value = typeof nextValue === 'string' ? nextValue : '';
    if (window.editorManager && window.editorManager.cmInstance && window.editorManager.cmInstance.state) {
      const view = window.editorManager.cmInstance;
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: value } });
    }
    const target = (window.editorManager && window.editorManager.textarea) || fallbackTextarea;
    if (target) {
      target.value = value;
      target.dispatchEvent(new Event('input', { bubbles: true }));
    }
  }

  /**
   * האם אפשר לכתוב ל-localStorage.
   *
   * ה-``catch`` רחב בכוונה: המצב "אין אחסון" מוצהר לכל כשל של האחסון עצמו — חסימה, מכסה מלאה, או
   * דפדפן שלא מספק אותו — והחריגה משתנה בין הסיבות. בתוך ה-``try`` אין דבר מלבד הפעולות על האחסון,
   * ולכן באג אחר לא יכול לקבל כאן את התווית "אין אחסון".
   */
  function storageAvailable() {
    try {
      const testKey = '__editorPageUtilsTest__';
      localStorage.setItem(testKey, 'ok');
      localStorage.removeItem(testKey);
      return true;
    } catch (_) {
      return false;
    }
  }

  if (typeof window !== 'undefined') {
    window.EditorPageUtils = Object.freeze({
      sleep,
      waitFor,
      debounce,
      formatTime,
      getEditorContent,
      setEditorContent,
      storageAvailable,
    });
  }
})();
