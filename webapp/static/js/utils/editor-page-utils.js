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

  /** מחכה עד ש-``fn()`` מחזיר ערך אמיתי, ומחזיר אותו; ``null`` אם עבר ``timeoutMs``. */
  async function waitFor(fn, { timeoutMs = 2500, intervalMs = 100 } = {}) {
    const started = Date.now();
    // eslint-disable-next-line no-constant-condition
    while (true) {
      try {
        const value = fn();
        if (value) return value;
      } catch (_) {
        // fn בודק אם משהו כבר נטען (למשל window.editorManager). חריגה כאן פירושה "עוד לא",
        // בדיוק כמו ערך ריק, ולכן ממשיכים לחכות עד הזמן הקצוב.
      }
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

  /** התוכן שבעורך: מ-CodeMirror אם הוא עלה, אחרת מה-textarea. */
  function getEditorContent(fallbackTextarea) {
    try {
      if (window.editorManager && window.editorManager.cmInstance && window.editorManager.cmInstance.state) {
        return window.editorManager.cmInstance.state.doc.toString();
      }
    } catch (_) {
      // מופע CodeMirror שנהרס באמצע: ה-textarea שלמטה מחזיק את אותו תוכן.
    }
    const target = (window.editorManager && window.editorManager.textarea) || fallbackTextarea;
    return (target && target.value) || '';
  }

  /** מחליף את כל התוכן שבעורך, ומודיע עליו ב-``input`` כדי שהתצוגה החיה והטיוטה יתעדכנו. */
  function setEditorContent(nextValue, fallbackTextarea) {
    const value = typeof nextValue === 'string' ? nextValue : '';
    try {
      if (window.editorManager && window.editorManager.cmInstance && window.editorManager.cmInstance.state) {
        const view = window.editorManager.cmInstance;
        const length = view.state.doc.length;
        view.dispatch({ changes: { from: 0, to: length, insert: value } });
      }
    } catch (_) {
      // אם CodeMirror לא קיבל את השינוי, ה-textarea שלמטה עדיין מתעדכן, וממנו התוכן נקרא.
    }
    const target = (window.editorManager && window.editorManager.textarea) || fallbackTextarea;
    if (target) {
      target.value = value;
      try {
        target.dispatchEvent(new Event('input', { bubbles: true }));
      } catch (_) {
        // דפדפן ישן בלי בנאי Event: התוכן כבר הוחלף, רק ההודעה למאזינים לא יצאה.
      }
    }
  }

  /** האם אפשר לכתוב ל-localStorage. בגלישה פרטית או כשהאתר חסום לאחסון, הכתיבה זורקת. */
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
