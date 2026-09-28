/**
 * הדגשת התאמות חיפוש — תשובה אחת לשאלה "איך מדגישים התאמה".
 *
 * משותף לשלושה צרכנים: החיפוש במסמך (``md_preview.html``), עמוד חיפוש
 * הפתקים (``notes_search.js``) והחיפוש בתוך פתק דביק (``sticky-notes.js``).
 * לפני הקובץ הזה היו שני מימושים נפרדים — ``highlightTerm`` במסמך
 * ו-``highlightInto`` בעמוד החיפוש — ולשניהם אותה ליבה בדיוק: פיצול טקסט
 * לקטעים רגילים ולקטעים מסומנים, עם בריחה ליטרלית ובלי רגישות לרישיות.
 *
 * **כללי ההתאמה זהים לחיפוש הפתקים בשרת** (``note_search_filter``
 * ב-``sticky_notes_target.py``): ליטרלי, לא רגיש לרישיות, בלי נרמול ניקוד.
 * כך פתק שנמצא בחיפוש "X" מציג הדגשה גם כשמחפשים X בתוכו.
 *
 * **ואין ``innerHTML`` בקובץ הזה.** כל עטיפה נוצרת ב-``createElement``
 * והטקסט שלה נכנס דרך ``textContent``, כי הטקסט הוא מה שהמשתמש כתב
 * (``bugbot-rules/xss-innerhtml``).
 *
 * מה שייחודי לכל צרכן — איזו מחלקה, מה עוד מדלגים עליו, מתי מריצים —
 * נשאר אצל הצרכן. הקובץ הזה אינו יודע דבר על פתקים או על מסמכים.
 */
(function () {
  'use strict';

  /**
   * תת-העצים שלעולם אינם נסרקים, בכל צרכן.
   *
   * **הדילוג הוא לפי סלקטור ולא לפי ``tagName``, וזה התיקון.** הבדיקה
   * הקודמת במסמך השוותה ``tagName`` ל-``'SVG'``, אבל אלמנט SVG במסמך HTML
   * מחזיר ``tagName`` באותיות קטנות (``'svg'``, וגם ``'style'`` שבתוכו) —
   * כלומר הבדיקה לא תפסה אף פעם. נמדד בכרומיום: ``tagName`` של ``<svg>``
   * הוא ``svg``, ו-``matches('svg')`` מחזיר ``true``. סלקטור מתאים את שני
   * המרחבים בלי תלות ברישיות.
   *
   * ולמה SVG בכלל: עטיפת HTML בתוך ``<text>`` של SVG אינה מצוירת, ולכן
   * ההתאמה הייתה נעלמת מהדיאגרמה במקום להידלק, וב-``<style>`` שבתוך SVG
   * היא הייתה מפרקת את ה-CSS באמצע מילה.
   */
  var DEFAULT_SKIP = 'script, style, noscript, svg';

  /** שם מחלקה שאפשר לשים בסלקטור כמו שהוא, בלי בריחה. */
  var CLASS_NAME_RE = /^[A-Za-z_][A-Za-z0-9_-]*$/;

  /** בריחת תווי רג'קס — המחט היא טקסט ליטרלי, לא ביטוי. */
  function escapeRegExp(s) {
    return String(s).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  }

  /** ``null``/``undefined`` הופכים למחרוזת ריקה, וכל ערך אחר ל-``String``. */
  function asText(value) {
    return String(value == null ? '' : value);
  }

  /**
   * מפצל טקסט לקטעים ``{ text, hit }`` לפי כל מופע של ``term``.
   *
   * זו הליבה שכל שאר הפונקציות עוברות דרכה. מחט ריקה אינה מסמנת דבר,
   * וטקסט ריק מחזיר רשימה ריקה. חיבור ``text`` של כל הקטעים מחזיר תמיד
   * את הטקסט המקורי, תו בתו.
   */
  function splitMatches(text, term) {
    var value = asText(text);
    var needle = asText(term);
    if (!value) return [];
    if (!needle) return [{ text: value, hit: false }];

    var re = new RegExp(escapeRegExp(needle), 'gi');
    var parts = [];
    var last = 0;
    var m;
    while ((m = re.exec(value)) !== null) {
      if (m.index > last) parts.push({ text: value.slice(last, m.index), hit: false });
      parts.push({ text: m[0], hit: true });
      last = m.index + m[0].length;
      // מחט ריקה נעצרה למעלה, ולכן התאמה באורך אפס אינה אפשרית כאן. אבל
      // ``lastIndex`` שלא זז הוא לולאה אינסופית שמקפיאה את הלשונית, ולכן
      // החסם נשאר.
      if (m[0].length === 0) re.lastIndex += 1;
    }
    if (last < value.length) parts.push({ text: value.slice(last), hit: false });
    return parts;
  }

  /** קורא את האפשרויות ומוודא שם מחלקה — עטיפה בלי מחלקה אי אפשר לנקות. */
  function readOptions(opts, defaultTag) {
    var o = opts || {};
    var className = o.className;
    if (typeof className !== 'string' || !CLASS_NAME_RE.test(className)) {
      throw new TypeError('TextHighlight: className must be a plain CSS class name');
    }
    var tagName = (typeof o.tagName === 'string' && o.tagName) ? o.tagName : defaultTag;
    var extra = (typeof o.skip === 'string' && o.skip.trim()) ? o.skip.trim() : '';
    return {
      className: className,
      tagName: tagName,
      skip: extra ? DEFAULT_SKIP + ', ' + extra : DEFAULT_SKIP,
    };
  }

  function docOf(node) {
    return (node && node.ownerDocument) || document;
  }

  /** בונה את הקטעים לתוך ``target`` ומחזיר את העטיפות שנוצרו, לפי הסדר. */
  function appendParts(doc, target, parts, o) {
    var made = [];
    for (var i = 0; i < parts.length; i++) {
      var part = parts[i];
      if (part.hit) {
        var wrap = doc.createElement(o.tagName);
        wrap.className = o.className;
        wrap.textContent = part.text;
        target.appendChild(wrap);
        made.push(wrap);
      } else {
        target.appendChild(doc.createTextNode(part.text));
      }
    }
    return made;
  }

  /**
   * מוסיף ל-``container`` את ``text`` כשכל מופע של ``term`` עטוף.
   * ברירת המחדל לתגית היא ``mark``. מחזיר **כמה מופעים סומנו**.
   *
   * זו הצורה למי שבונה את התוכן בעצמו מתוך מחרוזת (עמוד חיפוש הפתקים),
   * ולא עובר על תצוגה שכבר קיימת.
   */
  function appendHighlighted(container, text, term, opts) {
    var o = readOptions(opts, 'mark');
    return appendParts(docOf(container), container, splitMatches(text, term), o).length;
  }

  /**
   * מסיר מתחת ל-``root`` כל עטיפה במחלקה ``className`` ומחזיר את הטקסט
   * שלה למקומו. מחזיר כמה עטיפות הוסרו.
   *
   * ``normalize`` מאחד את צמתי הטקסט הסמוכים שנשארים אחרי ההסרה, ומוחק
   * צמתים ריקים — כלומר התצוגה חוזרת למבנה שהיה לה לפני ההדגשה. מקור:
   * MDN, ‏Node.normalize().
   */
  function clearHighlights(root, className) {
    if (typeof className !== 'string' || !CLASS_NAME_RE.test(className)) {
      throw new TypeError('TextHighlight: className must be a plain CSS class name');
    }
    var doc = docOf(root);
    var found = root.querySelectorAll('.' + className);
    var parents = [];
    for (var i = 0; i < found.length; i++) {
      var wrap = found[i];
      var parent = wrap.parentNode;
      if (!parent) continue;
      parent.replaceChild(doc.createTextNode(wrap.textContent), wrap);
      if (parents.indexOf(parent) === -1) parents.push(parent);
    }
    for (var j = 0; j < parents.length; j++) parents[j].normalize();
    return found.length;
  }

  /**
   * עוטף כל מופע של ``term`` בצמתי הטקסט שמתחת ל-``root``, ומחזיר את
   * העטיפות שנוצרו **בסדר המסמך**.
   *
   * ``opts.className`` חובה. ``opts.tagName`` ברירת מחדל ``span``.
   * ``opts.skip`` הוא סלקטור של תת-עצים נוספים שלא נסרקים, **בנוסף**
   * ל-``DEFAULT_SKIP`` שחל תמיד.
   *
   * הקריאה מנקה קודם הדגשות קודמות באותה מחלקה, ולכן אפשר לקרוא לה שוב
   * על אותו שורש בלי לעטוף עטיפה בתוך עטיפה.
   *
   * התאמה שחוצה גבול בין שני צמתי טקסט (למשל מילה שחציה מודגש) אינה
   * נתפסת — כל צומת טקסט נבדק לבדו.
   */
  function highlightWithin(root, term, opts) {
    var o = readOptions(opts, 'span');
    clearHighlights(root, o.className);
    var needle = asText(term);
    if (!needle) return [];

    var doc = docOf(root);
    // ‏SHOW_ELEMENT | SHOW_TEXT: האלמנטים עוברים דרך המסנן רק כדי שאפשר
    // יהיה לדחות אותם. ‏FILTER_REJECT על אלמנט ב-TreeWalker מדלג על כל
    // תת-העץ שלו, ו-FILTER_SKIP מדלג רק עליו וממשיך לילדים.
    // מקור: MDN, ‏Document.createTreeWalker() ו-NodeFilter.acceptNode().
    // ‏matches זורק SyntaxError על סלקטור לא תקין — וזה הערוץ הנכון:
    // שגיאת קורא צריכה להישמע. מקור: MDN, ‏Element.matches().
    var walker = doc.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: function (node) {
        if (node.nodeType === 1) {
          return node.matches(o.skip) ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_SKIP;
        }
        return NodeFilter.FILTER_ACCEPT;
      },
    });

    // קודם אוספים, ורק אחר כך מחליפים: החלפה תוך כדי הליכה משנה את העץ
    // שההליכה עוברת עליו.
    var probe = new RegExp(escapeRegExp(needle), 'i');
    var targets = [];
    var node;
    while ((node = walker.nextNode())) {
      if (probe.test(node.nodeValue)) targets.push(node);
    }

    var wrappers = [];
    for (var i = 0; i < targets.length; i++) {
      var textNode = targets[i];
      var frag = doc.createDocumentFragment();
      var made = appendParts(doc, frag, splitMatches(textNode.nodeValue, needle), o);
      textNode.parentNode.replaceChild(frag, textNode);
      for (var k = 0; k < made.length; k++) wrappers.push(made[k]);
    }
    return wrappers;
  }

  if (typeof window !== 'undefined') {
    window.TextHighlight = Object.freeze({
      DEFAULT_SKIP: DEFAULT_SKIP,
      escapeRegExp: escapeRegExp,
      splitMatches: splitMatches,
      appendHighlighted: appendHighlighted,
      highlightWithin: highlightWithin,
      clearHighlights: clearHighlights,
    });
  }
})();
