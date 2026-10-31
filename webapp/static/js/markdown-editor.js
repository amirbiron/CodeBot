/**
 * העורך הציבורי (``/markdown-editor``): מעלה את העורך, שומר טיוטה בדפדפן, ומפעיל את הכפתורים
 * "הורד ‎.md", "ניקוי" ו"טען דוגמה".
 *
 * העורך, התצוגה החיה וסרגל ה-MD הם הרכיבים של עמוד העריכה (ראו ההערה בראש
 * ``templates/markdown_editor.html``). הקובץ הזה רק מחבר אותם, ומחזיק את מה שאין בעמוד העריכה:
 *
 * - **הטיוטה.** ב-``localStorage``, תחת ``STORAGE_KEY``, כאובייקט JSON אחד ``{code, savedAt}``.
 *   היא משוחזרת לתוך ה-textarea כבר כשהסקריפט רץ, לפני ``DOMContentLoaded``: הבקר של התצוגה החיה
 *   נבנה שם ומרנדר מיד (``data-preview-autostart``), וכך הוא מרנדר את הטיוטה ולא את ההדגמה.
 *   טקסט ששווה בדיוק להדגמה אינו טיוטה: הוא נמחק מהאחסון, כדי שהדגמה מעודכנת תגיע גם למי שלא
 *   כתב כלום. "ניקוי" שומר טיוטה ריקה, כדי שבביקור הבא העורך יישאר ריק ולא יחזור להדגמה.
 * - **טקסט ההדגמה** הוא ``textarea.defaultValue``: התוכן שהשרת שלח בתוך התגית. כתיבה בעורך משנה את
 *   ``value`` ולא אותו.
 *
 * בשני חלונות פתוחים של העמוד, כל אחד שומר את הטקסט שלו, והאחרון שנשמר הוא מה שיופיע בביקור הבא.
 */
(function () {
  'use strict';

  const {
    waitFor, debounce, formatTime, getEditorContent, setEditorContent, storageAvailable,
  } = window.EditorPageUtils;

  const STORAGE_KEY = 'markdownEditorDraft.v1';
  const DOWNLOAD_NAME = 'document.md';
  const SAVE_DELAY_MS = 800;
  const REVOKE_DELAY_MS = 40000;

  const textarea = document.getElementById('codeTextarea');
  const container = document.getElementById('editorContainer');
  const statusEl = document.querySelector('[data-md-editor-status]');
  if (!textarea || !container) {
    return;
  }

  const demoText = textarea.defaultValue;
  const canStore = storageAvailable();

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  /** הטיוטה מהאחסון, או ``null``. מה שאינו בצורה שהקובץ הזה כותב — נחשב כאילו אין טיוטה. */
  function loadDraft() {
    if (!canStore) return null;
    let raw = null;
    try {
      raw = localStorage.getItem(STORAGE_KEY);
    } catch (err) {
      // כשל של האחסון עצמו (חסום, או נחסם אחרי הבדיקה בטעינה): אין ממה לשחזר.
      console.warn('[markdown-editor] failed to read the draft', err);
      return null;
    }
    if (!raw) return null;
    let parsed = null;
    try {
      parsed = JSON.parse(raw);
    } catch (err) {
      // רק JSON פגום הוא "אין טיוטה". כל חריגה אחרת היא באג, ועולה.
      if (!(err instanceof SyntaxError)) throw err;
      console.warn('[markdown-editor] ignoring an unreadable draft', err);
      return null;
    }
    if (!parsed || typeof parsed !== 'object' || typeof parsed.code !== 'string') {
      console.warn('[markdown-editor] ignoring a draft in an unknown shape');
      return null;
    }
    return { code: parsed.code };
  }

  // מה שמיוצג עכשיו באחסון: הטקסט של הטיוטה, או ההדגמה כשאין טיוטה.
  let persisted = demoText;

  function saveDraft() {
    if (!canStore) return;
    const code = getEditorContent(textarea);
    if (code === persisted) return;
    const savedAt = code === demoText ? null : Date.now();
    // ה-try עוטף רק את הפעולה על האחסון: כשל שלה (בעיקר מכסה מלאה) הוא "השמירה נכשלה". הטקסט עדיין
    // בעורך; רק השמירה לביקור הבא נכשלה.
    try {
      if (savedAt === null) {
        localStorage.removeItem(STORAGE_KEY);
      } else {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ code, savedAt }));
      }
    } catch (err) {
      console.warn('[markdown-editor] failed to save the draft', err);
      setStatus('לא הצלחתי לשמור את הטיוטה בדפדפן. כדי לא לאבד את הטקסט, הורידו אותו כקובץ.');
      return;
    }
    persisted = code;
    setStatus(savedAt === null ? '' : `הטיוטה נשמרה בדפדפן ב-${formatTime(savedAt)}`);
  }

  // שחזור — עכשיו, לפני DOMContentLoaded (ראו בראש הקובץ).
  const draft = loadDraft();
  if (draft) {
    textarea.value = draft.code;
    persisted = draft.code;
    setStatus('הטיוטה שלך מהביקור הקודם שוחזרה.');
  } else if (!canStore) {
    setStatus('הדפדפן לא מאפשר שמירה מקומית, ולכן הטקסט לא יישמר כשתצאו מהעמוד.');
  }

  const debouncedSave = debounce(saveDraft, SAVE_DELAY_MS);
  // CodeMirror מעתיק את התוכן ל-textarea ומודיע עליו ב-input (editor-manager.js), ולכן זה מכסה
  // גם כתיבה בעורך המתקדם.
  textarea.addEventListener('input', debouncedSave);
  // יציאה מהעמוד: בנייד beforeunload לא תמיד נשלח, ו-visibilitychange ל-hidden הוא האירוע האחרון
  // שבטוח מגיע. pagehide מכסה דפדפן שאינו שולח אותו בסגירה.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') saveDraft();
  });
  window.addEventListener('pagehide', saveDraft);

  function clearText() {
    if (!getEditorContent(textarea)) return;
    if (!window.confirm('למחוק את כל הטקסט שבעורך?')) return;
    setEditorContent('', textarea);
    saveDraft();
  }

  function loadDemo() {
    const current = getEditorContent(textarea);
    if (current === demoText) return;
    if (current.trim() && !window.confirm('להחליף את הטקסט שבעורך בטקסט ההדגמה? הטקסט הנוכחי יימחק.')) return;
    setEditorContent(demoText, textarea);
    saveDraft();
  }

  function downloadText() {
    const blob = new Blob([getEditorContent(textarea)], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = DOWNLOAD_NAME;
    document.body.appendChild(link);
    link.click();
    link.remove();
    // משחררים את הכתובת אחרי 40 שניות, כמו FileSaver.js, ולא מיד אחרי click(): כך ההורדה לא
    // תלויה ברגע המדויק שבו הדפדפן קורא את הכתובת. עד אז נשאר בזיכרון Blob בגודל הטקסט.
    setTimeout(() => URL.revokeObjectURL(url), REVOKE_DELAY_MS);
  }

  const actions = { download: downloadText, clear: clearText, 'load-demo': loadDemo };
  document.querySelectorAll('[data-md-editor-action]').forEach((btn) => {
    const handler = actions[btn.getAttribute('data-md-editor-action')];
    if (handler) btn.addEventListener('click', handler);
  });

  (async () => {
    const manager = await waitFor(() => window.editorManager, { timeoutMs: 3500, intervalMs: 100 });
    if (!manager || typeof manager.initEditor !== 'function') {
      // העורך נשאר textarea רגיל: הכתיבה, התצוגה החיה והטיוטה עובדים גם כך.
      console.warn('[markdown-editor] editorManager is not available; staying with the plain textarea');
      return;
    }
    try {
      await manager.initEditor(container, {
        language: 'markdown',
        value: textarea.value,
        theme: 'dark',
        fixedEditor: true,
      });
    } catch (err) {
      console.error('[markdown-editor] initEditor failed', err);
    }
  })();
})();
