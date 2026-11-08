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
 * **"צור קישור"** — באותה שורה, עם אותה ערכה — הוא היוצא מן הכלל היחיד: הוא שולח את הטקסט לשרת, ורק בלחיצה עליו
 * (``markdown_editor_create_share`` ב-``webapp/app.py``), ומקבל קישור קבוע לעמוד מעוצב, וקישור מחיקה. קישור המחיקה הוא
 * העמוד הזה עם ``#delete=<מזהה>.<מפתח>``: החלק שאחרי ``#`` לא נשלח לשרת כשפותחים אותו, ולכן המפתח לא מגיע ללוגים.
 * כשהעמוד נפתח עם החלק הזה, הוא מוריד אותו מהכתובת, מבקש אישור, ומוחק (``markdown_editor_delete_share``), עם המפתח
 * בכותרת ``Authorization`` ולא בגוף הבקשה.
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
  const shareBox = panel.querySelector('[data-md-editor-share]');
  const shareButtons = shareBox ? Array.from(shareBox.querySelectorAll('button')) : [];

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  // כל הכפתורים של השורה, של הייצוא ושל הקישור: ייצוא ויצירת קישור לא רצים יחד
  function setBusy(busy) {
    actionButtons.concat(shareButtons).forEach((btn) => { btn.disabled = busy; });
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
    actionButtons.concat(shareButtons).forEach((btn) => {
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

  // --- "צור קישור" ----------------------------------------------------------------------------------------------
  if (!shareBox) return;

  const shareUrl = shareBox.getAttribute('data-share-url');
  const deleteUrl = shareBox.getAttribute('data-delete-url');
  const maxBytes = Number(shareBox.getAttribute('data-max-bytes'));
  const resultEl = shareBox.querySelector('[data-md-editor-share-result]');
  const linkInput = shareBox.querySelector('[data-md-editor-share-link]');
  const deleteLinkInput = shareBox.querySelector('[data-md-editor-share-delete-link]');
  // תקרת הזמן ליצירה: הבקשה מעלה את כל הטקסט, עד ``data-max-bytes``, ובנייד איטי ההעלאה לוקחת יותר מבקשת השלד.
  // כשהיא נגמרת אי אפשר לדעת אם הקישור נוצר, וההודעה אומרת את זה.
  const SHARE_TIMEOUT_MS = 60000;
  const DELETE_TIMEOUT_MS = 15000;
  // המזהה והמפתח של הקישור האחרון שנוצר כאן, ל"מחק את הקישור עכשיו". רק בזיכרון של העמוד.
  let lastShare = null;

  // הקוד ב-``error`` של תשובת סירוב ← ההודעה. הקודים מ-``markdown_editor_create_share`` / ``markdown_editor_delete_share``,
  // ו-``rate_limit_exceeded`` מה-429 של Flask-Limiter (``_ratelimit_handler``).
  const SHARE_ERRORS = {
    document_too_large: 'המסמך גדול מכדי לשתף אותו בקישור. אפשר להוריד אותו כ-HTML ולשלוח את הקובץ.',
    empty_document: 'אין במסמך טקסט לשתף.',
    unknown_theme: 'הערכה שנבחרה אינה זמינה לקישור. רעננו את העמוד ונסו שוב.',
    rate_limit_exceeded: 'יצרת הרבה קישורים בזמן קצר. אפשר לנסות שוב מאוחר יותר.',
    daily_limit_reached: 'הגענו למכסה היומית של קישורים חדשים באתר. אפשר לנסות שוב מחר, או להוריד את המסמך כ-HTML.',
    not_found: 'הקישור לא נמצא. ייתכן שהוא כבר נמחק.',
  };

  function refusalCode(err) {
    try {
      const data = JSON.parse((err && err.bodyText) || '');
      return data && typeof data.error === 'string' ? data.error : '';
    } catch (_parseErr) {
      // תשובה שאינה JSON (שגיאה של proxy, עמוד 500) — אין קוד, וההודעה הכללית מתאימה
      return '';
    }
  }

  function describeShareError(err, fallback) {
    if (err && (err.name === 'TimeoutError' || err.name === 'AbortError')) return null;
    return SHARE_ERRORS[refusalCode(err)] || fallback;
  }

  async function postJson(url, payload, timeoutMs, extraHeaders) {
    const resp = await Core.fetchText(url, {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, extraHeaders || {}),
      body: JSON.stringify(payload),
      timeoutMs,
    });
    return JSON.parse(resp.text);
  }

  function showResult(share) {
    linkInput.value = share.share_url;
    deleteLinkInput.value = share.delete_url;
    resultEl.hidden = false;
  }

  function hideResult() {
    resultEl.hidden = true;
    linkInput.value = '';
    deleteLinkInput.value = '';
    lastShare = null;
  }

  // ``#delete=<מזהה>.<מפתח>`` מתוך ``delete_url``. שני החלקים בצורה של ``STYLED_SHARE_TOKEN_RE`` (``styled_shares.py``);
  // השרת בודק אותה שוב
  function parseDeleteFragment(value) {
    const match = /^#delete=([A-Za-z0-9_-]+)\.([A-Za-z0-9_-]+)$/.exec(value || '');
    return match ? { token: match[1], key: match[2] } : null;
  }

  async function createShare() {
    const themeInput = selectedTheme();
    if (!themeInput || !shareUrl) return;
    const text = getEditorContent(textarea);
    if (!text.trim()) {
      setStatus(SHARE_ERRORS.empty_document);
      return;
    }
    if (Number.isFinite(maxBytes) && new TextEncoder().encode(text).length > maxBytes) {
      setStatus(SHARE_ERRORS.document_too_large);
      return;
    }
    setBusy(true);
    setStatus('יוצר קישור…');
    try {
      const data = await postJson(shareUrl, { markdown: text, theme: themeInput.value }, SHARE_TIMEOUT_MS);
      const share = parseDeleteFragment(new URL(data.delete_url).hash);
      if (!data.ok || typeof data.share_url !== 'string' || !share) throw new Error('invalid_share_response');
      lastShare = share;
      showResult(data);
      setStatus('הקישור נוצר. שמרו גם את קישור המחיקה.');
    } catch (err) {
      console.error('[markdown-editor-export] share failed', err);
      const message = describeShareError(err, 'לא הצלחנו ליצור קישור. נסו שוב.');
      setStatus(message || 'השרת לא ענה בזמן. ייתכן שהקישור נוצר בכל זאת, אבל אי אפשר להציג אותו. אפשר לנסות שוב.');
    } finally {
      setBusy(false);
    }
  }

  async function deleteShare(share) {
    setBusy(true);
    setStatus('מוחק את הקישור…');
    try {
      // המפתח בכותרת ולא בגוף: את ``Authorization`` מערכת הניטור בשרת לא שומרת (``markdown_editor_delete_share``)
      await postJson(deleteUrl, { token: share.token }, DELETE_TIMEOUT_MS, { Authorization: `Bearer ${share.key}` });
      if (lastShare && lastShare.token === share.token) hideResult();
      setStatus('הקישור נמחק, ומי שיפתח אותו יקבל עמוד שלא נמצא.');
    } catch (err) {
      console.error('[markdown-editor-export] share delete failed', err);
      setStatus(describeShareError(err, 'לא הצלחנו למחוק את הקישור. נסו שוב.') || 'השרת לא ענה בזמן. נסו שוב בעוד רגע.');
    } finally {
      setBusy(false);
    }
  }

  async function copyField(input) {
    try {
      await navigator.clipboard.writeText(input.value);
      setStatus('הועתק.');
    } catch (_copyErr) {
      // בלי הרשאה ללוח (או דפדפן בלעדיו): מסמנים את הטקסט, והגולש מעתיק בעצמו
      input.select();
      setStatus('לא הצלחנו להעתיק. הטקסט מסומן, ואפשר להעתיק אותו ידנית.');
    }
  }

  shareBox.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button || !shareBox.contains(button)) return;
    const action = button.getAttribute('data-md-editor-share-action');
    const copyTarget = button.getAttribute('data-md-editor-share-copy');
    if (action === 'create') {
      createShare();
    } else if (action === 'delete' && lastShare) {
      if (window.confirm('למחוק את הקישור? אחרי המחיקה הוא יפסיק להיפתח לכל מי שקיבל אותו.')) deleteShare(lastShare);
    } else if (copyTarget) {
      const input = document.getElementById(copyTarget);
      if (input) copyField(input);
    }
  });

  // קישור מחיקה שנפתח: החלק שאחרי ``#`` יורד מהכתובת מיד, לפני האישור — כדי שהמפתח לא יישאר בשורת הכתובת ובהיסטוריה,
  // ורענון לא ישאל שוב.
  const pendingDelete = parseDeleteFragment(window.location.hash);
  if (pendingDelete) {
    window.history.replaceState(null, '', window.location.pathname + window.location.search);
    if (window.confirm('למחוק את הקישור ששיתפת? אחרי המחיקה הוא יפסיק להיפתח לכל מי שקיבל אותו.')) {
      deleteShare(pendingDelete);
    } else {
      setStatus('הקישור לא נמחק. אפשר לפתוח שוב את קישור המחיקה מתי שתרצו.');
    }
  }
})();
