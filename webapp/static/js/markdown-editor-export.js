/**
 * הייצוא ל-HTML מעוצב בעורך הציבורי (``/markdown-editor``): "HTML מעוצב" פותח שורה עם הערכות שאפשר לייצא בהן
 * (``EXPORT_THEME_IDS`` ב-``webapp/markdown_editor.py``), ו"הצג" או
 * "הורד HTML" בונים את הקובץ — **בלי לשלוח את הטקסט לשרת**.
 *
 * איך: השרת מגיש רק "שלד" — העמוד המעוצב של הערכה, עם הערת HTML במקום התוכן (``markdown_editor_export_skeleton``
 * ב-``webapp/app.py``). הדפדפן מרנדר את המסמך באותו מנוע כמו התצוגה החיה, ברינדור נפרד ממנה
 * (``MarkdownLiveRenderer.renderForExport`` ב-``live-preview.js``), ומכניס אותו במקום ההערה. רק אחרי הרינדור
 * ידוע אם במסמך יש נוסחה, ואז השלד מתבקש עם ה-CSS של KaTeX (``math=1``) או בלעדיו.
 *
 * - **"הצג"** פותח את הקובץ בטאב חדש, כמו התצוגה המקדימה בחלון הייצוא של המחוברים. הטאב נפתח מיד בלחיצה, לפני
 *   ההמתנה לרינדור ולשלד: דפדפן מתיר ``window.open`` רק זמן קצר אחרי פעולה של המשתמש ("transient activation" בתקן
 *   של HTML), ורינדור של מסמך עם תרשימים יכול להימשך יותר.
 * - **"הורד HTML"** מוריד אותו כ-``DOWNLOAD_NAME``, באותו מנגנון כמו "הורד ‎.md" (``downloadBlob``).
 * - **שם המסמך** (``<title>``) הוא הכותרת הראשונה במסמך, ונכנס דרך ``document.title`` — טקסט, לא HTML.
 *
 * התיעוד: ``docs/webapp/markdown-editor.rst``.
 */
(function () {
  'use strict';

  const { getEditorContent, downloadBlob } = window.EditorPageUtils;

  const DOWNLOAD_NAME = 'document.html';
  // השם כשאין במסמך כותרת
  const FALLBACK_TITLE = 'מסמך';
  // תקרת הזמן לבקשת השלד. הכפתורים מושבתים בזמן הבנייה, ולכן בקשה שלא חוזרת לא יכולה להשאיר אותם מושבתים.
  const SKELETON_TIMEOUT_MS = 15000;

  const panel = document.querySelector('[data-md-editor-export]');
  const toggle = document.querySelector('[data-md-editor-export-toggle]');
  const textarea = document.getElementById('codeTextarea');
  const statusEl = document.querySelector('[data-md-editor-status]');
  if (!panel || !toggle || !textarea) {
    return;
  }
  const markerText = panel.getAttribute('data-content-marker') || '';
  const actionButtons = Array.from(panel.querySelectorAll('[data-md-editor-export-action]'));

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  function setBusy(busy) {
    actionButtons.forEach((btn) => { btn.disabled = busy; });
    panel.setAttribute('aria-busy', busy ? 'true' : 'false');
  }

  toggle.addEventListener('click', () => {
    const open = panel.hidden;
    panel.hidden = !open;
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  function selectedTheme() {
    return panel.querySelector('input[name="mdEditorExportTheme"]:checked');
  }

  // ``AbortSignal.timeout`` כשהדפדפן מכיר אותו; אחרת אותה תקרה מ-``AbortController``; ובדפדפן שאין בו אף אחד מהם —
  // בלי סיגנל, והבקשה נשלחת בלי תקרה. לפי יכולת, לא אחרי כשל. אותו מבנה כמו ``requestDeadline`` ב-``card-preview.js``
  // (ושם ההסבר למה הוא לא אוחד לקובץ משותף).
  function timeoutSignal(ms) {
    if (typeof AbortSignal !== 'undefined' && typeof AbortSignal.timeout === 'function') {
      return AbortSignal.timeout(ms);
    }
    if (typeof AbortController === 'function') {
      const controller = new AbortController();
      setTimeout(() => controller.abort(), ms);
      return controller.signal;
    }
    return undefined;
  }

  async function fetchSkeleton(url, withMath) {
    const target = withMath ? `${url}?math=1` : url;
    const resp = await fetch(target, { credentials: 'same-origin', signal: timeoutSignal(SKELETON_TIMEOUT_MS) });
    if (!resp.ok) {
      throw new Error(`skeleton_http_${resp.status}`);
    }
    return resp.text();
  }

  function findMarker(doc) {
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_COMMENT);
    let node = walker.nextNode();
    while (node) {
      if (node.nodeValue === markerText) return node;
      node = walker.nextNode();
    }
    return null;
  }

  function documentTitle(box) {
    const heading = box.querySelector('h1, h2, h3, h4');
    const text = heading ? heading.textContent.replace(/\s+/g, ' ').trim() : '';
    return text || FALLBACK_TITLE;
  }

  // הקובץ השלם, כמחרוזת: השלד, עם המסמך במקום ההערה.
  async function buildDocument(themeInput) {
    if (!window.MarkdownLiveRenderer || typeof window.MarkdownLiveRenderer.renderForExport !== 'function') {
      throw new Error('renderer_missing');
    }
    const box = await window.MarkdownLiveRenderer.renderForExport(getEditorContent(textarea), {
      mermaidTheme: themeInput.getAttribute('data-mermaid-theme') || undefined,
    });
    const skeleton = await fetchSkeleton(themeInput.getAttribute('data-skeleton-url'), !!box.querySelector('.katex'));
    const doc = new DOMParser().parseFromString(skeleton, 'text/html');
    const marker = findMarker(doc);
    if (!marker) {
      throw new Error('skeleton_marker_missing');
    }
    const fragment = doc.createDocumentFragment();
    Array.from(box.childNodes).forEach((node) => fragment.appendChild(doc.importNode(node, true)));
    marker.replaceWith(fragment);
    doc.title = documentTitle(box);
    return `<!DOCTYPE html>\n${doc.documentElement.outerHTML}`;
  }

  function describeError(err) {
    const message = (err && err.message) || '';
    if (err && (err.name === 'TimeoutError' || err.name === 'AbortError')) {
      return 'השרת לא ענה בזמן. נסו שוב בעוד רגע.';
    }
    if (message === 'skeleton_http_429') {
      return 'יותר מדי ייצואים בזמן קצר. נסו שוב מאוחר יותר.';
    }
    if (message === 'renderer_missing') {
      return 'ספריית ה-Markdown לא נטענה, ולכן אי אפשר לייצא. נסו לרענן את העמוד.';
    }
    return 'הייצוא נכשל. נסו שוב.';
  }

  async function exportDocument(mode) {
    const themeInput = selectedTheme();
    if (!themeInput) return;
    // "הצג": הטאב נפתח עכשיו, בתוך הלחיצה (ראו בראש הקובץ), ומנותק מהעמוד הזה לפני שנטען בו משהו.
    let previewWindow = null;
    if (mode === 'preview') {
      previewWindow = window.open('', '_blank');
      if (!previewWindow) {
        setStatus('הדפדפן חסם את הטאב החדש. אפשר להתיר חלונות קופצים לאתר, או להוריד את הקובץ.');
        return;
      }
      previewWindow.opener = null;
    }
    setBusy(true);
    setStatus('מכין את הקובץ…');
    try {
      const html = await buildDocument(themeInput);
      const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
      if (previewWindow) {
        // הכתובת לא משתחררת: רענון של הטאב טוען אותה שוב, וכתובת ששוחררה הייתה מחזירה שגיאה. הדפדפן משחרר
        // אותה כשהעמוד הזה נסגר.
        previewWindow.location.href = URL.createObjectURL(blob);
      } else {
        downloadBlob(blob, DOWNLOAD_NAME);
      }
      setStatus('');
    } catch (err) {
      console.error('[markdown-editor-export] export failed', err);
      if (previewWindow) previewWindow.close();
      setStatus(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  actionButtons.forEach((btn) => {
    btn.addEventListener('click', () => exportDocument(btn.getAttribute('data-md-editor-export-action')));
  });
})();
