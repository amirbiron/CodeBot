# מדריך מימוש תצוגת Markdown בדפדפן הריפו

מדריך זה מפרט את השלבים למימוש אפשרות להציג תצוגת Markdown מעוצבת למסמכי `.md` בדפדפן הריפו (Repo Browser).

## סקירת הארכיטקטורה הקיימת

### קבצים רלוונטיים

| קובץ | תיאור |
|------|-------|
| `webapp/static/js/repo-browser.js` | הלוגיקה הראשית של דפדפן הריפו |
| `webapp/static/js/live-preview.js` | מנוע רינדור Markdown קיים (ניתן לשימוש חוזר!) |
| `webapp/templates/repo/index.html` | התבנית HTML של דפדפן הריפו |
| `webapp/static/css/repo-browser.css` | עיצוב דפדפן הריפו |
| `webapp/static/css/markdown-enhanced.css` | עיצוב Markdown מתקדם (admonitions, details, וכו') |

### זרימת הקוד הנוכחית

```
selectFile(path) → fetch API → initCodeViewer(content, language) → CodeMirror
```

הפונקציה `selectFile` ב-`repo-browser.js:881` אחראית על:
1. שליפת תוכן הקובץ מה-API
2. עדכון breadcrumbs ומידע על הקובץ
3. הצגת התוכן ב-CodeMirror

### מנוע Markdown קיים

הפרויקט כבר כולל מנוע רינדור Markdown מלא ב-`live-preview.js`:

```javascript
// MarkdownLiveRenderer - מנוע קיים שניתן לשימוש חוזר
MarkdownLiveRenderer.render(text)     // מחזיר HTML
MarkdownLiveRenderer.enhance(element) // מוסיף highlighting, math, mermaid
```

**יכולות קיימות:**
- Task lists עם checkboxes
- Admonitions (note, tip, warning, danger, info, success, וכו')
- קטעים מתקפלים (details)
- הערות שוליים (footnotes)
- תוכן עניינים אוטומטי
- אימוג'ים
- נוסחאות מתמטיות (KaTeX)
- דיאגרמות Mermaid
- Syntax highlighting לבלוקי קוד

---

## שלבי המימוש

### שלב 1: הוספת אלמנטים ל-HTML

**קובץ:** `webapp/templates/repo/index.html`

הוסף כפתור toggle ופאנל תצוגה בתוך `code-header`:

```html
<!-- בתוך .file-actions (שורה 19 בערך) -->
<div class="file-actions">
    <!-- כפתור תצוגת Markdown - יוצג רק לקבצי .md -->
    <button class="btn-icon markdown-preview-toggle"
            id="markdown-preview-toggle"
            title="תצוגת Markdown (Ctrl+Shift+M)"
            style="display: none;">
        <i class="bi bi-markdown"></i>
    </button>

    <!-- כפתורים קיימים -->
    <button class="btn-icon" id="search-in-file" ...>
    ...
</div>
```

הוסף container לתצוגת ה-Markdown (אחרי `code-editor-wrapper`):

```html
<!-- Markdown Preview Container -->
<div class="markdown-preview-container" id="markdown-preview-container" style="display: none;">
    <div class="markdown-preview-content markdown-body" id="markdown-preview-content">
        <!-- תוכן ה-Markdown המרונדר יוזרק לכאן -->
    </div>
</div>
```

---

### שלב 2: הוספת CSS

**קובץ:** `webapp/static/css/repo-browser.css`

הוסף בסוף הקובץ:

```css
/* ========================================
   Markdown Preview Toggle
   ======================================== */

/* כפתור Toggle */
.markdown-preview-toggle {
    position: relative;
    transition: all 0.2s ease;
}

.markdown-preview-toggle.active {
    background: var(--accent-blue);
    color: var(--bg-primary);
}

.markdown-preview-toggle.active:hover {
    background: var(--accent-purple);
}

/* אינדיקטור שהתצוגה פעילה */
.markdown-preview-toggle.active::after {
    content: '';
    position: absolute;
    bottom: -2px;
    left: 50%;
    transform: translateX(-50%);
    width: 4px;
    height: 4px;
    background: var(--accent-green);
    border-radius: 50%;
}

/* Container לתצוגת Markdown */
.markdown-preview-container {
    flex: 1;
    overflow: auto;
    padding: 24px 32px;
    background: var(--bg-secondary);
    direction: rtl; /* תמיכה בעברית */
}

/* תוכן ה-Markdown */
.markdown-preview-content {
    max-width: 900px;
    margin: 0 auto;
    line-height: 1.7;
    color: var(--text-primary);
}

/* כותרות */
.markdown-preview-content h1,
.markdown-preview-content h2,
.markdown-preview-content h3,
.markdown-preview-content h4,
.markdown-preview-content h5,
.markdown-preview-content h6 {
    color: var(--text-primary);
    margin-top: 1.5em;
    margin-bottom: 0.5em;
    font-weight: 600;
    line-height: 1.3;
}

.markdown-preview-content h1 {
    font-size: 2em;
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 0.3em;
}

.markdown-preview-content h2 {
    font-size: 1.5em;
    border-bottom: 1px solid var(--border-color);
    padding-bottom: 0.3em;
}

/* קישורים */
.markdown-preview-content a {
    color: var(--accent-blue);
    text-decoration: none;
}

.markdown-preview-content a:hover {
    text-decoration: underline;
}

/* בלוקי קוד */
.markdown-preview-content pre {
    background: var(--bg-primary);
    border: 1px solid var(--border-color);
    border-radius: 6px;
    padding: 16px;
    overflow-x: auto;
    direction: ltr; /* קוד תמיד LTR */
    text-align: left;
}

.markdown-preview-content code {
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.9em;
}

.markdown-preview-content :not(pre) > code {
    background: var(--bg-tertiary);
    padding: 2px 6px;
    border-radius: 4px;
    color: var(--accent-peach);
}

/* טבלאות */
.markdown-preview-content table {
    width: 100%;
    border-collapse: collapse;
    margin: 1em 0;
}

.markdown-preview-content th,
.markdown-preview-content td {
    border: 1px solid var(--border-color);
    padding: 8px 12px;
    text-align: right;
}

.markdown-preview-content th {
    background: var(--bg-tertiary);
    font-weight: 600;
}

.markdown-preview-content tr:nth-child(even) {
    background: rgba(255, 255, 255, 0.02);
}

/* רשימות */
.markdown-preview-content ul,
.markdown-preview-content ol {
    padding-right: 2em;
    padding-left: 0;
}

.markdown-preview-content li {
    margin: 0.25em 0;
}

/* Task lists */
.markdown-preview-content .task-list-item {
    list-style: none;
    margin-right: -1.5em;
}

.markdown-preview-content .task-list-item input[type="checkbox"] {
    margin-left: 0.5em;
    margin-right: 0;
}

/* ציטוטים */
.markdown-preview-content blockquote {
    border-right: 4px solid var(--accent-blue);
    border-left: none;
    margin: 1em 0;
    padding: 0.5em 1em;
    background: rgba(137, 180, 250, 0.1);
    color: var(--text-secondary);
}

/* תמונות */
.markdown-preview-content img {
    max-width: 100%;
    height: auto;
    border-radius: 8px;
    margin: 1em 0;
}

/* קו הפרדה */
.markdown-preview-content hr {
    border: none;
    border-top: 1px solid var(--border-color);
    margin: 2em 0;
}

/* מעבר חלק בין תצוגות */
.code-editor-wrapper,
.markdown-preview-container {
    transition: opacity 0.2s ease;
}

.code-editor-wrapper.hidden,
.markdown-preview-container.hidden {
    display: none !important;
}
```

---

### שלב 3: הוספת לוגיקה ב-JavaScript

**קובץ:** `webapp/static/js/repo-browser.js`

#### 3.1 הוספה ל-State

```javascript
// בתוך אובייקט state (שורה 64 בערך)
let state = {
    currentFile: null,
    treeData: null,
    editor: null,
    editorView6: null,
    expandedFolders: new Set(),
    selectedElement: null,
    // ... שאר השדות הקיימים ...

    // הוספה חדשה:
    markdownPreviewEnabled: false,
    currentFileContent: null,  // שמירת התוכן לשימוש חוזר
};
```

#### 3.2 פונקציות עזר לזיהוי Markdown

```javascript
// הוסף אחרי הגדרת CONFIG

/**
 * בודק אם הקובץ הוא קובץ Markdown
 */
function isMarkdownFile(path) {
    if (!path) return false;
    const ext = path.split('.').pop().toLowerCase();
    return ext === 'md' || ext === 'markdown';
}

/**
 * בודק אם השפה היא Markdown
 */
function isMarkdownLanguage(language) {
    if (!language) return false;
    const lang = language.toLowerCase();
    return lang === 'markdown' || lang === 'md';
}
```

#### 3.3 פונקציות Toggle

```javascript
/**
 * מציג/מסתיר את כפתור תצוגת Markdown
 */
function updateMarkdownToggleVisibility(path, language) {
    const toggleBtn = document.getElementById('markdown-preview-toggle');
    if (!toggleBtn) return;

    const isMarkdown = isMarkdownFile(path) || isMarkdownLanguage(language);
    toggleBtn.style.display = isMarkdown ? 'flex' : 'none';

    // אם עברנו לקובץ שאינו Markdown, כבה את התצוגה
    if (!isMarkdown && state.markdownPreviewEnabled) {
        disableMarkdownPreview();
    }
}

/**
 * מפעיל תצוגת Markdown
 */
async function enableMarkdownPreview() {
    const editorWrapper = document.getElementById('code-editor-wrapper');
    const previewContainer = document.getElementById('markdown-preview-container');
    const toggleBtn = document.getElementById('markdown-preview-toggle');
    const previewContent = document.getElementById('markdown-preview-content');

    if (!editorWrapper || !previewContainer || !previewContent) return;

    state.markdownPreviewEnabled = true;

    // עדכון UI
    editorWrapper.style.display = 'none';
    previewContainer.style.display = 'block';
    toggleBtn?.classList.add('active');

    // רינדור התוכן
    await renderMarkdownPreview(state.currentFileContent);
}

/**
 * מכבה תצוגת Markdown
 */
function disableMarkdownPreview() {
    const editorWrapper = document.getElementById('code-editor-wrapper');
    const previewContainer = document.getElementById('markdown-preview-container');
    const toggleBtn = document.getElementById('markdown-preview-toggle');

    if (!editorWrapper || !previewContainer) return;

    state.markdownPreviewEnabled = false;

    // עדכון UI
    editorWrapper.style.display = 'block';
    previewContainer.style.display = 'none';
    toggleBtn?.classList.remove('active');

    // רענון CodeMirror
    setTimeout(() => {
        if (state.editor) {
            state.editor.refresh();
        }
    }, 100);
}

/**
 * Toggle בין תצוגת קוד לתצוגת Markdown
 */
function toggleMarkdownPreview() {
    if (state.markdownPreviewEnabled) {
        disableMarkdownPreview();
    } else {
        enableMarkdownPreview();
    }

    // שמירת העדפה ב-localStorage
    localStorage.setItem('repo-browser-markdown-preview', state.markdownPreviewEnabled);
}

/**
 * רינדור תוכן Markdown
 */
async function renderMarkdownPreview(content) {
    const previewContent = document.getElementById('markdown-preview-content');
    if (!previewContent || !content) return;

    try {
        // בדיקה שה-MarkdownLiveRenderer זמין
        if (typeof MarkdownLiveRenderer === 'undefined' || !MarkdownLiveRenderer.isSupported()) {
            // Fallback: טעינת markdown-it אם לא נטען
            await loadMarkdownDependencies();
        }

        // רינדור ה-Markdown ל-HTML
        const html = await MarkdownLiveRenderer.render(content);
        previewContent.innerHTML = html;

        // שיפורים: syntax highlighting, math, mermaid
        await MarkdownLiveRenderer.enhance(previewContent);

    } catch (error) {
        console.error('Failed to render markdown:', error);
        previewContent.innerHTML = `
            <div class="error-message" style="padding: 20px; color: var(--accent-red);">
                <i class="bi bi-exclamation-triangle"></i>
                <span>שגיאה ברינדור Markdown: ${escapeHtml(error.message)}</span>
            </div>
        `;
    }
}

/**
 * טעינת תלויות Markdown (אם לא נטענו)
 */
async function loadMarkdownDependencies() {
    const scripts = [
        'https://cdn.jsdelivr.net/npm/markdown-it@14/dist/markdown-it.min.js',
        'https://cdn.jsdelivr.net/npm/highlight.js@11/highlight.min.js'
    ];

    for (const src of scripts) {
        if (!document.querySelector(`script[src="${src}"]`)) {
            await new Promise((resolve, reject) => {
                const script = document.createElement('script');
                script.src = src;
                script.onload = resolve;
                script.onerror = reject;
                document.head.appendChild(script);
            });
        }
    }
}
```

#### 3.4 עדכון פונקציית selectFile

עדכן את הפונקציה `selectFile` (שורה 881):

```javascript
async function selectFile(path, element) {
    // ... קוד קיים עד שורה 938 ...

    try {
        const response = await fetch(`${CONFIG.apiBase}/file/${encodeURIComponent(path)}?${getRepoParam()}`);
        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // שמירת התוכן ל-state (הוספה חדשה)
        state.currentFileContent = data.content;

        const language = data.language || detectLanguage(path);

        // עדכון breadcrumbs
        updateBreadcrumbs(path);
        updateFileHeader(path);
        updateFileInfo(data);

        // עדכון נראות כפתור Markdown (הוספה חדשה)
        updateMarkdownToggleVisibility(path, language);

        // בדיקה אם להציג Markdown או קוד
        const isMarkdown = isMarkdownFile(path) || isMarkdownLanguage(language);
        const savedPreference = localStorage.getItem('repo-browser-markdown-preview') === 'true';

        if (isMarkdown && savedPreference) {
            // המשתמש העדיף תצוגת Markdown - הצג אותה
            await enableMarkdownPreview();
        } else {
            // הצג קוד רגיל
            disableMarkdownPreview();
            await initCodeViewer(data.content, language);
        }

        addToRecentFiles(path);

    } catch (error) {
        // ... קוד קיים לטיפול בשגיאות ...
    }
}
```

#### 3.5 רישום Event Listeners

הוסף בפונקציית האתחול `initRepoBrowser()`:

```javascript
function initRepoBrowser() {
    // ... קוד קיים ...

    // רישום כפתור Markdown Preview
    const markdownToggle = document.getElementById('markdown-preview-toggle');
    if (markdownToggle) {
        markdownToggle.addEventListener('click', toggleMarkdownPreview);
    }

    // קיצור מקלדת: Ctrl+Shift+M
    document.addEventListener('keydown', (e) => {
        if (e.ctrlKey && e.shiftKey && e.key.toLowerCase() === 'm') {
            const toggleBtn = document.getElementById('markdown-preview-toggle');
            if (toggleBtn && toggleBtn.style.display !== 'none') {
                e.preventDefault();
                toggleMarkdownPreview();
            }
        }
    });

    // ... המשך קוד קיים ...
}
```

#### 3.6 חשיפה גלובלית

הוסף בסוף הקובץ (באזור ה-exports הגלובליים):

```javascript
// הוספה לאובייקט הגלובלי
window.toggleMarkdownPreview = toggleMarkdownPreview;
window.enableMarkdownPreview = enableMarkdownPreview;
window.disableMarkdownPreview = disableMarkdownPreview;
```

---

### שלב 4: טעינת תלויות

**קובץ:** `webapp/templates/repo/base_repo.html`

ודא שה-CSS של markdown-enhanced נטען:

```html
<!-- בתוך ה-head -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/markdown-enhanced.css') }}">
```

ודא שה-live-preview.js נטען לפני repo-browser.js:

```html
<!-- לפני repo-browser.js -->
<script src="{{ url_for('static', filename='js/live-preview.js') }}"></script>
<script src="{{ url_for('static', filename='js/repo-browser.js') }}"></script>
```

---

### שלב 5: הוספת אייקון Bootstrap

האייקון `bi-markdown` כבר קיים ב-Bootstrap Icons. אם אתה רוצה אייקון מותאם אישית:

```css
/* אייקון Markdown מותאם אישית */
.bi-markdown-custom::before {
    content: "M↓";
    font-weight: bold;
    font-family: monospace;
}
```

---

## שיפורים אופציונליים

### 1. Split View (תצוגה מפוצלת)

אפשר להוסיף תצוגה מפוצלת - קוד משמאל, preview מימין:

```javascript
function enableSplitView() {
    const container = document.getElementById('code-viewer-container');
    const editorWrapper = document.getElementById('code-editor-wrapper');
    const previewContainer = document.getElementById('markdown-preview-container');

    container.classList.add('split-view');
    editorWrapper.style.display = 'block';
    previewContainer.style.display = 'block';
}
```

```css
.code-viewer-container.split-view {
    display: grid;
    grid-template-columns: 1fr 1fr;
    grid-template-rows: auto 1fr auto;
}

.code-viewer-container.split-view .code-header {
    grid-column: 1 / -1;
}

.code-viewer-container.split-view .code-editor-wrapper {
    border-left: 1px solid var(--border-color);
}
```

### 2. Table of Contents צף

```javascript
function addFloatingTOC(previewContent) {
    const headings = previewContent.querySelectorAll('h1, h2, h3');
    if (headings.length < 3) return;

    const toc = document.createElement('nav');
    toc.className = 'floating-toc';
    toc.innerHTML = '<h4>תוכן עניינים</h4>';

    const list = document.createElement('ul');
    headings.forEach(h => {
        const li = document.createElement('li');
        li.className = `toc-${h.tagName.toLowerCase()}`;
        const a = document.createElement('a');
        a.href = `#${h.id}`;
        a.textContent = h.textContent;
        li.appendChild(a);
        list.appendChild(li);
    });

    toc.appendChild(list);
    previewContent.prepend(toc);
}
```

### 3. שמירת מיקום גלילה

```javascript
// שמירת מיקום גלילה בעת מעבר בין תצוגות
let savedScrollPosition = 0;

function enableMarkdownPreview() {
    savedScrollPosition = document.getElementById('code-editor-wrapper')?.scrollTop || 0;
    // ... שאר הקוד ...

    // שחזור מיקום גלילה
    setTimeout(() => {
        const previewContainer = document.getElementById('markdown-preview-container');
        if (previewContainer) {
            previewContainer.scrollTop = savedScrollPosition;
        }
    }, 100);
}
```

### 4. תמיכה ב-GitHub Flavored Markdown

ה-`MarkdownLiveRenderer` הקיים כבר תומך ברוב התכונות. להוספת תמיכה בתחביר GitHub מיוחד:

```javascript
// התאמות ל-GFM
function enhanceGFM(html) {
    // המרת mentions (@username)
    html = html.replace(/@(\w+)/g, '<a href="https://github.com/$1" class="mention">@$1</a>');

    // המרת references (#123)
    html = html.replace(/#(\d+)/g, '<a href="#issue-$1" class="issue-ref">#$1</a>');

    return html;
}
```

---

## בדיקות

### Manual Testing Checklist

- [ ] לחיצה על קובץ `.md` מציגה את כפתור ה-toggle
- [ ] לחיצה על קובץ שאינו `.md` מסתירה את הכפתור
- [ ] לחיצה על הכפתור עוברת לתצוגת Markdown
- [ ] לחיצה נוספת חוזרת לתצוגת קוד
- [ ] קיצור `Ctrl+Shift+M` עובד
- [ ] העדפה נשמרת ב-localStorage
- [ ] בלוקי קוד מקבלים syntax highlighting
- [ ] Task lists מוצגים נכון
- [ ] טבלאות מוצגות נכון
- [ ] תמונות נטענות
- [ ] קישורים עובדים
- [ ] Mermaid diagrams מרונדרים (אם רלוונטי)
- [ ] תמיכה בעברית (RTL) עובדת

---

## סיכום

המימוש משתמש בתשתית הקיימת של `MarkdownLiveRenderer` מ-`live-preview.js`, מה שמבטיח:
- עקביות עיצובית עם שאר האפליקציה
- תמיכה מלאה בכל תכונות Markdown המתקדמות
- ללא צורך בהוספת תלויות חדשות

השינויים העיקריים:
1. **HTML**: כפתור toggle + container לתצוגה
2. **CSS**: עיצוב לתצוגת Markdown
3. **JS**: לוגיקת toggle ואינטגרציה עם `selectFile`

הזמן המשוער למימוש: 2-4 שעות עבודה.
