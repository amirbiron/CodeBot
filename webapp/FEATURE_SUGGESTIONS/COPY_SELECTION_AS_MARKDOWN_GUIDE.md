# מדריך מימוש: "העתק כמארקדאון" — גישת Source Mapping

## סקירה כללית

בתצוגת Markdown המרונדרת (`md_preview.html`) המשתמש רואה HTML מעוצב — כותרות, טבלאות, קוד צבעוני ועוד. כרגע קיים כפתור "העתק קוד" שמעתיק את **כל** המקור. הפיצ'ר הזה מאפשר למשתמש **לסמן קטע** בתצוגה המרונדרת ולקבל את **המארקדאון המקורי** של אותו קטע בלבד.

### למה Source Mapping ולא Fuzzy Matching?

הגישה הקודמת ניסתה למפות טקסט מה-DOM חזרה למקור על ידי השוואת מחרוזות. זו גישה שבירה כי:

- הדפדפן מנרמל רווחים, שורות חדשות ותווים מיוחדים
- `selection.toString()` מחזיר טקסט נקי שלא תואם בהכרח לשורות המקור
- רשימות, טבלאות ו-inline formatting דורשים ניקוי regex שתמיד מפספס מקרי קצה
- אם שורה ראשונה לא נמצאת — אין מסלול התאוששות והכל נופל ל-fallback של טקסט רגיל

**Source Mapping** פותר את זה בצורה דטרמיניסטית: markdown-it כבר מחזיק מידע `map` (שורת התחלה וסיום) על כל token ברמת הבלוק. כל מה שצריך זה לכתוב את המידע הזה כ-`data` attribute על ה-HTML המרונדר, ואז לקרוא אותו ישירות מה-DOM. אפס ניחושים, אפס regex.

---

## מצב הקוד הקיים — מה שכבר יש לנו

### 1. תוכן Markdown גולמי זמין ב-JS

ב-`md_preview.html` שורה ~2022, התוכן הגולמי מוזרק כ-JSON:

```html
<script type="application/json" id="mdText">{{ md_code | tojson | safe }}</script>
```

ובשורה ~2072 הוא נקרא למשתנה גלובלי:

```javascript
const MD_TEXT = (function(){
  try {
    var el = document.getElementById('mdText');
    if (!el) return "";
    return JSON.parse(el.textContent || '""');
  } catch(_) { return ""; }
})();
```

כלומר **`MD_TEXT` כבר מכיל את כל המקור** — זה המפתח לפיצ'ר.

### 2. רינדור בצד לקוח

הרינדור מתבצע בשורה ~2427:

```javascript
const container = document.getElementById('md-content');
container.innerHTML = md.render(MD_TEXT || '');
```

`md` הוא אובייקט `markdown-it` עם פלאגינים (emoji, task-lists, anchor, footnote, container, admonition, hljs).

### 3. מידע שורות כבר קיים ב-tokens

markdown-it שומר על כל token ברמת הבלוק (paragraphs, headings, fences, list items, blockquotes, tables) מערך `map` עם `[startLine, endLine]`. המידע הזה כבר שם — רק צריך לכתוב אותו ל-DOM.

### 4. פונקציות העתקה קיימות

- `copyMarkdownSource` (שורות ~3847–3882) — מעתיקה את **כל** `MD_TEXT`
- `fallbackCopy(text)` — גיבוי עם `document.execCommand('copy')`

---

## עקרון המימוש

### שלב 1: הזרקת Source Map ל-HTML (Plugin)

כותבים plugin ל-markdown-it שעובר על כל ה-token types הרלוונטיים ומוסיף:
- `data-source-line` — שורת ההתחלה במקור (0-based)
- `data-source-line-end` — שורת הסיום במקור (exclusive, 0-based)

### שלב 2: קריאת Source Map מה-DOM

כשהמשתמש מסמן טקסט ולוחץ "העתק":
1. לוקחים את ה-`Range` של הסלקציה
2. מוצאים את האלמנט העוטף של תחילת הסלקציה וסופה
3. עולים ב-DOM עד שמוצאים `[data-source-line]`
4. קוראים את טווח השורות ו**חותכים** מ-`MD_TEXT` את השורות המתאימות

### למה זה עובד בצורה אמינה?

- **אין השוואת מחרוזות** — המיפוי ישיר מ-DOM למקור
- **אין תלות בנרמול** — לא משנה איך הדפדפן מציג את הטקסט
- **כל אלמנט יודע מאיפה הוא בא** — המידע מוצמד ברגע הרינדור

---

## שלבי מימוש

### שלב 1: הוספת CSS לכפתור הצף

הוסיפו את הסגנון הבא בתוך ה-`<style>` הקיים ב-`md_preview.html` (בסוף, לפני `</style>`):

```css
/* ──── כפתור צף "העתק כמארקדאון" ──── */
.md-copy-selection-fab {
  position: absolute;
  z-index: 9999;
  display: none;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 10px;
  border: 1px solid rgba(0, 0, 0, 0.12);
  background: #ffffff;
  color: #1f2937;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
  transition: background 0.15s ease, transform 0.15s ease;
  white-space: nowrap;
  pointer-events: auto;
  font-family: inherit;
  direction: rtl;
}

.md-copy-selection-fab:hover {
  background: #f3f4f6;
  transform: translateY(-1px);
}

.md-copy-selection-fab.is-visible {
  display: inline-flex;
}

.md-copy-selection-fab.is-copied {
  background: #ecfdf5;
  color: #065f46;
  border-color: #a7f3d0;
}

/* התאמה לערכות כהות */
[data-theme="dark"] .md-copy-selection-fab,
[data-theme="dim"] .md-copy-selection-fab,
[data-theme="nebula"] .md-copy-selection-fab {
  background: #1e293b;
  color: #e2e8f0;
  border-color: rgba(255, 255, 255, 0.15);
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
}

[data-theme="dark"] .md-copy-selection-fab:hover,
[data-theme="dim"] .md-copy-selection-fab:hover,
[data-theme="nebula"] .md-copy-selection-fab:hover {
  background: #334155;
}

[data-theme="dark"] .md-copy-selection-fab.is-copied,
[data-theme="dim"] .md-copy-selection-fab.is-copied,
[data-theme="nebula"] .md-copy-selection-fab.is-copied {
  background: #064e3b;
  color: #6ee7b7;
  border-color: #065f46;
}
```

### שלב 2: הוספת אלמנט הכפתור ב-HTML

הוסיפו את האלמנט הבא **אחרי** `<div id="md-content" ...></div>` (שורה ~1844), עדיין בתוך ה-`#mdCard`:

```html
<button type="button"
        id="mdCopySelectionFab"
        class="md-copy-selection-fab"
        aria-label="העתק כמארקדאון">
  <i class="fas fa-copy" aria-hidden="true"></i>
  העתק כמארקדאון
</button>
```

### שלב 3: Plugin ל-Source Mapping

הוסיפו את הקוד הבא **לפני** שורת הרינדור (`container.innerHTML = md.render(...)`) — כלומר אחרי כל ה-`md.use(...)` ולפני הקריאה ל-`md.render`:

```javascript
// ──── Source Mapping Plugin ────
// מוסיף data-source-line / data-source-line-end לכל אלמנט בלוק
// כדי לאפשר מיפוי מדויק מ-DOM חזרה לשורות מקור
(function sourceMapPlugin() {
  // רשימת כל ה-token types שפותחים אלמנט בלוק ומכילים map
  const BLOCK_OPEN_TYPES = [
    'paragraph_open',
    'heading_open',
    'blockquote_open',
    'bullet_list_open',
    'ordered_list_open',
    'list_item_open',
    'table_open',
    'thead_open',
    'tbody_open',
    'tr_open',
    'th_open',
    'td_open',
    'fence',
    'code_block',
    'hr',
  ];

  BLOCK_OPEN_TYPES.forEach(function(type) {
    const originalRule = md.renderer.rules[type];

    md.renderer.rules[type] = function(tokens, idx, options, env, self) {
      const token = tokens[idx];
      if (token.map && token.map.length >= 2) {
        token.attrSet('data-source-line', String(token.map[0]));
        token.attrSet('data-source-line-end', String(token.map[1]));
      }
      if (originalRule) {
        return originalRule(tokens, idx, options, env, self);
      }
      return self.renderToken(tokens, idx, options);
    };
  });
})();
```

**מה קורה כאן:**
- עוברים על כל סוגי ה-tokens שפותחים בלוק (פסקה, כותרת, רשימה וכו')
- לכל אחד — שומרים את ה-rule המקורי ועוטפים אותו
- לפני הרינדור, כותבים את `token.map[0]` (שורת התחלה) ו-`token.map[1]` (שורת סיום) כ-data attributes
- אם אין rule מקורי — משתמשים ב-`self.renderToken` (ברירת המחדל)

**דוגמה לתוצאה:**

Markdown מקורי:
```markdown
# כותרת ראשית

פסקה עם **טקסט מודגש** ועוד דברים.

- פריט א
- פריט ב
```

HTML מרונדר (חלקי):
```html
<h1 data-source-line="0" data-source-line-end="1" id="...">כותרת ראשית</h1>
<p data-source-line="2" data-source-line-end="3">פסקה עם <strong>טקסט מודגש</strong> ועוד דברים.</p>
<ul data-source-line="4" data-source-line-end="6">
  <li data-source-line="4" data-source-line-end="5">פריט א</li>
  <li data-source-line="5" data-source-line-end="6">פריט ב</li>
</ul>
```

כל אלמנט יודע בדיוק מאיפה הוא הגיע במקור.

### שלב 4: לוגיקת העתקה עם Source Mapping

הוסיפו את הסקריפט הבא **אחרי** הסקריפט הקיים של `copyMarkdownSource` (סביב שורה ~3882), עדיין בתוך `{% block content %}`:

```javascript
// === "העתק כמארקדאון" — Source Mapping ===
(function initCopySelectionAsMarkdown() {
  const container = document.getElementById('md-content');
  const fab = document.getElementById('mdCopySelectionFab');
  if (!container || !fab) return;

  const sourceLines = (typeof MD_TEXT === 'string' ? MD_TEXT : '').split('\n');
  if (!sourceLines.length) return;

  // ──── Source Mapping: מ-DOM לשורות מקור ────

  // מוצא את האלמנט הקרוב שיש לו data-source-line
  function findSourceNode(node) {
    if (!node) return null;
    var el = (node.nodeType === Node.TEXT_NODE) ? node.parentElement : node;
    // עולים ב-DOM עד שמוצאים אלמנט עם data-source-line,
    // אבל לא עוברים מעבר לקונטיינר
    while (el && el !== container) {
      if (el.hasAttribute && el.hasAttribute('data-source-line')) {
        return el;
      }
      el = el.parentElement;
    }
    return null;
  }

  // מחפש את ה-data-source-line הראשון/אחרון בתוך range
  // כולל חיפוש באלמנטים ילדים שנמצאים בתוך הטווח
  function getSourceRange(range) {
    var startNode = findSourceNode(range.startContainer);
    var endNode = findSourceNode(range.endContainer);

    // אם לא מצאנו source node ישירות, ננסה למצוא
    // את כל האלמנטים עם data-source-line בתוך ה-range
    if (!startNode && !endNode) {
      // fallback: מחפשים אלמנטים בתוך ה-range
      var fragment = range.cloneContents();
      var mapped = fragment.querySelectorAll('[data-source-line]');
      if (mapped.length > 0) {
        return {
          start: Number(mapped[0].getAttribute('data-source-line')),
          end: Number(mapped[mapped.length - 1].getAttribute('data-source-line-end')
                      || mapped[mapped.length - 1].getAttribute('data-source-line'))
        };
      }
      return null;
    }

    var startLine, endLine;

    if (startNode) {
      startLine = Number(startNode.getAttribute('data-source-line'));
    }
    if (endNode) {
      endLine = Number(endNode.getAttribute('data-source-line-end')
                       || endNode.getAttribute('data-source-line'));
    }

    // אם חסר אחד מהם — השתמש בשני
    if (startLine == null && endLine != null) startLine = endLine;
    if (endLine == null && startLine != null) endLine = startLine;
    if (startLine == null) return null;

    // ודא שהטווח הגיוני
    if (endLine < startLine) {
      var tmp = startLine;
      startLine = endLine;
      endLine = tmp;
    }

    return { start: startLine, end: endLine };
  }

  // הרחבה חכמה: אם הטווח נופל בתוך fenced code block,
  // ודא שכוללים את ה-fences (כי ה-token של fence כבר כולל אותם)
  function expandToFences(start, end) {
    // token.map של fence כבר כולל את שורות הפתיחה והסגירה,
    // אז אם ה-source mapping עובד נכון, אין צורך בהרחבה.
    // אבל ליתר ביטחון, נבדוק אם נפלנו בתוך fence:
    var fenceStart = -1;
    for (var i = start; i >= 0; i--) {
      if (sourceLines[i].trim().startsWith('```')) {
        fenceStart = i;
        break;
      }
    }
    if (fenceStart >= 0 && fenceStart < start) {
      // בדוק שיש fence סוגר אחרי ה-end
      for (var j = end; j < sourceLines.length; j++) {
        if (sourceLines[j].trim().startsWith('```')) {
          return { start: fenceStart, end: j + 1 };
        }
      }
    }
    return { start: start, end: end };
  }

  // הפונקציה הראשית: ממפה range לשורות מקור ומחזירה Markdown
  function mapRangeToMarkdown(range) {
    var sr = getSourceRange(range);
    if (!sr) return '';

    var expanded = expandToFences(sr.start, sr.end);
    // slice עובד עם end exclusive — כמו שמגיע מ-token.map
    var result = sourceLines.slice(expanded.start, expanded.end).join('\n');

    // נקה שורות ריקות מיותרות בהתחלה ובסוף
    return result.replace(/^\n+/, '').replace(/\n+$/, '');
  }

  // ──── מיקום הכפתור הצף ────

  function positionFab(range) {
    var rect = range.getBoundingClientRect();
    var containerRect = (container.closest('.glass-card') || container)
                          .getBoundingClientRect();

    // מקם מעל הסלקציה, מיושר לימין (RTL)
    fab.style.top = (rect.top - containerRect.top - fab.offsetHeight - 8) + 'px';
    fab.style.right = Math.max(8, containerRect.right - rect.right) + 'px';
    fab.style.left = '';
  }

  function showFab(range) {
    fab.classList.remove('is-copied');
    fab.classList.add('is-visible');
    // חכה פריים אחד כדי שה-fab יקבל מידות לפני מיקום
    requestAnimationFrame(function() { positionFab(range); });
  }

  function hideFab() {
    fab.classList.remove('is-visible', 'is-copied');
  }

  // ──── אירועי סלקציה ────

  var hideTimer = null;

  document.addEventListener('selectionchange', function() {
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(function() {
      var sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.rangeCount) {
        hideFab();
        return;
      }

      var range = sel.getRangeAt(0);
      // ודא שהסלקציה בתוך #md-content
      if (!container.contains(range.commonAncestorContainer)) {
        hideFab();
        return;
      }

      var text = sel.toString().trim();
      if (text.length < 2) {
        hideFab();
        return;
      }

      showFab(range);
    }, 250);
  });

  // ──── לחיצה על הכפתור ────

  fab.addEventListener('mousedown', function(e) {
    // מונע מהסלקציה להתבטל בלחיצה על הכפתור
    e.preventDefault();
    e.stopPropagation();
  });

  fab.addEventListener('click', async function(e) {
    e.preventDefault();
    e.stopPropagation();

    var sel = window.getSelection();
    if (!sel || sel.isCollapsed || !sel.rangeCount) return;

    var range = sel.getRangeAt(0);
    var markdown = mapRangeToMarkdown(range);
    // fallback: אם Source Mapping נכשל, העתק את הטקסט הנקי
    var textToCopy = markdown || sel.toString().trim();

    var success = false;
    try {
      await navigator.clipboard.writeText(textToCopy);
      success = true;
    } catch (_) {
      success = (typeof fallbackCopy === 'function') && fallbackCopy(textToCopy);
    }

    if (success) {
      fab.classList.add('is-copied');
      var label = fab.querySelector('span') || fab.lastChild;
      var originalText = label.textContent;
      label.textContent = markdown ? 'הועתק כמארקדאון!' : 'הועתק!';
      setTimeout(function() {
        label.textContent = originalText;
        hideFab();
      }, 1500);
    }
  });
})();
```

---

## הסבר על הלוגיקה לפי חלקים

### חלק 1: ה-Plugin — הזרקת source map ל-HTML

ה-Plugin עובר על כל סוגי ה-tokens שמייצגים בלוקים (פסקאות, כותרות, רשימות, טבלאות, code blocks וכו'). לכל token כזה, markdown-it כבר שומר מערך `map: [startLine, endLine]` שמציין את השורות במקור. ה-Plugin פשוט כותב את המידע הזה כ-data attributes:

```
token.map[0] → data-source-line="0"     (שורת התחלה, 0-based)
token.map[1] → data-source-line-end="3" (שורת סיום, exclusive)
```

**חשוב:** ה-`end` הוא exclusive — כלומר אם `map = [2, 5]`, השורות הן 2, 3, 4 (בלי 5). זה תואם בדיוק ל-`Array.slice(start, end)`.

### חלק 2: מציאת source node

הפונקציה `findSourceNode` מקבלת DOM node (יכול להיות text node) ועולה למעלה ב-DOM עד שמוצאת אלמנט עם `data-source-line`. זה תמיד יצליח כי כל אלמנט בלוק מקבל את ה-attribute מה-Plugin.

### חלק 3: חישוב טווח שורות

`getSourceRange` לוקחת את ה-Range של הסלקציה ומוצאת:
- את ה-`data-source-line` של ה-start container (= שורת ההתחלה)
- את ה-`data-source-line-end` של ה-end container (= שורת הסיום)

אם הסלקציה כולה בתוך אלמנט אחד — שני הערכים מגיעים מאותו אלמנט. אם היא חוצה כמה אלמנטים — כל אחד נותן את הצד שלו.

### חלק 4: חיתוך מקור

פשוט `sourceLines.slice(start, end).join('\n')`. מכיוון ש-`end` כבר exclusive, זה עובד ישירות בלי `+ 1`.

### חלק 5: כפתור צף

זהה לגרסה הקודמת: `position: absolute` ביחס ל-`#mdCard`, מופיע כשיש סלקציה בתוך `#md-content`, נעלם כשהסלקציה מתבטלת.

---

## מקרי קצה ואיך Source Mapping מטפל בהם

### 1. בלוקי קוד (fenced code blocks)

`fence` הוא token type ש-markdown-it מטפל בו כבלוק אחד. ה-`token.map` שלו **כבר כולל** את שורות ה-fences (` ``` `) — כלומר גם הפתיחה וגם הסגירה. לכן כשמסמנים קוד, ה-source map מחזיר את הבלוק המלא כולל ה-language hint.

בנוסף, יש פונקציית `expandToFences` ליתר ביטחון — אם מסיבה כלשהי ה-map לא כולל את ה-fences, היא סורקת למעלה ולמטה ומוצאת אותם.

### 2. טבלאות

טבלאות ב-markdown-it מקבלות `map` על `table_open`. כשמסמנים תא בטבלה:
- `findSourceNode` עולה מה-`<td>` ← `<tr>` ← `<tbody>` ← `<table>`
- כל אחד מהם מכיל `data-source-line`, אז ה-map מדויק
- ה-Plugin מכסה `table_open`, `tr_open`, `th_open`, `td_open` — כך שגם בחירה בתוך תא בודד עובדת

### 3. רשימות מקוננות

`list_item_open` מקבל `map` משלו, כך שכל פריט ברשימה ממופה בנפרד. גם רשימות מקוננות עובדות כי כל רמת קינון היא `list_item_open` עם `map` משלו.

### 4. ציטוטים (blockquotes)

`blockquote_open` מקבל `map` שמכסה את כל הציטוט, כולל סימני `>`. לכן הטקסט שחוזר כולל את תחביר הציטוט.

### 5. סלקציה שחוצה כמה בלוקים

למשל אם המשתמש סימן מאמצע פסקה עד תחילת הבאה:
- `range.startContainer` → מוצא את הפסקה הראשונה (למשל שורות 3–5)
- `range.endContainer` → מוצא את הפסקה השנייה (למשל שורות 7–9)
- התוצאה: שורות 3–9 (כולל שורות ריקות ביניהן)

### 6. Inline elements (bold, italic, links)

ל-inline tokens אין `map` משלהם (ב-markdown-it, מיפוי שורות קיים רק ברמת הבלוק). אבל `findSourceNode` פשוט עולה מה-`<strong>` או `<a>` עד הפסקה העוטפת — שיש לה `map`. כך הסלקציה מחזירה את כל הפסקה, כולל ה-inline markup.

### 7. RTL וכיוון

הכפתור ממוקם ביחס ל-`right` של הקונטיינר — מתאים ל-RTL.

### 8. מסך מלא (Fullscreen)

כשה-card במצב fullscreen, ה-`position: absolute` עדיין יחסי ל-card, כך שהכפתור נשאר בתוך התצוגה.

### 9. Fallback

אם Source Mapping נכשל (למשל אלמנט בלי `data-source-line` — מקרה נדיר), הכפתור מעתיק את הטקסט הנקי של הסלקציה. זה לא אידיאלי, אבל עדיף על כלום, וברוב המוחלט של המקרים זה לא יקרה.

---

## סדר הכנסה בקוד

חשוב לשים את הקוד במיקום הנכון ב-`md_preview.html`:

```
... md.use(markdownitFootnote) ...
... md.use(markdownitTocDoneRight) ...

◄── כאן: Source Mapping Plugin (שלב 3) ──►

const container = document.getElementById('md-content');
container.innerHTML = md.render(MD_TEXT || '');

... (בהמשך, אחרי copyMarkdownSource) ...

◄── כאן: לוגיקת העתקה (שלב 4) ──►
```

ה-Plugin **חייב** להירשם לפני `md.render()`. הלוגיקה של ההעתקה יכולה להיות בכל מקום אחרי שה-DOM מרונדר.

---

## tokens שחסר להם map — מה לעשות?

רוב ה-block tokens ב-markdown-it מקבלים `map` באופן אוטומטי. הנה מצב לכל סוג:

| Token | יש map? | הערות |
|-------|---------|-------|
| `paragraph_open` | כן | תמיד |
| `heading_open` | כן | תמיד |
| `fence` | כן | כולל שורות ` ``` ` |
| `code_block` | כן | בלוק קוד עם הזחה |
| `blockquote_open` | כן | כולל סימני `>` |
| `bullet_list_open` | כן | רשימה לא ממוספרת |
| `ordered_list_open` | כן | רשימה ממוספרת |
| `list_item_open` | כן | פריט ברשימה |
| `table_open` | כן | |
| `tr_open` | כן | |
| `th_open` / `td_open` | כן | |
| `hr` | כן | קו אופקי |
| `html_block` | כן | HTML גולמי (אם `html: true`) |
| inline tokens | **לא** | `strong_open`, `em_open`, `link_open` — אין map, עולים לבלוק העוטף |

> **הערה:** מכיוון שאצלנו `html: false` (בהגדרות markdown-it), אין `html_block` ולכן לא נדרש טיפול מיוחד.

---

## שיפורים אפשריים

### א. קיצור מקלדת

```javascript
document.addEventListener('keydown', function(e) {
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'C') {
    var sel = window.getSelection();
    if (sel && !sel.isCollapsed && container.contains(sel.anchorNode)) {
      e.preventDefault();
      // הפעל את אותה לוגיקה של fab.click
    }
  }
});
```

### ב. תפריט הקשר (Context Menu)

```javascript
container.addEventListener('contextmenu', function(e) {
  var sel = window.getSelection();
  if (sel && !sel.isCollapsed && container.contains(sel.anchorNode)) {
    // הצג תפריט מותאם עם אפשרות "העתק כמארקדאון"
  }
});
```

### ג. Tooltip עם תצוגה מקדימה

לפני ההעתקה, אפשר להציג tooltip קטן שמראה את ה-Markdown שייכנס ללוח — כדי שהמשתמש יוודא שזה מה שהוא רוצה.

---

## קבצים שיש לגעת בהם

| קובץ | סוג שינוי |
|-------|-----------|
| `webapp/templates/md_preview.html` | הוספת CSS, HTML, Plugin ו-JS |

> זהו. הפיצ'ר כולו ממומש ב-**קובץ אחד בלבד** — `md_preview.html`. אין צורך בשינוי בצד שרת, אין endpoint חדש, ואין תלות חדשה.

---

## צ'קליסט למימוש

- [ ] הוספת CSS לכפתור הצף (בתוך ה-`<style>` הקיים)
- [ ] הוספת אלמנט הכפתור (אחרי `#md-content`)
- [ ] הוספת Source Mapping Plugin (לפני `md.render()`)
- [ ] הוספת סקריפט המיפוי והאירועים (אחרי `copyMarkdownSource`)
- [ ] בדיקות:
  - [ ] סימון כותרת → מוחזר `# כותרת`
  - [ ] סימון טקסט מודגש → מוחזרת הפסקה עם `**טקסט**`
  - [ ] סימון בלוק קוד → מוחזר הבלוק עם ` ``` ` ו-language hint
  - [ ] סימון ציטוט → מוחזר עם `>`
  - [ ] סימון טבלה → מוחזר עם `|` ומפרידים
  - [ ] סימון רשימה → מוחזר עם `-` או `1.`
  - [ ] סימון חוצה בלוקים → מוחזרות כל השורות כולל ריקות
  - [ ] בדיקה שאלמנטים ב-DOM מכילים `data-source-line` (DevTools → Elements)
  - [ ] עובד בערכות כהות
  - [ ] עובד במצב מסך מלא
  - [ ] עובד במובייל (long-press לסימון)
- [ ] עדכון CHANGELOG אם רלוונטי

---

## סיכום — למה Source Mapping עדיף?

| קריטריון | Fuzzy Matching (גרסה ישנה) | Source Mapping (גרסה זו) |
|-----------|---------------------------|--------------------------|
| דיוק | תלוי באורך טקסט, ייחודיות, ratio | **100% — מיפוי ישיר** |
| מקרי קצה | רשימות, טבלאות, HTML, אינדנטציה שוברים | **אין** — כל בלוק ממופה |
| תחזוקה | כל שינוי ב-MD format דורש עדכון regex | **אפס** — Plugin גנרי |
| ביצועים | O(n*m) השוואות מחרוזות | **O(1)** — קריאת attribute |
| Fallback | טקסט רגיל (שקט, בלי אזהרה) | טקסט רגיל (נדיר שנגיע לשם) |
