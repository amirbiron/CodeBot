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

  // בקשה עם תקרת זמן. סטטוס שאינו 2xx זורק ``http_<סטטוס>`` (``describeError`` מתרגם אותו להודעה), עם ``status`` ועם
  // גוף התשובה ב-``bodyText`` — לקורא שמבחין בין סירובים עם אותו סטטוס ("צור קישור" בעורך הציבורי: 429 של מגבלת הקצב
  // מול 429 של התקרה היומית).
  async function fetchText(url, options) {
    const opts = options || {};
    const resp = await fetch(url, {
      method: opts.method || 'GET',
      headers: opts.headers,
      body: opts.body,
      credentials: 'same-origin',
      signal: timeoutSignal(opts.timeoutMs),
    });
    if (!resp.ok) {
      const err = new Error(`http_${resp.status}`);
      err.status = resp.status;
      try {
        err.bodyText = await resp.text();
      } catch (_readErr) {
        // הגוף רק מפרט את הסיבה; בלעדיו הקורא נשען על הסטטוס, שכבר בשגיאה
        err.bodyText = '';
      }
      throw err;
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
  // רשומה לכל סקריפט — ההבטחה, האלמנט, והאם הוא כבר נטען. ניסיון חוזר משתמש בסקריפט שכבר נטען (בלי להריץ אותו
  // שוב), ובונה מחדש סקריפט שנכשל או שננטש בתקרת הזמן (``abandonPending``).
  const scripts = new Map();
  // כמה פעמים כל סקריפט ננטש בתקרת הזמן. ניסיון אחרי נטישה מבקש כתובת אחרת (``retry=N``): Chromium מצמיד אלמנט חדש
  // לבקשה שעוד פתוחה לאותה כתובת, ואז גם הניסיון החדש מחכה לבקשה התקועה (נמדד ב-Chromium 153: בלי הפרמטר יצאה בקשה
  // אחת לשני הניסיונות). הנתיב הסטטי מתעלם מהפרמטר.
  const abandoned = new Map();

  function forgetScript(src, entry) {
    if (scripts.get(src) === entry) scripts.delete(src);
    entry.el.remove();
  }

  function scriptUrl(src) {
    const retry = abandoned.get(src);
    return retry ? `${src}${src.includes('?') ? '&' : '?'}retry=${retry}` : src;
  }

  function loadScript(src) {
    const known = scripts.get(src);
    if (known) return known.promise;
    const entry = { el: document.createElement('script'), loaded: false, promise: null };
    entry.promise = new Promise((resolve, reject) => {
      entry.el.src = scriptUrl(src);
      // ``async`` (ברירת המחדל לסקריפט שנוסף מקוד), ולא ``async = false``: הסדר נשמר בכל מקרה, כי כל סקריפט נוסף רק
      // אחרי שהקודם נטען. ו-``async = false`` מכניס את הסקריפט לתור של "לפי סדר ההוספה", שבו הוא מחכה לכל מי שנוסף
      // לפניו — גם לסקריפט שננטש בבקשה תקועה, ושהסרה מהעמוד אינה מוציאה מהתור (נמדד: הניסיון החדש נתקע מאחוריו).
      entry.el.async = true;
      entry.el.onload = () => {
        entry.loaded = true;
        resolve();
      };
      entry.el.onerror = () => {
        forgetScript(src, entry);
        reject(new Error('engine_load_failed'));
      };
      document.head.appendChild(entry.el);
    });
    scripts.set(src, entry);
    return entry.promise;
  }

  // בתקרת הזמן: סקריפט שעוד לא נטען — בקשה תקועה, חיבור שנפל באמצע — יוצא מהרשימה, כדי שהניסיון הבא יבקש אותו מחדש.
  // בלי זה כל ניסיון היה מחכה לאותה בקשה תקועה, ונכשל שוב, עד רענון העמוד. אי אפשר לבטל בקשה של אלמנט סקריפט, ולכן
  // אם הבקשה הישנה תסתיים בכל זאת, הסקריפט ירוץ פעם נוספת; ``test_a_hung_engine_script_is_requested_again`` מראה
  // שהייצוא עובד גם אחרי ריצה כזו.
  function abandonPending() {
    scripts.forEach((entry, src) => {
      if (entry.loaded) return;
      forgetScript(src, entry);
      abandoned.set(src, (abandoned.get(src) || 0) + 1);
    });
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
    let timer = null;
    const deadline = new Promise((_resolve, reject) => {
      timer = setTimeout(() => {
        abandonPending();
        reject(new Error('engine_timeout'));
      }, timeoutMs);
    });
    // התקרה מבוטלת כשהטעינה מסתיימת, בכל דרך, כדי שתקרה של ניסיון קודם (שנכשל מהר) לא תרוץ באמצע ניסיון חדש ותוציא
    // מהרשומות סקריפטים שלו. זה סדר, לא תיקון של תקלה שנראית: הניסיון החדש היה מסתיים גם כך
    enginePromise = Promise.race([load, deadline])
      .finally(() => clearTimeout(timer))
      .catch((err) => {
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
