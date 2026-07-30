/**
 * md-anchors.js — תמיכה בעוגני HTML מפורשים בתוך מסמכי Markdown.
 *
 * הבעיה שזה פותר: מסמכים רבים (בעיקר כאלה שנכתבו ל-GitHub) מגדירים עוגן לכותרת כך:
 *
 *     ## 1. תקשורת <a id="communication"></a>
 *
 * ואז מפנים אליו מתוכן העניינים: `[תקשורת](#communication)`.
 * ה-renderer שלנו רץ עם `html: false` (הגנת XSS על תוכן שמשתמשים מעלים), ולכן התגית
 * לא הופכת לאלמנט — היא נמחקת כתגית ומוצגת כטקסט זבל בתוך הכותרת, וגם מזהמת את ה-slug
 * האוטומטי. התוצאה: הקישור לא מוביל לשום מקום.
 *
 * הפתרון כאן שומר על `html: false`:
 *   1. לפני הרינדור — שולפים את העוגנים משורות הכותרות ומנקים אותם מהטקסט.
 *   2. אחרי הרינדור — מוסיפים אלמנט יעד בלתי-נראה לפני כל כותרת רלוונטית.
 *
 * הערה: אנחנו לא דורסים את ה-id של הכותרת עצמה — מזהי הכותרות משמשים לסימניות,
 * ודריסה הייתה שוברת סימניות קיימות.
 */
(function (root) {
  'use strict';

  // <a id="x"></a> / <a name='x'></a> / <a id=x></a> — גם עם רווחים ותכונות בסדר הפוך
  var ANCHOR_RE = /<a\s+[^>]*?(?:id|name)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))[^>]*>\s*<\/a\s*>/gi;

  // שורת כותרת ATX: עד 3 רווחי הזחה, 1-6 סולמיות, ואז רווח
  var HEADING_RE = /^\s{0,3}#{1,6}\s/;

  // גדר בלוק קוד: ``` או ~~~ (עם שפה אופציונלית)
  var FENCE_RE = /^\s{0,3}(`{3,}|~{3,})/;

  // קו תחתון של כותרת Setext: שורה שכולה "=" (h1) או "-" (h2)
  var SETEXT_UNDERLINE_RE = /^\s{0,3}(=+|-+)\s*$/;

  /**
   * האם השורה יכולה לשמש כטקסט של כותרת Setext (כלומר פסקה רגילה)?
   * הבידוק שמרני בכוונה: כל דבר שהוא בלוק אחר (רשימה, ציטוט, טבלה, קוד מוזח)
   * לא יוצר כותרת גם כשאחריו "---" — שם ה-"---" הוא קו מפריד (hr), לא כותרת.
   */
  function canBeSetextText(line) {
    if (!line || !line.trim()) return false;                       // שורה ריקה
    if (SETEXT_UNDERLINE_RE.test(line)) return false;              // קו תחתון בעצמה
    if (HEADING_RE.test(line)) return false;                       // כותרת ATX
    if (FENCE_RE.test(line)) return false;                         // גדר קוד
    if (/^\s{0,3}>/.test(line)) return false;                      // ציטוט
    if (/^\s{0,3}([-*+]|\d{1,9}[.)])\s/.test(line)) return false;  // פריט רשימה
    if (/^\s{4,}\S/.test(line)) return false;                      // בלוק קוד מוזח
    if (/^\s{0,3}\|/.test(line)) return false;                     // שורת טבלה
    return true;
  }

  /**
   * ניקוי מזהה עוגן. ה-id מוצב דרך element.id (DOM property) ולא דרך innerHTML,
   * ולכן אין וקטור הזרקה — הניקוי כאן נועד למנוע מזהים מוזרים/שבורים בלבד.
   */
  function sanitizeAnchorId(rawId) {
    if (!rawId) return '';
    var id = String(rawId).trim();
    // גרשיים מסולסלים נוצרים כש-typographer פעיל; מסירים גם אותם
    id = id.replace(/[\s<>"'“”‘’]/g, '');
    // "#intro" → "intro" (מסמכים לפעמים כוללים סולמית מיותרת)
    id = id.replace(/^#+/, '');
    return id;
  }

  /**
   * עיבוד מקדים של מקור ה-Markdown: שליפת עוגנים מפורשים והסרתם מהטקסט.
   *
   * @param {string} source מקור ה-Markdown הגולמי
   * @param {{setext?: boolean}} [options] setext=false אם ה-renderer מנטרל כותרות Setext
   *   (md.disable('lheading')). ברירת מחדל true — כמו ההתנהגות הרגילה של markdown-it.
   * @returns {{source: string, anchors: Array<{headingIndex: number, ids: string[]}>}}
   *   source — המקור אחרי ניקוי תגיות העוגן
   *   anchors — לכל כותרת (לפי סדר הופעתה, 0-based) רשימת המזהים שהוגדרו לה.
   *   חשוב: הספירה חייבת לכלול גם כותרות Setext, אחרת האינדקס לא יתאים לאלמנטי
   *   ה-h1..h6 בפועל והעוגן יוחל על הכותרת הלא נכונה.
   */
  function extractExplicitAnchors(source, options) {
    var text = (source == null) ? '' : String(source);
    var allowSetext = !(options && options.setext === false);
    if (!text || text.indexOf('<a') === -1) {
      return { source: text, anchors: [] };
    }

    var lines = text.split('\n');
    var outLines = [];
    var anchors = [];
    var headingIndex = -1;   // אינדקס הכותרת האחרונה שראינו
    var pendingIds = [];     // עוגנים שהופיעו בשורה נפרדת וממתינים לכותרת הבאה
    var fence = null;        // סוג הגדר הפתוחה (``` / ~~~) או null

    function pushAnchors(index, ids) {
      if (!ids.length) return;
      anchors.push({ headingIndex: index, ids: ids.slice() });
    }

    for (var i = 0; i < lines.length; i++) {
      var line = lines[i];

      // מעקב אחר בלוקי קוד — בתוכם לא נוגעים בכלום
      var fenceMatch = line.match(FENCE_RE);
      if (fenceMatch) {
        var marker = fenceMatch[1].charAt(0);
        if (fence === null) {
          fence = marker;
        } else if (fence === marker) {
          fence = null;
        }
        outLines.push(line);
        continue;
      }
      if (fence !== null) {
        outLines.push(line);
        continue;
      }

      // כותרת ATX (`## כותרת`) או כותרת Setext (שורת טקסט שאחריה === / ---).
      // חובה לזהות גם Setext: markdown-it מייצר עבורה h1/h2, ואם לא נספור אותה
      // האינדקסים יזוזו והעוגן יוחל על הכותרת הלא נכונה.
      var isHeading = HEADING_RE.test(line);
      if (!isHeading && allowSetext && canBeSetextText(line)) {
        var nextLine = (i + 1 < lines.length) ? lines[i + 1] : null;
        if (nextLine !== null && SETEXT_UNDERLINE_RE.test(nextLine)) {
          isHeading = true;
        }
      }

      // שורה שכולה עוגנים (הדפוס הקלאסי של GitHub: עוגן בשורה שלפני הכותרת)
      if (!isHeading) {
        var stripped = line.replace(ANCHOR_RE, '').trim();
        if (stripped === '' && line.trim() !== '') {
          ANCHOR_RE.lastIndex = 0;
          var m;
          while ((m = ANCHOR_RE.exec(line)) !== null) {
            var standaloneId = sanitizeAnchorId(m[1] || m[2] || m[3]);
            if (standaloneId) pendingIds.push(standaloneId);
          }
          // השורה מוסרת לגמרי (אחרת תוצג כטקסט זבל)
          continue;
        }
        outLines.push(line);
        continue;
      }

      // --- שורת כותרת ---
      headingIndex += 1;
      var idsForHeading = pendingIds.slice();
      pendingIds = [];

      ANCHOR_RE.lastIndex = 0;
      var hm;
      while ((hm = ANCHOR_RE.exec(line)) !== null) {
        var inlineId = sanitizeAnchorId(hm[1] || hm[2] || hm[3]);
        if (inlineId) idsForHeading.push(inlineId);
      }

      // ניקוי התגיות מטקסט הכותרת + צמצום רווחים כפולים שנוצרו
      var cleaned = line.replace(ANCHOR_RE, '').replace(/[ \t]{2,}/g, ' ').replace(/[ \t]+$/, '');
      outLines.push(cleaned);

      pushAnchors(headingIndex, idsForHeading);
    }

    // עוגנים שנשארו בלי כותרת אחריהם — משויכים לכותרת האחרונה (עדיף מלאבד אותם)
    if (pendingIds.length && headingIndex >= 0) {
      pushAnchors(headingIndex, pendingIds);
    }

    return { source: outLines.join('\n'), anchors: anchors };
  }

  /**
   * החלת העוגנים על ה-DOM אחרי הרינדור: לפני כל כותרת רלוונטית מוסיפים אלמנט יעד ריק.
   *
   * @param {Element} container אלמנט שמכיל את ה-HTML המרונדר
   * @param {Array} anchors הפלט של extractExplicitAnchors
   * @returns {number} כמה עוגנים הוחלו בפועל
   */
  function applyExplicitAnchors(container, anchors) {
    if (!container || !anchors || !anchors.length) return 0;
    var headings;
    try {
      headings = container.querySelectorAll('h1, h2, h3, h4, h5, h6');
    } catch (_) {
      return 0;
    }
    var applied = 0;
    for (var i = 0; i < anchors.length; i++) {
      var entry = anchors[i];
      var heading = headings[entry.headingIndex];
      if (!heading) continue;
      for (var j = 0; j < entry.ids.length; j++) {
        var id = entry.ids[j];
        if (!id) continue;
        // אם המזהה כבר תפוס (למשל ע"י כותרת אחרת) — לא דורסים
        var existing = null;
        try {
          existing = (heading.ownerDocument || document).getElementById(id);
        } catch (_) {
          existing = null;
        }
        if (existing) continue;
        var target = (heading.ownerDocument || document).createElement('span');
        target.className = 'md-explicit-anchor';
        target.id = id;  // DOM property — אין הזרקת HTML
        target.setAttribute('aria-hidden', 'true');
        if (heading.parentNode) {
          heading.parentNode.insertBefore(target, heading);
          applied += 1;
        }
      }
    }
    return applied;
  }

  /**
   * עיבוד מקדים + רינדור + החלת עוגנים, בקריאה אחת.
   * מיועד לשימוש בצרכנים (md_preview / live-preview) כדי לא לשכפל את הסדר.
   *
   * @param {string} source מקור Markdown
   * @param {function(string): string} renderFn פונקציית רינדור (md.render)
   * @param {Element} container היעד ב-DOM (ה-HTML יוזרק אליו)
   */
  function renderWithAnchors(source, renderFn, container, options) {
    var extracted = extractExplicitAnchors(source, options);
    var html = renderFn(extracted.source || '');
    if (container) {
      container.innerHTML = html;
      applyExplicitAnchors(container, extracted.anchors);
    }
    return html;
  }

  var api = {
    extractExplicitAnchors: extractExplicitAnchors,
    applyExplicitAnchors: applyExplicitAnchors,
    renderWithAnchors: renderWithAnchors,
    sanitizeAnchorId: sanitizeAnchorId,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;   // לבדיקות מ-Node
  }
  if (root) {
    root.MdAnchors = api;   // שימוש בדפדפן
  }
})(typeof window !== 'undefined' ? window : null);
