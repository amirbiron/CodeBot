/**
 * markdown-deps.js — טעינת התלויות של תצוגת ה-Markdown: הבאנדל המקומי ``md_preview.bundle.js``.
 *
 * משותף לדפדפן הקוד (``repo-browser.js``) ולכרטיסי התיעוד בחיפוש של עמוד הקבצים
 * (``global_search.js``). הבאנדל מגדיר את markdown-it עם כל התוספים, highlight.js, KaTeX
 * ו-Mermaid (``webapp/static_build/md-preview-entry.js``), ו-``MarkdownLiveRenderer``
 * (``live-preview.js``) נשען עליהם.
 *
 * חושף שתי פונקציות גלובליות, באותם שמות שהיו ב-``repo-browser.js``. הקוראים, וגם
 * ``tests/repo-browser-notes.test.js``, פונים אליהן בשם החשוף:
 *
 * - ``loadMarkdownDependencies()`` — טוען את הבאנדל, אם הוא עוד לא רץ.
 * - ``ensureHighlightJsLoaded()`` — מוודא ש-highlight.js זמין, ובלעדיו טוען את הבאנדל.
 *
 * **הבאנדל ישירות, בלי CDN.** התצוגה צריכה את markdown-it יחד עם התוספים שלו, ו-markdown-it
 * מ-CDN מגיע בלעדיהם: בלי הערות, בלי תרשימים ובלי נוסחאות, ובלי שום שגיאה. קודם הבאנדל
 * נטען רק כגיבוי, כשהטעינה מה-CDN נכשלה.
 *
 * **הכתובת נגזרת מהתגית של הקובץ הזה:** אותה תיקייה ואותו ``?v=``. כך התבנית קובעת את
 * הגרסה במקום אחד, והבאנדל מתחלף יחד עם הקוד שטוען אותו (``SEND_FILE_MAX_AGE_DEFAULT`` הוא
 * שנה). אין כתובת בלי גרסה כגיבוי. כשאי אפשר לדעת את הכתובת, הטעינה נדחית במפורש.
 */
(function () {
  'use strict';

  const BUNDLE_FILE = 'md_preview.bundle.js';

  // נמדד ב-7.10.2026 ב-Chromium מול הוובאפ: הבאנדל עובר דחוס ב-br, ‏1,080,562 בתים (כמו
  // בפרודקשן). בלי האטה הוא נטען ורץ בפחות משנייה. ב-400kbps, השהיה של 400ms ו-CPU איטי
  // פי 4 זה לקח 23.5 שניות. הדדליין הוא בערך פי 2.5 מזה. הוא לא נועד לקצר המתנה איטית.
  // הוא שם כדי שבקשה שנתקעה לא תחזיק את הטעינה לנצח.
  const BUNDLE_DEADLINE_MS = 60000;

  // ``currentScript`` מצביע על התגית רק בזמן שהקובץ רץ בפעם הראשונה, ולכן הכתובת נקבעת
  // כאן ולא בזמן הקריאה. במודול ``currentScript`` אינו מצביע על התגית, ואז אין כתובת.
  const bundleSrc = (function bundleUrlFromOwnTag() {
    const own = document.currentScript;
    if (!own || !own.src) {
      return null;
    }
    const ownUrl = new URL(own.src);
    const url = new URL(BUNDLE_FILE, ownUrl);
    url.search = ownUrl.search;
    return url.href;
  })();

  function hljsIsReady() {
    return !!window.hljs && typeof window.hljs.highlightElement === 'function';
  }

  // markdown-it ו-highlight.js מוגדרים יחד בסוף הבאנדל.
  function bundleIsReady() {
    return typeof window.markdownit === 'function' && hljsIsReady();
  }

  // התגיות שהטוען הוסיף לעמוד, לפי כתובת.
  const scripts = new Map();

  /**
   * מוסיף תגית script לכתובת, אם עוד אין, ומחכה עד שהיא רצה ו-``isReady`` מחזיר אמת.
   *
   * קריאות לאותה כתובת חולקות תגית אחת, כלומר בקשה אחת, וכל קריאה מחכה עם דדליין משלה.
   * כשהדדליין עובר ההמתנה נדחית אבל התגית נשארת, כי הבקשה עוד יכולה להסתיים. הקריאה הבאה
   * מחכה לאותה תגית ולא מורידה שוב. תגית שנכשלה, או שרצה בלי להגדיר את מה שחיכו לו, יורדת
   * מהעמוד. אחרת הקריאה הבאה הייתה מחכה לתגית מתה עד הדדליין, ולא הייתה מנסה שוב באמת.
   */
  function loadScript(src, isReady, deadlineMs) {
    if (isReady()) {
      return Promise.resolve();
    }
    let script = scripts.get(src);
    if (!script) {
      const added = document.createElement('script');
      added.src = src;
      const drop = () => {
        added.remove();
        if (scripts.get(src) === added) {
          scripts.delete(src);
        }
      };
      added.addEventListener('error', drop, { once: true });
      added.addEventListener('load', () => {
        if (!isReady()) {
          drop();
        }
      }, { once: true });
      scripts.set(src, added);
      document.head.appendChild(added);
      script = added;
    }

    const tag = script;
    return new Promise((resolve, reject) => {
      const onLoad = () => settle(isReady() ? null : new Error(`script_not_ready:${src}`));
      const onError = () => settle(new Error(`script_load_failed:${src}`));
      const timeoutId = setTimeout(() => settle(new Error(`script_load_timeout:${src}`)), deadlineMs);
      function settle(error) {
        clearTimeout(timeoutId);
        tag.removeEventListener('load', onLoad);
        tag.removeEventListener('error', onError);
        if (error) {
          reject(error);
        } else {
          resolve();
        }
      }
      tag.addEventListener('load', onLoad);
      tag.addEventListener('error', onError);
    });
  }

  async function loadMarkdownDependencies() {
    if (!bundleIsReady()) {
      if (!bundleSrc) {
        throw new Error('markdown_bundle_url_unknown');
      }
      await loadScript(bundleSrc, bundleIsReady, BUNDLE_DEADLINE_MS);
    }
    // ה-patch של diff חל על המופע של hljs, והבאנדל מחליף אותו במופע חדש.
    if (window.SafeHighlight) window.SafeHighlight.patchHighlightAuto();
  }

  async function ensureHighlightJsLoaded() {
    if (!hljsIsReady()) {
      await loadMarkdownDependencies();
      return;
    }
    if (window.SafeHighlight) window.SafeHighlight.patchHighlightAuto();
  }

  window.loadMarkdownDependencies = loadMarkdownDependencies;
  window.ensureHighlightJsLoaded = ensureHighlightJsLoaded;
})();
