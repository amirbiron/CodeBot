/**
 * הדגשת תחביר בטוחה לבלוקי קוד – מונעת זיהוי שגוי כ-diff.
 * משותף ל-live-preview, repo-browser, snippets ו-md_preview.
 *
 * כש-highlight.js מפעיל highlightAuto על בלוק ללא שפה מוגדרת,
 * שורות שמתחילות ב-מקף ("-") מזוהות בטעות כ-diff ונצבעות באדום.
 * פונקציה זו עוטפת את הלוגיקה ומדלגת על זיהוי diff אוטומטי,
 * תוך שימור language class ו-data-highlighted guard.
 */
(function () {
  'use strict';

  /**
   * מדגיש בלוק קוד בודד באופן בטוח.
   * - אם יש language class מפורש: משתמש ב-highlightElement כרגיל.
   * - אם אין: מפעיל highlightAuto, מדלג על diff, מוסיף language class
   *   ומסמן data-highlighted למניעת עיבוד כפול.
   *
   * @param {HTMLElement} block  אלמנט <code> בתוך <pre>
   */
  function highlightBlock(block) {
    if (!block || !window.hljs) return;
    if (block.dataset && block.dataset.highlighted === 'yes') return;

    var hasExplicitLang = /\blanguage-/.test(block.className || '');
    if (hasExplicitLang) {
      window.hljs.highlightElement(block);
    } else {
      var result = window.hljs.highlightAuto(block.textContent || '');
      if (result.language !== 'diff') {
        block.innerHTML = result.value;
        if (result.language) block.classList.add('language-' + result.language);
      }
      block.classList.add('hljs');
      block.dataset.highlighted = 'yes';
    }
  }

  /**
   * מדגיש את כל בלוקי pre>code בתוך root.
   *
   * @param {HTMLElement} root  אלמנט שורש לחיפוש בלוקי קוד
   */
  function highlightAllBlocks(root) {
    if (!root || !window.hljs) return;
    root.querySelectorAll('pre code').forEach(function (block) {
      try {
        highlightBlock(block);
      } catch (err) {
        console.warn('safe-highlight failed', err);
      }
    });
  }

  /**
   * פונקציית highlight callback ל-markdown-it.
   * מדלגת על זיהוי אוטומטי של diff.
   *
   * @param {string} str   תוכן בלוק הקוד
   * @param {string} lang  שפה שצוינה (או ריק)
   * @returns {string}     HTML מודגש, או '' ל-fallback
   */
  function markdownItHighlight(str, lang) {
    if (!window.hljs) return '';
    if (lang) {
      try {
        if (window.hljs.getLanguage(lang)) {
          return window.hljs.highlight(str, { language: lang }).value;
        }
      } catch (_) {}
    }
    try {
      var result = window.hljs.highlightAuto(str);
      if (result.language === 'diff') return '';
      return result.value;
    } catch (_) {}
    return '';
  }

  if (typeof window !== 'undefined') {
    window.SafeHighlight = {
      highlightBlock: highlightBlock,
      highlightAllBlocks: highlightAllBlocks,
      markdownItHighlight: markdownItHighlight
    };
  }
})();
