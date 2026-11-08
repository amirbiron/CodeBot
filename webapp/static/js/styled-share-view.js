/**
 * עמוד קישור השיתוף המעוצב, בצורה השנייה (``/shared/styled/<token>``; ``format`` ב-``styled_shares.py``): הטקסט של
 * הקובץ מגיע בתוך העמוד, כ-JSON ב-``#ckShareSource``, והסקריפט הזה מרנדר אותו באותו מנוע כמו התצוגה החיה
 * (``MarkdownLiveRenderer.renderForExport``, דרך ``StyledExportCore``) ומכניס אותו במקום ההערה שבשלד. כך מי שפותח את
 * הקישור רואה את מה שבעל הקובץ ראה בתצוגה, ואת אותו HTML כמו בקובץ שיורד.
 *
 * - **סקריפט ההעתקה** רץ לפני הסקריפט הזה, כשהמסמך עוד לא בעמוד, ולכן כפתורי ההעתקה מתווספים כאן, אחרי ההכנסה
 *   (``window.ckAttachCopyButtons`` מ-``COPY_CODE_SCRIPT``).
 * - **עוגן בכתובת** (``#סעיף``) לא נמצא כשהעמוד נטען, כי המסמך עוד לא היה בו. Chromium ממשיך לנסות עד ``load``,
 *   אבל רינדור שנגמר אחריו — מסמך ארוך, טלפון איטי — לא נגלל לבד (נמדד ב-``test_a_share_opens_at_the_anchor_in_its_address``,
 *   שמעכב את הרינדור עד אחרי ``load``), ולכן הגלילה אליו כאן.
 * - **כשל** נכתב בשורת המצב (``#ckShareStatus``), במקום "טוען", ובקונסול.
 * - **קישור שגולש יצר בעורך הציבורי** (``publicEditor`` ב-``#ckShareSource``, ``render_public_editor_share_page``): לטקסט
 *   אין שם קובץ, ולכן שם העמוד הוא הכותרת הראשונה במסמך (``firstHeadingTitle``, כמו בקובץ שיוצא מהעורך), כטקסט. וכל
 *   קישור במסמך מקבל ``rel="ugc nofollow noreferrer"`` (``USER_CONTENT_LINK_REL``): הקישורים של גולש, ולא של האתר.
 *
 * ה-CSP של העמוד: ``styled_share_page_csp`` ב-``services/styled_export_service.py``. התיעוד: ``docs/webapp/styled-export.rst``.
 */
(function () {
  'use strict';

  const FAILED_MESSAGE = 'לא הצלחנו להציג את המסמך. נסו לרענן את העמוד.';
  // ``ugc`` ו-``nofollow`` — לסורקים: הקישור של גולש, והאתר לא ממליץ עליו. ``noreferrer`` — היעד לא מקבל את כתובת העמוד
  const USER_CONTENT_LINK_REL = 'ugc nofollow noreferrer';

  function markUserContent(box) {
    box.querySelectorAll('a[href]').forEach((a) => a.setAttribute('rel', USER_CONTENT_LINK_REL));
  }

  function readSource() {
    const el = document.getElementById('ckShareSource');
    const source = el ? JSON.parse(el.textContent) : null;
    if (!source || typeof source.markdown !== 'string' || typeof source.marker !== 'string') {
      throw new Error('share_source_missing');
    }
    return source;
  }

  function scrollToHash() {
    if (!window.location.hash) return;
    let id = window.location.hash.slice(1);
    try {
      id = decodeURIComponent(id);
    } catch (_err) {
      // כתובת עם קידוד שבור — מחפשים את המזהה כמו שהוא
    }
    const target = document.getElementById(id);
    if (target) target.scrollIntoView();
  }

  async function render() {
    const status = document.getElementById('ckShareStatus');
    try {
      const Core = window.StyledExportCore;
      if (!Core) throw new Error('renderer_missing');
      const source = readSource();
      const box = await Core.renderMarkdown(source.markdown, source.mermaidTheme);
      const marker = Core.findMarker(document, source.marker);
      if (!marker) throw new Error('skeleton_marker_missing');
      if (source.publicEditor === true) {
        markUserContent(box);
        // בלי כותרת במסמך — השם שהשרת נתן לשלד (``EDITOR_EXPORT_DEFAULT_TITLE``) נשאר
        document.title = Core.firstHeadingTitle(box, document.title);
      }
      const fragment = document.createDocumentFragment();
      while (box.firstChild) fragment.appendChild(box.firstChild);
      const container = marker.parentNode;
      marker.replaceWith(fragment);
      if (status) status.remove();
      if (typeof window.ckAttachCopyButtons === 'function') window.ckAttachCopyButtons(container);
      document.documentElement.setAttribute('data-share-rendered', 'true');
      scrollToHash();
    } catch (err) {
      console.error('[styled-share] render failed', err);
      if (status) status.textContent = FAILED_MESSAGE;
      document.documentElement.setAttribute('data-share-rendered', 'failed');
    }
  }

  render();
})();
