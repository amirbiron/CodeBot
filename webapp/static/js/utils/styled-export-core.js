/**
 * ייצוא ל-HTML מעוצב בדפדפן — מה שמשותף לעורך הציבורי (``markdown-editor-export.js``) ולחלון הייצוא של המחוברים
 * (``export-modal.js``). ``window.StyledExportCore``.
 *
 * הזרימה בשני המקומות זהה: המסמך מרונדר באותו מנוע כמו התצוגה החיה (``MarkdownLiveRenderer.renderForExport``
 * ב-``live-preview.js``), השרת מגיש "שלד" — העמוד המעוצב של הערכה עם הערת HTML במקום התוכן — והמסמך נכנס במקום
 * ההערה. רק אחרי הרינדור ידוע אם יש במסמך נוסחה, ולכן השלד מתבקש אחריו (עם ה-CSS של KaTeX או בלעדיו).
 *
 * - **תקרות זמן.** כל בקשה (``fetchText``) וטעינת המנוע (``loadEngine``) מוגבלות בזמן משלהן: הכפתורים מושבתים בזמן
 *   הבנייה, ובקשה שלא חוזרת לא יכולה להשאיר אותם מושבתים.
 * - **טעינת המנוע לפי דרישה** (``loadEngine``) — לעמוד שאינו טוען את התצוגה החיה מראש, כמו עמוד הקובץ. הסקריפטים
 *   יושבים כ-``<script>`` בתוך ``<template>`` (אותו ``_live_preview_scripts.html`` של עמודי העורך, בלי עותק שני של
 *   הרשימה), ושם הם אינם נטענים. בלחיצה הם נבנים מחדש כסקריפטים חיים, לפי הסדר.
 *
 * גם עמוד קישור השיתוף מרנדר דרך הקובץ הזה (``styled-share-view.js``).
 *
 * התיעוד: ``docs/webapp/markdown-editor.rst`` ו-``docs/webapp/styled-export.rst``.
 */
(function () {
  'use strict';

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

  // בקשה עם תקרת זמן. סטטוס שאינו 2xx זורק ``http_<סטטוס>`` (``describeError`` מתרגם אותו להודעה).
  async function fetchText(url, options) {
    const opts = options || {};
    const resp = await fetch(url, {
      method: opts.method || 'GET',
      body: opts.body,
      credentials: 'same-origin',
      signal: timeoutSignal(opts.timeoutMs),
    });
    if (!resp.ok) {
      throw new Error(`http_${resp.status}`);
    }
    return { text: await resp.text(), headers: resp.headers };
  }

  async function renderMarkdown(text, mermaidTheme) {
    if (!window.MarkdownLiveRenderer || typeof window.MarkdownLiveRenderer.renderForExport !== 'function') {
      throw new Error('renderer_missing');
    }
    return window.MarkdownLiveRenderer.renderForExport(text, { mermaidTheme: mermaidTheme || undefined });
  }

  function hasMath(box) {
    return !!box.querySelector('.katex');
  }

  // ההערה שהשלד מחזיק במקום התוכן. גם לעמוד של קישור השיתוף, שבו ההערה כבר בעמוד החי (``styled-share-view.js``).
  function findMarker(doc, markerText) {
    const walker = doc.createTreeWalker(doc.body, NodeFilter.SHOW_COMMENT);
    let node = walker.nextNode();
    while (node) {
      if (node.nodeValue === markerText) return node;
      node = walker.nextNode();
    }
    return null;
  }

  // הכותרת הראשונה במסמך, כטקסט — שם המסמך כשלקובץ אין שם משלו (העורך הציבורי).
  function firstHeadingTitle(box, fallback) {
    const heading = box.querySelector('h1, h2, h3, h4');
    const text = heading ? heading.textContent.replace(/\s+/g, ' ').trim() : '';
    return text || fallback;
  }

  // הקובץ השלם, כמחרוזת: השלד, עם המסמך במקום ההערה. ``title`` — שם המסמך, נכנס דרך ``document.title`` (טקסט, לא
  // HTML); בלעדיו נשאר ה-``<title>`` של השלד.
  function assemble(skeletonHtml, box, markerText, title) {
    const doc = new DOMParser().parseFromString(skeletonHtml, 'text/html');
    const marker = findMarker(doc, markerText);
    if (!marker) {
      throw new Error('skeleton_marker_missing');
    }
    const fragment = doc.createDocumentFragment();
    Array.from(box.childNodes).forEach((node) => fragment.appendChild(doc.importNode(node, true)));
    marker.replaceWith(fragment);
    if (title) doc.title = title;
    return `<!DOCTYPE html>\n${doc.documentElement.outerHTML}`;
  }

  function describeError(err) {
    const message = (err && err.message) || '';
    if (err && (err.name === 'TimeoutError' || err.name === 'AbortError' || message === 'engine_timeout')) {
      return 'השרת לא ענה בזמן. נסו שוב בעוד רגע.';
    }
    if (message === 'http_429') {
      return 'יותר מדי ייצואים בזמן קצר. נסו שוב מאוחר יותר.';
    }
    if (message === 'renderer_missing' || message === 'engine_load_failed') {
      return 'ספריית ה-Markdown לא נטענה, ולכן אי אפשר לייצא. נסו לרענן את העמוד.';
    }
    return 'הייצוא נכשל. נסו שוב.';
  }

  // "הצג": הטאב נפתח בתוך הלחיצה — דפדפן מתיר ``window.open`` רק זמן קצר אחרי פעולה של המשתמש ("transient
  // activation" בתקן של HTML), ורינדור של מסמך עם תרשימים יכול להימשך יותר — ומנותק מהעמוד לפני שנטען בו משהו.
  function openPreviewTab() {
    const win = window.open('', '_blank');
    if (win) win.opener = null;
    return win;
  }

  // מראה את הקובץ בטאב, או מוריד אותו. הכתובת של הטאב לא משתחררת: רענון של הטאב טוען אותה שוב, וכתובת ששוחררה
  // הייתה מחזירה שגיאה. הדפדפן משחרר אותה כשהעמוד הזה נסגר.
  function deliver(html, previewWindow, filename) {
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    if (previewWindow) {
      previewWindow.location.href = URL.createObjectURL(blob);
    } else {
      window.EditorPageUtils.downloadBlob(blob, filename);
    }
  }

  // --- טעינת המנוע לפי דרישה ---------------------------------------------------------------------------------
  // הערך המשותף הוא ההבטחה עצמה, והיא גם השומר: לחיצה שנייה בזמן טעינה מקבלת את אותה הבטחה, וכשל מאפס אותה כדי
  // שלחיצה הבאה תנסה שוב — ולא תיזכר ככישלון עד רענון.
  let enginePromise = null;
  // הבטחה לכל סקריפט: ניסיון חוזר (אחרי תקרת זמן או כשל) משתמש במה שכבר נטען או עדיין נטען, ובונה מחדש רק את מה
  // שנכשל — בלי להריץ את הבאנדל פעמיים
  const scriptPromises = new Map();

  function loadScript(src) {
    if (scriptPromises.has(src)) return scriptPromises.get(src);
    const promise = new Promise((resolve, reject) => {
      const el = document.createElement('script');
      el.src = src;
      // סקריפט שנוסף מקוד הוא async כברירת מחדל; כאן הוא נטען אחרי שהקודם הסתיים, ולכן הסדר נשמר בכל מקרה
      el.async = false;
      el.onload = () => resolve();
      el.onerror = () => {
        scriptPromises.delete(src);
        el.remove();
        reject(new Error('engine_load_failed'));
      };
      document.head.appendChild(el);
    });
    scriptPromises.set(src, promise);
    return promise;
  }

  function loadEngine(templateEl, timeoutMs) {
    if (window.MarkdownLiveRenderer && typeof window.MarkdownLiveRenderer.renderForExport === 'function') {
      return Promise.resolve();
    }
    if (enginePromise) return enginePromise;
    const sources = templateEl
      ? Array.from(templateEl.content.querySelectorAll('script[src]')).map((s) => s.getAttribute('src'))
      : [];
    if (!sources.length) {
      return Promise.reject(new Error('engine_load_failed'));
    }
    const load = sources.reduce((chain, src) => chain.then(() => loadScript(src)), Promise.resolve());
    // תקרה אחת על הטעינה כולה, לא לכל סקריפט: עשרה סקריפטים איטיים עוברים כל תקרה לסקריפט אחד
    const deadline = new Promise((_resolve, reject) => {
      setTimeout(() => reject(new Error('engine_timeout')), timeoutMs);
    });
    enginePromise = Promise.race([load, deadline]).catch((err) => {
      enginePromise = null;
      throw err;
    });
    return enginePromise;
  }

  window.StyledExportCore = {
    timeoutSignal,
    fetchText,
    renderMarkdown,
    hasMath,
    findMarker,
    firstHeadingTitle,
    assemble,
    describeError,
    openPreviewTab,
    deliver,
    loadEngine,
  };
})();
