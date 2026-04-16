/**
 * הדגשת תחביר בטוחה לבלוקי קוד – מונעת זיהוי שגוי כ-diff.
 * משותף ל-live-preview, repo-browser, snippets ו-md_preview.
 *
 * כש-highlight.js מפעיל highlightAuto על בלוק ללא שפה מוגדרת,
 * שורות שמתחילות ב-מקף ("-") מזוהות בטעות כ-diff ונצבעות באדום.
 *
 * הפתרון: patch גלובלי ל-hljs.highlightAuto שמדלג על זיהוי diff אוטומטי.
 * זה מכסה את כל נתיבי ההדגשה, כולל קריאות פנימיות מ-hljs.highlightElement.
 * שפת diff מפורשת (```diff) עדיין עובדת כי היא עוברת דרך hljs.highlight ולא highlightAuto.
 */
(function () {
  'use strict';

  // ─── Patch גלובלי ל-highlightAuto: מדלג על זיהוי diff אוטומטי ───
  // חוסם את diff רק בזיהוי אוטומטי. שפה מפורשת (language-diff) לא מושפעת
  // כי highlightElement קורא ל-hljs.highlight(code, {language}) ישירות.
  function patchHighlightAuto() {
    if (!window.hljs || !window.hljs.highlightAuto) return;
    if (window.hljs._safeHighlightPatched) return; // כבר הוחל

    var original = window.hljs.highlightAuto;
    window.hljs.highlightAuto = function (code, languageSubset) {
      var result = original.call(this, code, languageSubset);
      if (result && result.language === 'diff') {
        // מחזיר תוצאה ריקה – בלי הדגשת diff
        return {
          language: '',
          relevance: 0,
          value: window.hljs.getLanguage ? code : result.value,
          secondBest: result.secondBest,
          _emitError: result._emitError
        };
      }
      return result;
    };
    window.hljs._safeHighlightPatched = true;
  }

  // מחיל את ה-patch מיד אם hljs כבר טעון, ומאזין לטעינה עתידית
  patchHighlightAuto();
  if (typeof document !== 'undefined') {
    // אם hljs נטען דינמית אחרי safe-highlight (למשל מ-CDN או bundle),
    // נבדוק שוב אחרי DOMContentLoaded ובכל טעינת סקריפט
    var observer = null;
    function tryPatch() {
      if (window.hljs && !window.hljs._safeHighlightPatched) {
        patchHighlightAuto();
        if (observer) { observer.disconnect(); observer = null; }
      }
    }
    if (!window.hljs || !window.hljs._safeHighlightPatched) {
      document.addEventListener('DOMContentLoaded', tryPatch);
      // MutationObserver שעוקב אחרי הוספת script tags (טעינת CDN/bundle)
      try {
        observer = new MutationObserver(function (mutations) {
          for (var i = 0; i < mutations.length; i++) {
            var nodes = mutations[i].addedNodes;
            for (var j = 0; j < nodes.length; j++) {
              if (nodes[j].tagName === 'SCRIPT') {
                // ממתין מעט לאחר טעינת הסקריפט כדי ש-hljs יהיה זמין
                setTimeout(tryPatch, 50);
                setTimeout(tryPatch, 200);
                return;
              }
            }
          }
        });
        observer.observe(document.documentElement, { childList: true, subtree: true });
      } catch (_) {}
    }
  }

  // ─── פונקציות עזר (נשארות לתאימות אחורה) ───

  /**
   * מדגיש בלוק קוד בודד באופן בטוח.
   */
  function highlightBlock(block) {
    if (!block || !window.hljs) return;
    if (block.dataset && block.dataset.highlighted === 'yes') return;

    var hasExplicitLang = /\blanguage-/.test(block.className || '');
    if (hasExplicitLang) {
      window.hljs.highlightElement(block);
    } else {
      var result = window.hljs.highlightAuto(block.textContent || '');
      if (result.language) {
        block.innerHTML = result.value;
        block.classList.add('language-' + result.language);
      }
      block.classList.add('hljs');
      block.dataset.highlighted = 'yes';
    }
  }

  /**
   * מדגיש את כל בלוקי pre>code בתוך root.
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
      if (!result.language) return '';
      return result.value;
    } catch (_) {}
    return '';
  }

  if (typeof window !== 'undefined') {
    window.SafeHighlight = {
      highlightBlock: highlightBlock,
      highlightAllBlocks: highlightAllBlocks,
      markdownItHighlight: markdownItHighlight,
      patchHighlightAuto: patchHighlightAuto
    };
  }
})();
