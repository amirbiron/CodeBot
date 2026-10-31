/**
 * md-code-blocks.js — בלוק קוד של מסמך Markdown: המסגרת, פס הכותרת עם שם השפה, וכפתור ההעתקה.
 *
 * עד שהקובץ הזה נוצר, הבלוק נבנה בתוך הסקריפט של ``md_preview.html`` (``addCopyButtons``), והתצוגה
 * החיה בעמודי העריכה וההעלאה בנתה במקומו כפתור קטן בפינת ה-``pre`` — כמו בדפדפן הריפו. עכשיו שתי
 * התצוגות בונות את אותו בלוק מאותו קוד, והעיצוב שלו (``.code-block``, ``.md-code-header``,
 * ``.md-code-lang``, ``.md-copy-btn``) יושב ב-``webapp/static/css/md-content-layout.css``.
 *
 * מי קורא:
 *   - ``md_preview.html`` — אחרי רינדור ה-Mermaid, כך שבלוק ```mermaid כבר הוחלף בתרשים.
 *   - ``live-preview.js`` — ``MarkdownLiveRenderer.enhance`` עם ``documentCodeBlocks: true``, באותו סדר.
 *     דפדפן הריפו וכרטיסי החיפוש בתיעוד קוראים ל-``enhance`` בלי האפשרות, ושומרים על הכפתור הקטן
 *     שמעוצב ב-``markdown-preview.css``.
 *
 * ``enhance`` אידמפוטנטי: בלוק שכבר עטוף, או שכבר יש לו פס כותרת או כפתור, אינו נבנה פעמיים.
 */
(function (root) {
  'use strict';

  // משך הסימון "הועתק" / "נכשל" על הכפתור.
  var COPY_FEEDBACK_MS = 1800;

  var COPY_ICONS =
    '<svg class="icon-copy" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true" stroke-linecap="round" stroke-linejoin="round" stroke-width="2">' +
    '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect>' +
    '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path>' +
    '</svg>' +
    '<svg class="icon-check" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" aria-hidden="true" stroke-linecap="round" stroke-linejoin="round" stroke-width="2">' +
    '<polyline points="20 6 9 17 4 12"></polyline>' +
    '</svg>' +
    '<span class="sr-only">העתק קוד</span>';

  // שם השפה כשה-fence לא ציין שפה: לפי כיוון העמוד, כמו בתצוגת המסמך.
  function fallbackLanguage(doc) {
    return doc && doc.documentElement && doc.documentElement.dir === 'rtl' ? 'טקסט' : 'Text';
  }

  function languageFromClasses(className) {
    var classes = (className || '').split(/\s+/);
    for (var i = 0; i < classes.length; i += 1) {
      var cls = classes[i];
      if (!cls) continue;
      if (cls.indexOf('language-') === 0) return cls.replace(/^language-/, '');
      if (cls.indexOf('lang-') === 0) return cls.replace(/^lang-/, '');
    }
    return null;
  }

  // התווית בפס הכותרת: ``data-language`` / ``data-lang``, אחריהם מחלקת ``language-*`` / ``lang-*``
  // של ה-``code`` ואז של ה-``pre``. מקפים וקווים תחתונים הופכים לרווח, וכל מילה באות גדולה.
  function detectLanguage(pre) {
    var doc = pre.ownerDocument;
    var code = pre.querySelector('code');
    var lang = null;
    if (code) {
      lang = code.getAttribute('data-language') || code.getAttribute('data-lang');
      if (!lang && code.dataset) {
        lang = code.dataset.language || code.dataset.lang || null;
      }
      if (!lang) {
        lang = languageFromClasses(code.className);
      }
    }
    if (!lang && pre.className) {
      lang = languageFromClasses(pre.className);
    }
    if (!lang) return fallbackLanguage(doc);
    lang = lang.replace(/[-_]+/g, ' ').trim();
    if (!lang) return fallbackLanguage(doc);
    return lang.replace(/\b\w/g, function (ch) { return ch.toUpperCase(); });
  }

  function showCopyResult(btn, cls, other) {
    btn.classList.remove(other);
    btn.classList.add(cls);
    setTimeout(function () { btn.classList.remove(cls); }, COPY_FEEDBACK_MS);
  }

  // ``options.announce(message)`` — הודעה לקורא מסך; ``options.fallbackCopy(text)`` — העתקה כשה-Clipboard
  // API נכשל, ומחזירה אמת בהצלחה. שתיהן של העמוד המארח, ושתיהן רשות: בלי ``fallbackCopy`` כשל של
  // ה-API מסומן ככשל על הכפתור.
  function buildCopyButton(doc, pre, options) {
    var btn = doc.createElement('button');
    btn.type = 'button';
    btn.className = 'md-copy-btn';
    btn.setAttribute('aria-label', 'העתק קוד');
    btn.setAttribute('title', 'העתק קוד');
    btn.innerHTML = COPY_ICONS;
    var announce = typeof options.announce === 'function' ? options.announce : function () {};
    btn.addEventListener('click', async function () {
      // textContent ולא innerText: innerText נגזר מהפריסה, ומוסיף ירידת שורה בכל גבול של אלמנט בלוק.
      // בבלוק עברי עם קוד פנימי, העטיפה של wrapInnerFences היא אלמנט בלוק, ו-innerText הוסיף שורה
      // ריקה לפני הקטע ואחריו (נמדד ב-Chromium 141). textContent הוא התווים עצמם.
      var codeEl = pre.querySelector('code');
      var text = (codeEl && codeEl.textContent) || pre.textContent;
      try {
        await navigator.clipboard.writeText(text);
        showCopyResult(btn, 'copied', 'copy-error');
        announce('הקוד הועתק ללוח');
      } catch (err) {
        if (typeof options.fallbackCopy === 'function' && options.fallbackCopy(text)) {
          showCopyResult(btn, 'copied', 'copy-error');
          announce('הקוד הועתק ללוח');
        } else {
          console.warn('md-code-blocks: copy failed', err);
          showCopyResult(btn, 'copy-error', 'copied');
          announce('ההעתקה נכשלה');
        }
      }
    });
    btn.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        btn.click();
      }
    });
    return btn;
  }

  // עוטף כל ``pre`` שתחת ``container`` ב-``div.code-block``, ומוסיף לפניו פס כותרת עם שם השפה
  // וכפתור העתקה.
  function enhance(container, options) {
    if (!container) return;
    var opts = options || {};
    var doc = container.ownerDocument;
    container.querySelectorAll('pre').forEach(function (pre) {
      var wrapper = pre.parentElement;
      if (!wrapper || !wrapper.classList || !wrapper.classList.contains('code-block')) {
        wrapper = doc.createElement('div');
        wrapper.className = 'code-block';
        pre.replaceWith(wrapper);
        wrapper.appendChild(pre);
      }
      var header = wrapper.querySelector('.md-code-header');
      if (!header) {
        header = doc.createElement('div');
        header.className = 'md-code-header';
        wrapper.insertBefore(header, pre);
      }
      var langEl = header.querySelector('.md-code-lang');
      if (!langEl) {
        langEl = doc.createElement('span');
        langEl.className = 'md-code-lang';
        header.insertBefore(langEl, header.firstChild || null);
      }
      langEl.textContent = detectLanguage(pre);
      if (!header.querySelector('.md-copy-btn')) {
        header.appendChild(buildCopyButton(doc, pre, opts));
      }
    });
  }

  var api = {
    enhance: enhance,
    detectLanguage: detectLanguage,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;   // לבדיקות מ-Node
  }
  if (root) {
    root.MdCodeBlocks = api;   // שימוש בדפדפן
  }
})(typeof window !== 'undefined' ? window : null);
