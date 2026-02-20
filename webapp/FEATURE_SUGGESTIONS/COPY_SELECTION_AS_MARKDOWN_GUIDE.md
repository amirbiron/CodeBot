# 📋 מדריך מימוש: "העתק כמארקדאון" — העתקת קטע מסומן כ-Markdown מקורי

## סקירה כללית

בתצוגת Markdown המרונדרת (`md_preview.html`) המשתמש רואה HTML יפה — כותרות, טבלאות, קוד צבעוני ועוד. כרגע קיים כפתור "העתק קוד" שמעתיק את **כל** המקור. הפיצ'ר הזה מאפשר למשתמש **לסמן קטע** בתצוגה המרונדרת ולקבל את **המארקדאון המקורי** של אותו קטע בלבד.

---

## מצב הקוד הקיים — מה שכבר יש לנו

### 1. תוכן Markdown גולמי זמין ב-JS

ב-`md_preview.html` שורה 2022, התוכן הגולמי מוזרק כ-JSON:

```html
<script type="application/json" id="mdText">{{ md_code | tojson | safe }}</script>
```

ובשורה 2072 הוא נקרא למשתנה גלובלי:

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

הרינדור מתבצע בשורה 2427:

```javascript
const container = document.getElementById('md-content');
container.innerHTML = md.render(MD_TEXT || '');
```

`md` הוא אובייקט `markdown-it` עם פלאגינים (emoji, task-lists, anchor, footnote, container, admonition, hljs).

### 3. פונקציית העתקה קיימת

בשורות 3847–3882 יש את `copyMarkdownSource` שמעתיקה את **כל** `MD_TEXT`.

### 4. פונקציית עזר fallback

יש כבר `fallbackCopy(text)` שמשתמשת ב-`document.execCommand('copy')` כגיבוי.

---

## עקרון המימוש

### האתגר

כשמשתמש מסמן טקסט בתצוגה המרונדרת, הדפדפן מחזיר לנו HTML מרונדר (או טקסט נקי). אנחנו צריכים **למפות חזרה** לשורות המארקדאון המקוריות.

### האסטרטגיה: מיפוי לפי שורות מקור

1. **פיצול** `MD_TEXT` למערך שורות.
2. **חילוץ** הטקסט הנקי מהסלקציה (`selection.toString()`).
3. **מציאת** השורה הראשונה והאחרונה ב-`MD_TEXT` שמתאימות לטקסט המסומן.
4. **החזרת** כל שורות המקור מהראשונה עד האחרונה (כולל).

### למה זה עובד?

markdown-it שומר על סדר הטקסט — כלומר הטקסט שמופיע ב-HTML תואם בסדר לטקסט שנמצא בשורות המקור. גם אם יש עיבוד (כותרות, דגשים, קישורים), הטקסט הגולמי נשמר ברצף.

---

## שלבי מימוש

### שלב 1: הוספת CSS לכפתור הצף

הוסיפו את הסגנון הבא בתוך הבלוק `{% block extra_css %}` של `md_preview.html` (בסוף ה-`<style>` הקיים, לפני `</style>`):

```css
/* כפתור צף "העתק כמארקדאון" */
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

הוסיפו את האלמנט הבא **אחרי** `<div id="md-content" ...></div>` (שורה 1844), עדיין בתוך ה-`#mdCard`:

```html
<button type="button"
        id="mdCopySelectionFab"
        class="md-copy-selection-fab"
        aria-label="העתק כמארקדאון">
  <i class="fas fa-markdown" aria-hidden="true"></i>
  העתק כמארקדאון
</button>
```

> **הערה:** אם FontAwesome לא כולל אייקון markdown, אפשר להשתמש ב: `<i class="fas fa-copy"></i>` או באימוג'י `📋`.

### שלב 3: לוגיקת ה-JavaScript

הוסיפו סקריפט חדש **אחרי** הסקריפט הקיים של `copyMarkdownSource` (סביב שורה 3882), עדיין בתוך `{% block content %}`:

```javascript
// === "העתק כמארקדאון" — העתקת קטע מסומן כ-Markdown מקורי ===
(function initCopySelectionAsMarkdown() {
  const container = document.getElementById('md-content');
  const fab = document.getElementById('mdCopySelectionFab');
  if (!container || !fab) return;

  const sourceLines = (typeof MD_TEXT === 'string' ? MD_TEXT : '').split('\n');

  // --- עזרים ---

  // ניקוי טקסט לצורך השוואה: הורדת רווחים מיותרים ותווים לא-נראים
  function normalize(str) {
    return (str || '')
      .replace(/\s+/g, ' ')
      .trim()
      .toLowerCase();
  }

  // חילוץ "טקסט נקי" משורת Markdown — מסיר תחביר כמו #, *, `, -, > וכו'
  function stripMarkdownSyntax(line) {
    return line
      .replace(/^#{1,6}\s+/, '')       // כותרות
      .replace(/^>\s?/gm, '')          // ציטוטים
      .replace(/^[-*+]\s+/, '')        // רשימות
      .replace(/^\d+\.\s+/, '')        // רשימות ממוספרות
      .replace(/^[-*_]{3,}\s*$/, '')   // קווים אופקיים
      .replace(/\*\*(.+?)\*\*/g, '$1') // bold
      .replace(/__(.+?)__/g, '$1')
      .replace(/\*(.+?)\*/g, '$1')     // italic
      .replace(/_(.+?)_/g, '$1')
      .replace(/~~(.+?)~~/g, '$1')     // strikethrough
      .replace(/==(.+?)==/g, '$1')     // mark
      .replace(/`([^`]+)`/g, '$1')     // inline code
      .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1') // links
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, '$1'); // images
  }

  // מציאת אינדקס השורה ב-sourceLines שמכילה טקסט מסוים
  function findLineIndex(searchText, startFrom) {
    const needle = normalize(searchText);
    if (!needle) return -1;
    for (let i = startFrom; i < sourceLines.length; i++) {
      const haystack = normalize(stripMarkdownSyntax(sourceLines[i]));
      if (haystack && needle.includes(haystack)) return i;
      if (haystack && haystack.includes(needle)) return i;
    }
    return -1;
  }

  // מיפוי טקסט מסומן חזרה לשורות מקור
  function mapSelectionToSource(selectedText) {
    if (!selectedText || !sourceLines.length) return '';

    const selLines = selectedText.split('\n').map(l => l.trim()).filter(Boolean);
    if (!selLines.length) return '';

    // מצא את שורת המקור הראשונה שתואמת לשורה הראשונה בסלקציה
    let firstSourceIdx = -1;
    for (const selLine of selLines) {
      firstSourceIdx = findLineIndex(selLine, 0);
      if (firstSourceIdx >= 0) break;
    }

    // מצא את שורת המקור האחרונה שתואמת לשורה האחרונה בסלקציה
    let lastSourceIdx = firstSourceIdx;
    for (let i = selLines.length - 1; i >= 0; i--) {
      const idx = findLineIndex(selLines[i], Math.max(0, firstSourceIdx));
      if (idx >= 0) {
        lastSourceIdx = Math.max(lastSourceIdx, idx);
        break;
      }
    }

    if (firstSourceIdx < 0) return '';

    // הרחבה: אם הסלקציה נופלת בתוך fenced code block — כלול את הבלוק כולו
    // סריקה למעלה ולמטה מנקודת ההתחלה כדי לזהות fences עוטפים
    const isFence = (line) => (line || '').trim().startsWith('```');
    let fenceStart = -1;
    let fenceEnd = -1;

    for (let i = firstSourceIdx; i >= 0; i--) {
      if (isFence(sourceLines[i])) { fenceStart = i; break; }
    }
    if (fenceStart >= 0) {
      for (let i = Math.max(fenceStart + 1, lastSourceIdx); i < sourceLines.length; i++) {
        if (isFence(sourceLines[i])) { fenceEnd = i; break; }
      }
    }

    if (fenceStart >= 0 && fenceEnd > fenceStart) {
      firstSourceIdx = fenceStart;
      lastSourceIdx = fenceEnd;
    }

    return sourceLines.slice(firstSourceIdx, lastSourceIdx + 1).join('\n');
  }

  // --- מיקום הכפתור ---

  function positionFab(range) {
    const rect = range.getBoundingClientRect();
    const containerRect = container.closest('.glass-card')?.getBoundingClientRect()
                       || container.getBoundingClientRect();

    // מקם מעל הסלקציה, מיושר לימין (RTL)
    fab.style.top = (rect.top - containerRect.top - fab.offsetHeight - 8) + 'px';
    fab.style.right = Math.max(8, containerRect.right - rect.right) + 'px';
    fab.style.left = '';
  }

  function showFab(range) {
    fab.classList.remove('is-copied');
    fab.classList.add('is-visible');
    // חכה פריים אחד כדי שה-fab יקבל מידות לפני מיקום
    requestAnimationFrame(() => positionFab(range));
  }

  function hideFab() {
    fab.classList.remove('is-visible', 'is-copied');
  }

  // --- אירועי סלקציה ---

  let hideTimer = null;

  document.addEventListener('selectionchange', () => {
    if (hideTimer) clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      const sel = window.getSelection();
      if (!sel || sel.isCollapsed || !sel.rangeCount) {
        hideFab();
        return;
      }

      const range = sel.getRangeAt(0);
      // ודא שהסלקציה בתוך #md-content
      if (!container.contains(range.commonAncestorContainer)) {
        hideFab();
        return;
      }

      const text = sel.toString().trim();
      if (text.length < 2) {
        hideFab();
        return;
      }

      showFab(range);
    }, 250);
  });

  // --- לחיצה על הכפתור ---

  fab.addEventListener('mousedown', (e) => {
    // מונע מהסלקציה להתבטל בלחיצה על הכפתור
    e.preventDefault();
    e.stopPropagation();
  });

  fab.addEventListener('click', async (e) => {
    e.preventDefault();
    e.stopPropagation();

    const sel = window.getSelection();
    const selectedText = sel ? sel.toString().trim() : '';
    if (!selectedText) return;

    const markdown = mapSelectionToSource(selectedText);
    const textToCopy = markdown || selectedText;

    let success = false;
    try {
      await navigator.clipboard.writeText(textToCopy);
      success = true;
    } catch (_) {
      success = fallbackCopy(textToCopy);
    }

    if (success) {
      fab.classList.add('is-copied');
      const label = fab.querySelector('span') || fab;
      const originalText = label.textContent;
      label.textContent = markdown ? 'הועתק כמארקדאון!' : 'הועתק!';
      setTimeout(() => {
        label.textContent = originalText;
        hideFab();
      }, 1500);
    }
  });

  // הסתרה בלחיצה מחוץ לכפתור
  document.addEventListener('mousedown', (e) => {
    if (e.target !== fab && !fab.contains(e.target)) {
      // נתן ל-selectionchange לטפל
    }
  });
})();
```

---

## הסבר על הלוגיקה לפי חלקים

### חלק 1: פיצול המקור לשורות

```javascript
const sourceLines = (typeof MD_TEXT === 'string' ? MD_TEXT : '').split('\n');
```

ניגשים ל-`MD_TEXT` שכבר קיים כמשתנה גלובלי ומפצלים לשורות.

### חלק 2: ניקוי תחביר Markdown

הפונקציה `stripMarkdownSyntax` מסירה סימני תחביר כמו `#`, `**`, `` ` ``, `>` וכו' — כדי שנוכל להשוות טקסט נקי מהסלקציה לטקסט נקי מהמקור.

### חלק 3: מיפוי חזרה למקור

`mapSelectionToSource` לוקחת את הטקסט המסומן, מפצלת לשורות, ומחפשת עבור השורה הראשונה והאחרונה את השורה המתאימה ב-`sourceLines`. אחר כך מחזירה את כל הבלוק מהראשונה עד האחרונה.

### חלק 4: כפתור צף

הכפתור מוצב `position: absolute` ביחס ל-`#mdCard` (שהוא ה-glass-card העוטף). הוא מופיע כש:

- יש סלקציה בתוך `#md-content`
- הטקסט המסומן גדול מ-2 תווים

הוא נעלם כשהסלקציה מתבטלת.

---

## מקרי קצה ופתרונות

### 1. בלוקי קוד

כשהמשתמש מסמן קוד מעוצב, הטקסט שחוזר מ-`selection.toString()` הוא רק הקוד עצמו (בלי ה-` ``` `). הפונקציה `mapSelectionToSource` סורקת **למעלה** מהשורה הראשונה שנמצאה עד שמוצאת fence פותח, ו**למטה** עד שמוצאת fence סוגר. כך גם כשבוחרים שורה באמצע הבלוק — ההעתקה כוללת את ה-fences ואת ה-language hint (למשל ` ```python `).

### 2. טבלאות

טבלאות מרונדרות מאבדות את תחביר ה-`|`. אבל הטקסט בתוך התאים נשמר, כך שהמיפוי עובד. גם אם המיפוי מחזיר רק חלק מהטבלה — זה עדיף על העתקת HTML.

### 3. מיפוי חלקי (fallback)

אם לא מצליחים למפות — הכפתור מעתיק את הטקסט הנקי של הסלקציה (בלי תחביר Markdown, אבל גם בלי HTML).

### 4. RTL וכיוון

הכפתור ממוקם ביחס ל-`right` של הקונטיינר כדי להתאים ל-RTL.

### 5. מסך מלא (Fullscreen)

כשה-card במצב fullscreen, ה-`position: absolute` עדיין יחסי ל-card, כך שהכפתור יישאר בתוך התצוגה.

---

## שיפורים אפשריים (גרסה 2)

### א. מיפוי מדויק עם data attributes

במקום מיפוי לפי טקסט, אפשר לשנות את ה-render כך שכל אלמנט HTML יקבל `data-source-line` עם מספר השורה:

```javascript
md.use(function sourceLinePlugin(mdInstance) {
  const defaultRender = mdInstance.renderer.rules.paragraph_open ||
    function(tokens, idx, options, env, self) {
      return self.renderToken(tokens, idx, options);
    };

  mdInstance.renderer.rules.paragraph_open = function(tokens, idx, options, env, self) {
    const token = tokens[idx];
    if (token.map && token.map.length) {
      token.attrSet('data-source-line', token.map[0]);
      token.attrSet('data-source-line-end', token.map[1]);
    }
    return defaultRender(tokens, idx, options, env, self);
  };
  // חזור על heading_open, blockquote_open, list_item_open, fence וכו'
});
```

אז המיפוי יהפוך למדויק לחלוטין:

```javascript
function mapSelectionToSourceV2(range) {
  const startEl = range.startContainer.nodeType === Node.TEXT_NODE
    ? range.startContainer.parentElement
    : range.startContainer;
  const endEl = range.endContainer.nodeType === Node.TEXT_NODE
    ? range.endContainer.parentElement
    : range.endContainer;

  const startLine = startEl.closest('[data-source-line]')
    ?.getAttribute('data-source-line');
  const endLine = endEl.closest('[data-source-line-end]')
    ?.getAttribute('data-source-line-end');

  if (startLine != null && endLine != null) {
    return sourceLines.slice(Number(startLine), Number(endLine)).join('\n');
  }
  return null; // fallback לשיטה הקודמת
}
```

> **הערה:** markdown-it כבר מכניס `map` על רוב ה-tokens (למשל paragraphs, headings, fences). כל מה שצריך זה hook שכותב אותו כ-data attribute.

### ב. תפריט הקשר (Context Menu)

במקום כפתור צף, אפשר להוסיף אפשרות ל-context menu (קליק ימני):

```javascript
container.addEventListener('contextmenu', (e) => {
  const sel = window.getSelection();
  if (sel && !sel.isCollapsed && container.contains(sel.anchorNode)) {
    // הצג תפריט מותאם עם אפשרות "העתק כמארקדאון"
  }
});
```

### ג. קיצור מקלדת

```javascript
document.addEventListener('keydown', (e) => {
  if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'C') {
    const sel = window.getSelection();
    if (sel && !sel.isCollapsed && container.contains(sel.anchorNode)) {
      e.preventDefault();
      // הפעל העתקה כמארקדאון
    }
  }
});
```

---

## קבצים שיש לגעת בהם

| קובץ | סוג שינוי |
|-------|-----------|
| `webapp/templates/md_preview.html` | הוספת CSS, HTML ו-JS |

> זהו! הפיצ'ר כולו ממומש ב-**קובץ אחד בלבד** — `md_preview.html`. אין צורך בשינוי בצד שרת, אין endpoint חדש, ואין תלות חדשה.

---

## צ'קליסט למימוש

- [ ] הוספת CSS לכפתור הצף (בתוך `{% block extra_css %}`)
- [ ] הוספת אלמנט הכפתור (אחרי `#md-content`)
- [ ] הוספת סקריפט המיפוי והאירועים (אחרי `copyMarkdownSource`)
- [ ] בדיקות:
  - [ ] סימון כותרת → מוחזר `# כותרת`
  - [ ] סימון טקסט מודגש → מוחזר `**טקסט**`
  - [ ] סימון בלוק קוד → מוחזר הבלוק עם הגדרות
  - [ ] סימון ציטוט → מוחזר עם `>`
  - [ ] סימון קטע שלא ממופה → מוחזר טקסט נקי כ-fallback
  - [ ] עובד בערכות כהות
  - [ ] עובד במצב מסך מלא
  - [ ] עובד במובייל (long-press לסימון)
- [ ] עדכון CHANGELOG אם רלוונטי

---

## סיכום

הפיצ'ר הזה פשוט למימוש כי:

1. **המקור כבר נגיש ב-JS** — `MD_TEXT` קיים.
2. **אין צורך בשרת** — הכל בצד לקוח.
3. **הלוגיקה מינימלית** — מיפוי לפי טקסט + חיפוש שורות.
4. **ה-fallback טוב** — אם מיפוי נכשל, מעתיקים טקסט נקי.

השיפור העיקרי לגרסה 2 (data attributes) יהפוך את המיפוי למדויק ב-100%, אבל גם גרסה 1 עם מיפוי טקסטואלי נותנת חוויה טובה מאוד לרוב המקרים.
