/**
 * Expanded Card Preview – מציג 20 שורות קוד בתוך כרטיס בעמוד הקבצים
 */
(function () {
  'use strict';

  const expandedCards = new Set();
  const expandedTargets = new Map();

  /**
   * תקרת זמן לבקשות של הכרטיס — הפתיחה וההעתקה.
   *
   * **למה צריך אותה:** בזמן ההמתנה משהו מוחזק. בפתיחה זה הכרטיס כולו —
   * ``card-preview-expanding`` מבטל עליו לחיצות (``card-preview.css``) — ובהעתקה
   * זה הכפתור, שמושבת עד שהתשובה מגיעה. חיבור half-open — מעבר רשת בנייד — אינו
   * עונה ואינו מתנתק, ו-``fetch`` בלי סיגנל תלוי לנצח, ואיתו מה שהוחזק.
   *
   * **המספר לא נמדד מול הנתיבים האלה.** הוא נלקח מ-``FETCH_TIMEOUT_MS`` שב-
   * ``webapp/templates/base.html``, ושם מתועדות המדידה שממנה הוא נגזר והסיבה
   * שבצד השרת אין תקרה שתסיים את ההמתנה במקומנו.
   */
  const REQUEST_DEADLINE_MS = 15 * 1000;

  /** מזהה של מסמך במונגו — הצורה היחידה שמותר להכניס מהתשובה לכתובת. */
  const OBJECT_ID_RE = /^[a-f0-9]{24}$/i;

  /**
   * הודעה למשתמש לכל קוד שגיאה שהשרת או ההעתקה מחזירים. קוד שאינו כאן מוצג
   * כמו שהוא: אלה ההודעות הישנות של ``file_preview`` ב-``webapp/app.py``.
   */
  const MESSAGES = {
    not_found: 'הקובץ לא נמצא — ייתכן שנמחק או ששמו שונה',
    in_recycle_bin: 'הקובץ נמצא בסל המיחזור',
    service_unavailable: 'אין כרגע חיבור למסד הנתונים — נסו שוב בעוד רגע',
    db_error: 'שגיאה בקריאת הקובץ מהשרת — נסו שוב',
    timeout: 'השרת לא ענה בזמן — נסו שוב',
    network: 'אין חיבור לשרת — בדקו את החיבור ונסו שוב',
    bad_response: 'התקבלה מהשרת תשובה לא צפויה — נסו שוב',
    clipboard_denied: 'הדפדפן לא אישר להעתיק ללוח — נסו שוב',
    clipboard_unavailable: 'הדפדפן לא מאפשר העתקה ללוח בדף הזה',
  };

  function messageFor(code) {
    if (typeof code !== 'string' || !code) return '';
    return Object.prototype.hasOwnProperty.call(MESSAGES, code) ? MESSAGES[code] : code;
  }

  /**
   * הסיגנל שמגביל בקשה ל-``REQUEST_DEADLINE_MS``.
   *
   * ``AbortSignal.timeout`` דוחה את ה-``fetch`` עם ``TimeoutError``, ובכרום
   * 103–123 עם ``AbortError`` (MDN browser-compat-data, ``api/AbortSignal.json``,
   * ``timeout_static``). דפדפן שאינו מכיר אותו מקבל את אותה תקרה מ-
   * ``AbortController`` — נפילה-לאחור על היעדר יכולת, לא על כשל.
   *
   * אותו מבנה חי גם ב-``fetchOpts`` שב-``webapp/templates/base.html`` וב-
   * ``withRequestDeadline`` שב-``webapp/static/js/repo-browser.js``. הוא לא
   * אוחד לקובץ משותף, כי השורות שב-``base.html`` מקובעות מילה במילה בטסט
   * המוטציות ``tests/test_sticky_reminders_polling_browser.py``.
   */
  function requestDeadline() {
    if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
      return AbortSignal.timeout(REQUEST_DEADLINE_MS);
    }
    if (typeof AbortController === 'function') {
      const controller = new AbortController();
      setTimeout(() => controller.abort(), REQUEST_DEADLINE_MS);
      return controller.signal;
    }
    return undefined;
  }

  /** כל ביטול כאן הוא פקיעה של ``requestDeadline`` — אין ביטול מכוון אחר. */
  function isDeadline(err) {
    return !!err && (err.name === 'TimeoutError' || err.name === 'AbortError');
  }

  function redirectToLogin() {
    window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search + window.location.hash);
  }

  /** שגיאה בתוך התצוגה, כטקסט: ההודעה מגיעה גם מהשרת, ולכן היא לא נכנסת כ-HTML. */
  function showPreviewError(wrapper, message) {
    wrapper.innerHTML = '<div class="preview-error"><i class="fas fa-exclamation-triangle"></i> </div>';
    wrapper.firstChild.append(message);
  }

  function findOrCreateWrapper(cardElement) {
    try { cardElement.dataset.previewHost = '1'; } catch (_e) {}
    let wrapper = cardElement.querySelector('.card-code-preview-wrapper');
    if (!wrapper) {
      wrapper = document.createElement('div');
      wrapper.className = 'card-code-preview-wrapper';
      cardElement.appendChild(wrapper);
    }
    return wrapper;
  }

  async function expandCard(fileId, cardElement) {
    if (!fileId) return;

    const previousHost = expandedTargets.get(fileId) || null;
    if (expandedCards.has(fileId)) {
      collapseCard(fileId);
      if (previousHost === cardElement) {
        return;
      }
    }

    if (!cardElement) return;

    expandedTargets.set(fileId, cardElement);

    // חסימת לחיצות כפולות
    if (cardElement.classList.contains('card-preview-expanding')) return;

    cardElement.classList.add('card-preview-expanding');
    const wrapper = findOrCreateWrapper(cardElement);
    wrapper.innerHTML = '\n      <div class="preview-spinner">\n        <i class="fas fa-circle-notch"></i>\n        <span>טוען תצוגה מקדימה...</span>\n      </div>\n    ';

    try {
      const res = await fetch(`/api/file/${encodeURIComponent(fileId)}/preview`, {
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
        signal: requestDeadline()
      });

      if (res.status === 401 || res.status === 302) {
        redirectToLogin();
        return;
      }

      let data = null;
      try {
        data = await res.json();
      } catch (err) {
        // פקיעת התקרה באמצע קריאת הגוף עולה ל-catch החיצוני ומוצגת כ"לא ענה
        // בזמן". גוף שאינו JSON ממשיך הלאה ומוצג כשגיאה בבדיקה שמתחת.
        if (isDeadline(err)) throw err;
      }
      if (!res.ok || !data || data.ok !== true || typeof data.highlighted_html !== 'string') {
        showPreviewError(wrapper, messageFor(data && data.error) || 'שגיאה בטעינת תצוגה מקדימה');
        expandedTargets.delete(fileId);
        return;
      }

      injectSyntaxCSS(data.syntax_css);
      wrapper.innerHTML = buildPreviewHTML(data, fileId);
      cardElement.classList.add('card-preview-expanded');
      expandedCards.add(fileId);
      expandedTargets.set(fileId, cardElement);
    } catch (err) {
      console.error('preview load failed', err);
      showPreviewError(wrapper, isDeadline(err) ? MESSAGES.timeout : 'אירעה שגיאה בעת הטעינה');
      expandedTargets.delete(fileId);
    } finally {
      cardElement.classList.remove('card-preview-expanding');
    }
  }

  function collapseCard(fileId, cardElement) {
    const target = cardElement || expandedTargets.get(fileId) || null;
    expandedCards.delete(fileId);
    if (!target) {
      expandedTargets.delete(fileId);
      return;
    }
    const wrapper = target.querySelector('.card-code-preview-wrapper');
    if (wrapper) wrapper.innerHTML = '';
    target.classList.remove('card-preview-expanded');
    target.classList.remove('card-preview-expanding');
    expandedTargets.delete(fileId);
  }

  function buildPreviewHTML(data, fileId) {
    // ``file_id`` ו-``version`` הם של הגרסה שהוצגה — האחרונה, גם כשהכרטיס מחזיק
    // מזהה של גרסה ישנה (``file_preview`` ב-``webapp/app.py``). הם, וגם מספרי
    // השורות, נכנסים ל-HTML, ולכן נבדקים קודם: מזהה במבנה של מזהה מונגו,
    // ומספרים כמספרים שלמים.
    const shownId = (typeof data.file_id === 'string' && OBJECT_ID_RE.test(data.file_id)) ? data.file_id : fileId;
    const version = (Number.isInteger(data.version) && data.version > 0) ? data.version : null;
    const details = [];
    if (version) details.push(`גרסה ${version}`);
    if (data.has_more && Number.isInteger(data.preview_lines) && Number.isInteger(data.total_lines)) {
      details.push(`מציג ${data.preview_lines} מתוך ${data.total_lines} שורות`);
    }
    const infoLine = details.length
      ? `<p style="opacity:0.7; font-size:0.9rem; margin-top:1rem;">\n           <i class="fas fa-info-circle"></i> ${details.join(' · ')}\n         </p>`
      : '';

    return `
      <div class="card-code-preview">${data.highlighted_html}</div>
      ${infoLine}
      <div class="preview-actions">
        <button class="btn btn-primary btn-icon" onclick="window.location.href='/file/${shownId}'">
          <i class="fas fa-expand-alt"></i>
          <span class="btn-text">פתח דף מלא</span>
        </button>
        <button class="btn btn-secondary btn-icon" data-testid="card-preview-copy" title="העתק את כל הקובץ" aria-label="העתק את כל הקובץ" onclick="window.cardPreview.copyPreviewCode(this, '${shownId}')">
          <i class="fas fa-copy"></i>
          <span class="btn-text">העתק</span>
        </button>
        <button class="btn btn-secondary btn-icon" onclick="window.cardPreview.collapse('${fileId}', this.closest('[data-preview-host]'))">
          <i class="fas fa-times"></i>
          <span class="btn-text">סגור</span>
        </button>
      </div>`;
  }

  function injectSyntaxCSS(css) {
    if (!css) return;
    if (document.getElementById('preview-syntax-css')) return;
    const styleEl = document.createElement('style');
    styleEl.id = 'preview-syntax-css';
    styleEl.textContent = css;
    document.head.appendChild(styleEl);
  }

  function copyError(code) {
    const err = new Error(code);
    err.code = code;
    return err;
  }

  /**
   * התוכן העדכני של הקובץ: ``{code, version}``, או שגיאה עם ``code`` שיש לו
   * הודעה ב-``MESSAGES``. ``api_file_content`` ב-``webapp/app.py`` מחזיר את
   * הגרסה הפעילה האחרונה גם כשהמזהה שייך לגרסה ישנה.
   */
  async function fetchLatestContent(fileId) {
    let res;
    try {
      res = await fetch(`/api/file/${encodeURIComponent(fileId)}/content`, {
        headers: { 'Accept': 'application/json' },
        credentials: 'same-origin',
        cache: 'no-store',
        signal: requestDeadline()
      });
    } catch (err) {
      throw copyError(isDeadline(err) ? 'timeout' : 'network');
    }
    if (res.status === 401) {
      redirectToLogin();
      throw copyError('login');
    }
    let data = null;
    try {
      data = await res.json();
    } catch (err) {
      if (isDeadline(err)) throw copyError('timeout');
      // גוף שאינו JSON (למשל דף שגיאה של proxy): נופל לתשובה לא צפויה, למטה.
      data = null;
    }
    if (!data || typeof data !== 'object' || data.ok !== true || typeof data.code !== 'string') {
      throw copyError((data && typeof data.error === 'string' && data.error) ? data.error : 'bad_response');
    }
    const version = (Number.isInteger(data.version) && data.version > 0) ? data.version : null;
    return { code: data.code, version };
  }

  /**
   * מעתיק ללוח את **כל** הקובץ, כפי שהוא שמור ברגע הלחיצה.
   *
   * התצוגה מציגה רק את תחילת הקובץ, והיא נטענה כשנפתחה — ומאז ייתכן שנשמרה
   * גרסה חדשה. לכן התוכן נמשך מהשרת עכשיו, ולא מה-DOM.
   *
   * **הכתיבה ללוח מתחילה בתוך הלחיצה.** דפדפנים מרשים לכתוב ללוח רק בתוך אירוע
   * של המשתמש (MDN browser-compat-data, ``api/Clipboard.json``, ``write`` ו-
   * ``writeText``: "must be called within user gesture event handlers"; WebKit,
   * "Async Clipboard API": קריאה מחוץ לאירוע נדחית מיד). המתנה לשרת לפני
   * הכתיבה הייתה נדחית בספארי. ``ClipboardItem`` מקבל Promise במקום התוכן
   * עצמו (W3C Clipboard API, ``ClipboardItemData``), ולכן הכתיבה נפתחת כאן
   * והתוכן נכנס כשהשרת עונה. Promise ל-``Blob`` ולא למחרוזת: כרום 98–132 מקבל
   * רק ``Blob`` או Promise ל-``Blob`` (MDN browser-compat-data,
   * ``api/ClipboardItem.json``).
   *
   * דפדפן בלי ``ClipboardItem`` (פיירפוקס לפני 127) כותב ב-``writeText`` אחרי
   * שהתוכן הגיע — נפילה-לאחור על היעדר יכולת. שם הדפדפן עלול לסרב, והסירוב
   * מוצג כהודעה.
   */
  function copyPreviewCode(buttonEl, fileId) {
    if (!buttonEl || buttonEl.disabled) return;
    if (!fileId) {
      alert(MESSAGES.not_found);
      return;
    }
    const clipboard = navigator.clipboard;
    if (!window.isSecureContext || !clipboard) {
      alert(MESSAGES.clipboard_unavailable);
      return;
    }

    const original = buttonEl.innerHTML;
    buttonEl.disabled = true;
    buttonEl.setAttribute('aria-busy', 'true');
    buttonEl.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i>';

    const content = fetchLatestContent(fileId);
    let writing;
    try {
      if (typeof window.ClipboardItem === 'function' && typeof clipboard.write === 'function') {
        const blob = content.then((r) => new Blob([r.code], { type: 'text/plain' }));
        // הסיבה לכישלון נקראת מ-``content`` למטה. בלי ה-catch הזה, דפדפן שזרק
        // כבר בבנאי של ``ClipboardItem`` היה משאיר את ``blob`` בלי מטפל, וכל כשל
        // של הבקשה היה נרשם גם כ-"Uncaught (in promise)".
        blob.catch(() => {});
        writing = clipboard.write([new window.ClipboardItem({ 'text/plain': blob })]);
      } else {
        writing = content.then((r) => clipboard.writeText(r.code));
      }
    } catch (err) {
      writing = Promise.reject(err);
    }

    // שתיהן נאספות יחד: כשהבקשה נכשלה גם הכתיבה נדחית (המפרט דוחה אותה ב-
    // ``NotAllowedError``), וההודעה צריכה את הסיבה האמיתית — זו של הבקשה.
    Promise.allSettled([content, writing]).then(([fetched, written]) => {
      buttonEl.disabled = false;
      buttonEl.removeAttribute('aria-busy');
      if (fetched.status === 'rejected') {
        buttonEl.innerHTML = original;
        const code = fetched.reason && fetched.reason.code;
        if (code === 'login') return; // ``redirectToLogin`` כבר בדרך לדף ההתחברות
        alert(messageFor(code) || MESSAGES.bad_response);
        return;
      }
      if (written.status === 'rejected') {
        console.warn('card preview: clipboard write failed', written.reason);
        buttonEl.innerHTML = original;
        alert(MESSAGES.clipboard_denied);
        return;
      }
      const version = fetched.value.version;
      buttonEl.innerHTML = '<i class="fas fa-check"></i> ' + (version ? `הועתקה גרסה ${version}` : 'הועתק!');
      buttonEl.classList.add('btn-success');
      setTimeout(() => {
        buttonEl.innerHTML = original;
        buttonEl.classList.remove('btn-success');
      }, 1800);
    });
  }

  // חשיפת API
  window.cardPreview = {
    expand: expandCard,
    collapse: collapseCard,
    copyPreviewCode
  };

  // קיצור מקלדת אופציונלי: Ctrl/Cmd+E לכרטיס תחת העכבר
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'e') {
      const hovered = document.querySelector('.file-card:hover');
      if (hovered) {
        const id = hovered.getAttribute('data-file-id');
        if (id) expandCard(id, hovered);
      }
    }
  });

  console.log('✅ Card preview script loaded');
})();
