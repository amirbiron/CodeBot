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
 * - **מה שמשותף לייצוא של המחוברים** — הבקשה לשלד עם תקרת זמן, ההכנסה של המסמך, הטאב וההורדה, וההודעות על כשל —
 *   ב-``utils/styled-export-core.js`` (``window.StyledExportCore``).
 * - **שם המסמך** (``<title>``) הוא הכותרת הראשונה במסמך, ונכנס דרך ``document.title`` — טקסט, לא HTML.
 *
 * התיעוד: ``docs/webapp/markdown-editor.rst``.
 */
(function () {
  'use strict';

  const { getEditorContent } = window.EditorPageUtils;
  const Core = window.StyledExportCore;

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

  // ``styled-export-core.js`` לא נטען (בקשה שנכשלה): הכפתורים גלויים, ולכן לחיצה עליהם אומרת למה אין ייצוא — ולא
  // שותקת.
  if (!Core) {
    console.error('[markdown-editor-export] StyledExportCore is missing; export is unavailable');
    actionButtons.forEach((btn) => {
      btn.addEventListener('click', () => setStatus('רכיב הייצוא לא נטען, ולכן אי אפשר לייצא. נסו לרענן את העמוד.'));
    });
    return;
  }

  function selectedTheme() {
    return panel.querySelector('input[name="mdEditorExportTheme"]:checked');
  }

  // הקובץ השלם, כמחרוזת: השלד, עם המסמך במקום ההערה. שם המסמך — הכותרת הראשונה בו.
  async function buildDocument(themeInput) {
    const box = await Core.renderMarkdown(getEditorContent(textarea), themeInput.getAttribute('data-mermaid-theme'));
    const url = themeInput.getAttribute('data-skeleton-url');
    const skeleton = await Core.fetchText(Core.hasMath(box) ? `${url}?math=1` : url, { timeoutMs: SKELETON_TIMEOUT_MS });
    return Core.assemble(skeleton.text, box, markerText, Core.firstHeadingTitle(box, FALLBACK_TITLE));
  }

  async function exportDocument(mode) {
    const themeInput = selectedTheme();
    if (!themeInput) return;
    let previewWindow = null;
    if (mode === 'preview') {
      previewWindow = Core.openPreviewTab();
      if (!previewWindow) {
        setStatus('הדפדפן חסם את הטאב החדש. אפשר להתיר חלונות קופצים לאתר, או להוריד את הקובץ.');
        return;
      }
    }
    setBusy(true);
    setStatus('מכין את הקובץ…');
    try {
      Core.deliver(await buildDocument(themeInput), previewWindow, DOWNLOAD_NAME);
      setStatus('');
    } catch (err) {
      console.error('[markdown-editor-export] export failed', err);
      if (previewWindow) previewWindow.close();
      setStatus(Core.describeError(err));
    } finally {
      setBusy(false);
    }
  }

  actionButtons.forEach((btn) => {
    btn.addEventListener('click', () => exportDocument(btn.getAttribute('data-md-editor-export-action')));
  });
})();
