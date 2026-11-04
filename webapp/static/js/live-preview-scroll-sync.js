/**
 * live-preview-scroll-sync.js — גלילה מסונכרנת בין העורך לתצוגה החיה (Split View): גוללים צד אחד, והצד השני מגיע
 * לאותו מקום בטקסט. ``LivePreviewController`` ב-``live-preview.js`` מחבר אותו, בעורך הציבורי (``/markdown-editor``)
 * ובעמודי העריכה וההעלאה.
 *
 * **ההתאמה היא לפי שורות, לא לפי אחוזים.** בגלילה של ``/compare/paste`` ושל השוואת הקומיטים כל צד זז באותו אחוז
 * מהגובה שלו — שם זה עובד, כי שני הצדדים בנויים מאותן שורות. ב-Markdown לא: כמה שורות של תרשים הן תרשים גבוה
 * בתצוגה, ותמונה היא שורה אחת בעורך ושטח גדול בתצוגה, ולכן אחוז זהה מראה בכל צד מקום אחר בטקסט. כאן כל בלוק בתצוגה מסומן
 * בשורות המקור שלו (``data-source-line`` / ``data-source-line-end``, מ-``md-source-lines-plugin.js``), ומהסימונים
 * נבנות **נקודות התאמה**: ראש הבלוק מול השורה הראשונה שלו, ותחתית הבלוק מול השורה שאחרי האחרונה. בין שתי נקודות
 * המיקום מחושב לפי היחס ביניהן — בתוך בלוק, ובין בלוק לבלוק. בעורך, CodeMirror יודע את הגובה של כל שורה גם כשהיא
 * נשברת לכמה שורות מסך (``lineBlockAt`` / ``lineBlockAtHeight``).
 *
 * **נקודת הקריאה זזה לפי המיקום במסמך.** הנקודה שמותאמת בין הצדדים היא בראש החלון כשהגלילה בהתחלה, בתחתית החלון
 * כשהגלילה בסוף, ובאמצע — לפי היחס (``readingY``). אילו הותאם תמיד ראש החלון, כשהעורך מגיע לסוף התצוגה עדיין לא
 * הייתה שם (או להפך), והסוף של אחד הצדדים לא היה נראה. כך ההתחלה והסוף מתיישרים תמיד.
 *
 * **מי מוביל.** הצד שהמשתמש עשה בו משהו אחרון — גלגלת, מגע, לחיצה (גם על פס הגלילה), מקלדת או פוקוס (``INTENT_EVENTS``).
 * רק גלילה של הצד המוביל מזיזה את השני. הגלילה שהמנוע עושה בצד השני, וגלילות שהדפדפן או CodeMirror עושים
 * בעצמם, לא חוזרות לצד הראשון כהד. אחרי כל רינדור של התצוגה (``contentRendered``) הצדדים מתיישרים מחדש לפי הצד
 * המוביל — בהקלדה זה העורך, ולכן התצוגה מראה את מה שכותבים. **ובזמן רינדור אין סנכרון:** מהרגע שהתוכן בתצוגה מוחלף
 * ועד שהתרשימים במקומם (``contentCleared`` ואז ``contentRendered``), הצד השני מחכה, ואז זז פעם אחת. עד שזה תוקן
 * הוא זז באמצע לפי הגבהים של תרשימים שעוד לא צוירו, ואחר כך קפץ שוב (נמדד ב-4.11.2026: 95px,
 * ``test_a_scroll_while_the_preview_renders_waits_for_the_render``).
 *
 * **מתי אין סנכרון.** בעורך הפשוט (textarea) — החלטת המשתמש, נובמבר 2026; ``getEditorView`` מחזיר את העורך רק
 * כש-CodeMirror פעיל. כשאחד הצדדים מוסתר (בטלפון רואים פאנל אחד בכל פעם) — ובמעבר בין הלשוניות אין קפיצה, גם זה
 * לפי החלטת המשתמש. וכשבתצוגה אין סימוני שורות: תצוגה של HTML, ורינדור מהשרת (``contentCleared``). שם אין סנכרון
 * בכלל, ולא גלילה לפי אחוזים במקומו, שהייתה נותנת התאמה שגויה שנראית תקינה.
 *
 * הפונקציות שבחלק העליון (``buildPoints`` ועד ``scrollTopForReadingY``) הן חשבון בלבד, בלי DOM, ונבדקות מ-Node
 * (``tests/live-preview-scroll-sync.test.js``). ההתנהגות בדפדפן נבדקת ב-``tests/test_markdown_editor_browser.py``
 * וב-``tests/test_edit_page_frame_browser.py``.
 */
(function (root) {
  'use strict';

  // ---------------------------------------------------------------------------------------------------------------
  // חשבון: נקודות התאמה בין שורה (0-based, עם שבר בתוך השורה) לגובה (פיקסלים מראש התוכן של הגולל).
  // ---------------------------------------------------------------------------------------------------------------

  /**
   * הנקודות ``{line, y}`` מהבלוקים שנמדדו בתצוגה, ממוינות לפי השורה וגם לפי הגובה, ובכל שורה נקודה אחת.
   *
   * ``entries`` — ``{start, end, top, bottom}`` לכל בלוק: שורת ההתחלה, השורה שאחרי האחרונה, וראש הבלוק ותחתיתו.
   *
   * **השוליים שלפני השורה הראשונה ואחרי האחרונה.** בשני הצדדים יש ריפוד לפני הטקסט ואחריו, והוא אינו אף שורה.
   * לכן הוא מקבל "שורות" משלו: ``-1`` היא ראש הגולל, ו-``lineCount + 1`` היא הסוף שלו (``contentHeight``). כך ראש
   * הגולל בצד אחד מתאים לראש הגולל בצד השני, והסוף לסוף — ולא לשורה הראשונה, שבתצוגה יושבת מתחת לריפוד. העורך
   * משתמש באותן שורות לריפוד שלו (``editorSide``).
   *
   * **בכל שורה נקודה אחת — הגבוהה.** כששני בלוקים צמודים בלי שורה ריקה ביניהם (כותרת ומיד אחריה כותרת), התחתית
   * של הראשון והראש של השני נופלים על אותה שורה. שתי הנקודות היו יוצרות קפיצה: גלילה של פחות מפיקסל בעורך הייתה
   * מזיזה את התצוגה בגובה המרווח שבין הבלוקים (נמדד: 20px בטקסט ההדגמה). נשארת נקודת הראש, והמרווח מתחלק על
   * השורות של הבלוק הראשון.
   *
   * **נקודה שסותרת את השאר נזרקת.** בלוק שהמיקום שלו בתצוגה אינו לפי הסדר במקור — הערת שוליים, למשל, מוצגת בסוף
   * המסמך אבל כתובה באמצע — היה הופך את ההתאמה ללא מונוטונית. נשארת הסדרה הארוכה ביותר של נקודות שהגובה בה לא
   * יורד (``longestNonDecreasing``), כלומר הנקודות שמסכימות זו עם זו.
   */
  function buildPoints(entries, lineCount, contentHeight) {
    var points = [{ line: -1, y: 0 }];
    (entries || []).forEach(function (entry) {
      if (!entry) return;
      var start = entry.start;
      var end = entry.end;
      var top = entry.top;
      var bottom = entry.bottom;
      if (!isFinite(start) || !isFinite(top) || !isFinite(bottom) || start < 0 || bottom < top) return;
      if (!isFinite(end) || end <= start) end = start + 1;
      points.push({ line: start, y: top });
      points.push({ line: end, y: bottom });
    });
    if (isFinite(lineCount) && lineCount >= 0 && isFinite(contentHeight) && contentHeight >= 0) {
      points.push({ line: lineCount + 1, y: contentHeight });
    }
    points.sort(function (a, b) { return (a.line - b.line) || (a.y - b.y); });
    var kept = longestNonDecreasing(points);
    // ממוינות לפי (שורה, גובה), ולכן האחרונה בכל שורה היא הגבוהה.
    return kept.filter(function (p, i) {
      return i === kept.length - 1 || kept[i + 1].line !== p.line;
    });
  }

  /** הסדרה הארוכה ביותר שבה ``y`` לא יורד, מתוך נקודות שכבר ממוינות לפי ``line``. O(n log n). */
  function longestNonDecreasing(points) {
    var tails = [];
    var prev = new Array(points.length);
    for (var i = 0; i < points.length; i += 1) {
      var y = points[i].y;
      var lo = 0;
      var hi = tails.length;
      while (lo < hi) {
        var mid = (lo + hi) >> 1;
        if (points[tails[mid]].y <= y) lo = mid + 1;
        else hi = mid;
      }
      prev[i] = lo > 0 ? tails[lo - 1] : -1;
      tails[lo] = i;
    }
    var out = [];
    var k = tails.length ? tails[tails.length - 1] : -1;
    while (k >= 0) {
      out.push(points[k]);
      k = prev[k];
    }
    return out.reverse();
  }

  /** האינדקס האחרון שבו ``key(points[i]) <= value``, או ``-1``. */
  function lastAtOrBefore(points, value, key) {
    var lo = 0;
    var hi = points.length;
    while (lo < hi) {
      var mid = (lo + hi) >> 1;
      if (key(points[mid]) <= value) lo = mid + 1;
      else hi = mid;
    }
    return lo - 1;
  }

  function byLine(p) { return p.line; }
  function byY(p) { return p.y; }

  /** הגובה של שורה (עם שבר), לפי היחס בין שתי הנקודות שמשני צדיה. */
  function lineToY(points, line) {
    if (!points || !points.length) return null;
    var i = lastAtOrBefore(points, line, byLine);
    if (i < 0) return points[0].y;
    if (i >= points.length - 1) return points[points.length - 1].y;
    var a = points[i];
    var b = points[i + 1];
    var t = (line - a.line) / (b.line - a.line);
    return a.y + t * (b.y - a.y);
  }

  /** ההפך של ``lineToY``: השורה (עם שבר) בגובה נתון. */
  function yToLine(points, y) {
    if (!points || !points.length) return null;
    var i = lastAtOrBefore(points, y, byY);
    if (i < 0) return points[0].line;
    if (i >= points.length - 1) return points[points.length - 1].line;
    var a = points[i];
    var b = points[i + 1];
    var t = (y - a.y) / (b.y - a.y);
    return a.line + t * (b.line - a.line);
  }

  /** הגלילה המקסימלית. ``Math.max(0, …)``: תוכן קצר מהחלון אינו נותן גבול שלילי. */
  function maxScrollOf(scrollHeight, clientHeight) {
    return Math.max(0, scrollHeight - clientHeight);
  }

  /** נקודת הקריאה, בפיקסלים מראש התוכן: ראש החלון בהתחלה, התחתית בסוף, ובאמצע — לפי היחס. */
  function readingY(scrollTop, maxScroll, scrollHeight) {
    if (!(maxScroll > 0)) return 0;
    var ratio = Math.min(1, Math.max(0, scrollTop / maxScroll));
    return ratio * scrollHeight;
  }

  /** ההפך של ``readingY``: הגלילה שבה נקודת הקריאה נמצאת בגובה ``y``, בתוך גבולות הגלילה. */
  function scrollTopForReadingY(y, maxScroll, scrollHeight) {
    if (!(maxScroll > 0) || !(scrollHeight > 0)) return 0;
    return Math.min(maxScroll, Math.max(0, (y * maxScroll) / scrollHeight));
  }

  // ---------------------------------------------------------------------------------------------------------------
  // שני הצדדים: העורך (CodeMirror) והתצוגה.
  // ---------------------------------------------------------------------------------------------------------------

  /**
   * CodeMirror 6. המיקומים לפי ``@codemirror/view`` (נבדק בגרסה 6.38.6, וזה גם הקוד שבחבילה ``codemirror.local.js``):
   * ``documentTop`` הוא ראש השורה הראשונה בקואורדינטות המסך (``contentDOM`` ועוד הריפוד העליון), ו-``lineBlockAt`` /
   * ``lineBlockAtHeight`` מחזירים ``{from, to, top, height}`` ביחס אליו. בלוק הוא שורה אחת, או כמה כשקטע מקופל.
   *
   * הגבהים בפיקסלים מראש התוכן של הגולל. הריפוד שלפני השורה הראשונה הוא השורות ``-1`` עד ``0``, והריפוד שאחרי
   * האחרונה — ``doc.lines`` עד ``doc.lines + 1``, כמו בנקודות של התצוגה (``buildPoints``).
   */
  function editorSide(view) {
    var scroller = view.scrollDOM;
    var doc = view.state.doc;
    // ראש המסמך, בפיקסלים מראש התוכן של הגולל — מה שמתרגם בין הגובה במסמך לבין scrollTop.
    var docOffset = view.documentTop - scroller.getBoundingClientRect().top - scroller.clientTop + scroller.scrollTop;
    var docEnd = docOffset + view.lineBlockAt(doc.length).bottom;
    var tail = Math.max(0, scroller.scrollHeight - docEnd);

    function blockLines(block) {
      var first = doc.lineAt(block.from).number - 1;
      var last = doc.lineAt(block.to).number;
      return { first: first, last: Math.max(first + 1, last) };
    }

    return {
      lineAtY: function (y) {
        if (y < docOffset) return docOffset > 0 ? -1 + Math.max(0, y) / docOffset : 0;
        if (y >= docEnd) return doc.lines + (tail > 0 ? Math.min(1, (y - docEnd) / tail) : 0);
        var docY = y - docOffset;
        var block = view.lineBlockAtHeight(docY);
        var lines = blockLines(block);
        var t = block.height > 0 ? Math.min(1, Math.max(0, (docY - block.top) / block.height)) : 0;
        return lines.first + t * (lines.last - lines.first);
      },
      yAtLine: function (line) {
        if (line < 0) return docOffset * Math.max(0, line + 1);
        if (line >= doc.lines) return docEnd + tail * Math.min(1, line - doc.lines);
        var block = view.lineBlockAt(doc.line(Math.floor(line) + 1).from);
        var lines = blockLines(block);
        var t = Math.min(1, Math.max(0, (line - lines.first) / (lines.last - lines.first)));
        return docOffset + block.top + t * block.height;
      },
    };
  }

  /** הבלוקים המסומנים שבתצוגה, כ-``entries`` של ``buildPoints``. בלוק שאינו מוצג — בתוך "קיפול" סגור, או מוסתר — לא נכנס. */
  function measurePreview(canvas) {
    var canvasRect = canvas.getBoundingClientRect();
    var originTop = canvasRect.top + canvas.clientTop - canvas.scrollTop;
    var entries = [];
    var nodes = canvas.querySelectorAll('[data-source-line]');
    for (var i = 0; i < nodes.length; i += 1) {
      var el = nodes[i];
      // תוכן של ``<details>`` סגור: רק מה שבתוך ה-``summary`` מוצג. נבדק כאן במפורש ולא דרך הגודל של האלמנט, כדי לא
      // להישען על האופן שבו הדפדפן מסתיר את התוכן. ה-``<details>`` עצמו נמדד — הוא בגובה ה-``summary`` שלו — ולכן
      // מחפשים קיפול סגור רק מעל האלמנט.
      var closed = el.parentElement ? el.parentElement.closest('details:not([open])') : null;
      if (closed) {
        var summary = closed.querySelector('summary');
        if (!summary || !summary.contains(el)) continue;
      }
      if (!el.getClientRects().length) continue;
      var rect = el.getBoundingClientRect();
      var start = Number(el.getAttribute('data-source-line'));
      var end = Number(el.getAttribute('data-source-line-end'));
      entries.push({ start: start, end: end, top: rect.top - originTop, bottom: rect.bottom - originTop });
    }
    return entries;
  }

  // ---------------------------------------------------------------------------------------------------------------
  // החיבור לעמוד.
  // ---------------------------------------------------------------------------------------------------------------

  /** האירועים שמסמנים שהמשתמש עובד בצד מסוים, ולכן הוא המוביל. ``focusin`` — גם כפתורי הסרגל, שמעבירים פוקוס לעורך. */
  var INTENT_EVENTS = ['wheel', 'touchstart', 'pointerdown', 'keydown', 'focusin'];

  /** כמה פעמים לכל היותר מיישרים שוב את העורך אחרי שגללנו אותו (ראו ``settleEditor``). */
  var MAX_EDITOR_SETTLE_PASSES = 3;

  /**
   * מחבר את הסנכרון לעמוד.
   *
   * - ``editorPanel`` / ``previewPanel`` — הפאנלים, שבהם מזהים איזה צד מוביל.
   * - ``canvas`` — הגולל של התצוגה (``[data-preview-canvas]``).
   * - ``getEditorView`` — ה-``EditorView`` של CodeMirror כשהוא העורך הפעיל, אחרת ``null``.
   *
   * מחזיר ``contentRendered(lineCount)`` — לקרוא אחרי כל רינדור של Markdown בדפדפן, עם מספר השורות של הטקסט
   * שרונדר — ו-``contentCleared()``: כשבתצוגה אין עכשיו תוכן מסומן, **וגם לפני שרינדור מחליף את התוכן**. הרינדור
   * בדפדפן מחליף את ה-canvas ואחר כך מחכה לתרשימים (``enhance``), ובחלון הזה הבלוקים, הגבהים ומספר השורות כבר
   * אינם של הרינדור הקודם — ונקודות ההתאמה שבמטמון עלולות להישאר בתוקף, כשהגובה הכולל במקרה לא השתנה. בין שתי
   * הקריאות אין סנכרון, ו-``contentRendered`` מיישר את הצד השני לפי הצד המוביל.
   */
  function attach(options) {
    var editorPanel = options.editorPanel;
    var previewPanel = options.previewPanel;
    var canvas = options.canvas;
    var getEditorView = options.getEditorView;

    var leader = null;
    var rendered = false;
    var lineCount = 0;
    var version = 0;
    var cache = null;
    var frame = 0;
    var pendingSide = null;

    function previewPoints() {
      var key = version + ':' + canvas.scrollHeight + ':' + canvas.clientWidth;
      if (cache && cache.key === key) return cache.points;
      var entries = measurePreview(canvas);
      var points = entries.length ? buildPoints(entries, lineCount, canvas.scrollHeight) : null;
      cache = { key: key, points: points };
      return points;
    }

    /** מזיז את הצד שאינו ``side`` למקום שמתאים לצד ``side``. מחזיר ``true`` כשהעורך נגלל. */
    function syncFrom(side) {
      if (!rendered) return false;
      var view = getEditorView();
      if (!view || !view.scrollDOM) return false;
      var scroller = view.scrollDOM;
      if (!scroller.clientHeight || !canvas.clientHeight) return false;
      var points = previewPoints();
      if (!points) return false;
      var editor = editorSide(view);
      var editorMax = maxScrollOf(scroller.scrollHeight, scroller.clientHeight);
      var previewMax = maxScrollOf(canvas.scrollHeight, canvas.clientHeight);
      if (side === 'editor') {
        var line = editor.lineAtY(readingY(scroller.scrollTop, editorMax, scroller.scrollHeight));
        var previewTarget = scrollTopForReadingY(lineToY(points, line), previewMax, canvas.scrollHeight);
        if (Math.abs(canvas.scrollTop - previewTarget) >= 1) canvas.scrollTop = previewTarget;
        return false;
      }
      var sourceLine = yToLine(points, readingY(canvas.scrollTop, previewMax, canvas.scrollHeight));
      var editorTarget = scrollTopForReadingY(editor.yAtLine(sourceLine), editorMax, scroller.scrollHeight);
      if (Math.abs(scroller.scrollTop - editorTarget) < 1) return false;
      scroller.scrollTop = editorTarget;
      return true;
    }

    /**
     * אחרי שגללנו את העורך, CodeMirror מודד את השורות שנכנסו לחלון במקום הגובה המשוער שלהן, ומזיז את ``scrollTop``
     * כדי שהשורה שבראש החלון תישאר במקומה (``measure`` ב-``@codemirror/view``). השורה שבנקודת הקריאה יכולה לזוז
     * מעט, ולכן מיישרים שוב — אחרי שתי מסגרות, כשהמדידה שלו כבר רצה — עד שאין מה לתקן, ולכל היותר
     * ``MAX_EDITOR_SETTLE_PASSES`` פעמים.
     */
    function settleEditor(pass) {
      if (pass >= MAX_EDITOR_SETTLE_PASSES) return;
      root.requestAnimationFrame(function () {
        root.requestAnimationFrame(function () {
          if (leader !== 'preview') return;
          if (syncFrom('preview')) settleEditor(pass + 1);
        });
      });
    }

    function run(side) {
      if (syncFrom(side) && side === 'preview') settleEditor(0);
    }

    function schedule(side) {
      pendingSide = side;
      if (frame) return;
      frame = root.requestAnimationFrame(function () {
        frame = 0;
        var nextSide = pendingSide;
        pendingSide = null;
        if (nextSide) run(nextSide);
      });
    }

    /** יישור מחדש אחרי שמשהו השתנה בלי גלילה: רינדור, תמונה שנטענה, קיפול שנפתח, שינוי גודל. */
    function realign() {
      schedule(leader === 'preview' ? 'preview' : 'editor');
    }

    INTENT_EVENTS.forEach(function (type) {
      editorPanel.addEventListener(type, function () { leader = 'editor'; }, { capture: true, passive: true });
      previewPanel.addEventListener(type, function () { leader = 'preview'; }, { capture: true, passive: true });
    });

    // אירוע scroll לא עולה (bubbles: false), אבל עובר בשלב ה-capture דרך כל האבות — ולכן מאזין אחד על הפאנל תופס
    // את הגולל של CodeMirror גם אחרי שהעורך נבנה מחדש (מעבר מהעורך הפשוט).
    editorPanel.addEventListener('scroll', function (event) {
      if (leader !== 'editor') return;
      var view = getEditorView();
      if (view && event.target === view.scrollDOM) schedule('editor');
    }, { capture: true, passive: true });
    canvas.addEventListener('scroll', function () {
      if (leader === 'preview') schedule('preview');
    }, { passive: true });

    // שינוי גובה בתצוגה בלי רינדור: תמונה שנטענה (lazy), וקיפול שנפתח או נסגר. שני האירועים לא עולים, ולכן capture.
    canvas.addEventListener('load', realign, true);
    canvas.addEventListener('toggle', realign, true);
    if (typeof root.ResizeObserver === 'function') {
      var resizeObserver = new root.ResizeObserver(realign);
      resizeObserver.observe(canvas);
      resizeObserver.observe(editorPanel);
    }

    return {
      contentRendered: function (count) {
        rendered = true;
        lineCount = count;
        version += 1;
        cache = null;
        realign();
      },
      contentCleared: function () {
        rendered = false;
        version += 1;
        cache = null;
      },
    };
  }

  var api = {
    attach: attach,
    buildPoints: buildPoints,
    lineToY: lineToY,
    yToLine: yToLine,
    maxScrollOf: maxScrollOf,
    readingY: readingY,
    scrollTopForReadingY: scrollTopForReadingY,
  };

  if (typeof module !== 'undefined' && module.exports) {
    module.exports = api;   // לבדיקות מ-Node
  }
  if (root) {
    root.LivePreviewScrollSync = api; // שימוש בדפדפן
  }
})(typeof window !== 'undefined' ? window : null);
