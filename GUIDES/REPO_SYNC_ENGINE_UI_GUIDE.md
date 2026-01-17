# מדריך המשך: UI מתקדם לדפדפן הקוד

> **מטרה:** בניית ממשק משתמש מודרני עם Tree View, CodeMirror, וחיפוש משולב

---

## תוכן עניינים

1. [סקירת הממשק](#סקירת-הממשק)
2. [התקנת Dependencies](#התקנת-dependencies)
3. [Base Template מעודכן](#base-template-מעודכן)
4. [Tree View Component](#tree-view-component)
5. [Code Viewer עם CodeMirror](#code-viewer-עם-codemirror)
6. [Search Bar משולב](#search-bar-משולב)
7. [CSS מלא](#css-מלא)
8. [JavaScript Components](#javascript-components)
9. [API Endpoints נוספים](#api-endpoints-נוספים)

---

## סקירת הממשק

```
┌─────────────────────────────────────────────────────────────────────┐
│  🔍 [_______________Search code..._________________] [🔎]  [⚙️]    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────┬───────────────────────────────────────────┐│
│  │  📁 Tree View       │  📄 Code Viewer                          ││
│  │                     │                                           ││
│  │  ▼ 📁 src/          │  ┌─────────────────────────────────────┐ ││
│  │    ▼ 📁 services/   │  │ 1  import logging                   │ ││
│  │      📄 git_mirror  │  │ 2  from typing import Optional      │ ││
│  │      📄 indexer     │  │ 3                                   │ ││
│  │    ▶ 📁 handlers/   │  │ 4  class GitMirrorService:          │ ││
│  │    📄 main.py       │  │ 5      """Git Mirror Service"""     │ ││
│  │  ▶ 📁 tests/        │  │ 6                                   │ ││
│  │  ▶ 📁 webapp/       │  │ 7      def __init__(self):          │ ││
│  │  📄 README.md       │  │ 8          self.path = ...          │ ││
│  │  📄 requirements.txt│  └─────────────────────────────────────┘ ││
│  │                     │                                           ││
│  │  [Stats: 5,143 files│  Path: src/services/git_mirror.py        ││
│  │   Python: 892]      │  Lines: 245 | Size: 8.2KB | Python       ││
│  └─────────────────────┴───────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────┘
```

### מה נבנה:

| רכיב | תיאור | טכנולוגיה |
|------|-------|-----------|
| **Tree View** | עץ תיקיות וקבצים מתקפל | Vanilla JS + CSS |
| **Code Viewer** | תצוגת קוד עם Syntax Highlighting | CodeMirror 6 |
| **Search Bar** | חיפוש מהיר עם autocomplete | JS + API |
| **Split Pane** | חלוקה גמישה בין tree לקוד | CSS Grid + Resize |
| **Breadcrumbs** | ניווט בנתיב הקובץ | Bootstrap |
| **File Icons** | אייקונים לפי סוג קובץ | Font Awesome / Custom |

---

## התקנת Dependencies

### 1. עדכון requirements.txt

```txt
# כבר קיים (אין צורך בחבילות פייתון נוספות ל-UI)
```

### 2. CDN Dependencies (ב-HTML)

```html
<!-- CodeMirror 6 -->
<script type="module">
  import {EditorView, basicSetup} from "https://cdn.jsdelivr.net/npm/codemirror@6/dist/index.js";
  import {python} from "https://cdn.jsdelivr.net/npm/@codemirror/lang-python@6/dist/index.js";
  import {javascript} from "https://cdn.jsdelivr.net/npm/@codemirror/lang-javascript@6/dist/index.js";
  import {html} from "https://cdn.jsdelivr.net/npm/@codemirror/lang-html@6/dist/index.js";
  import {css} from "https://cdn.jsdelivr.net/npm/@codemirror/lang-css@6/dist/index.js";
  import {json} from "https://cdn.jsdelivr.net/npm/@codemirror/lang-json@6/dist/index.js";
  import {markdown} from "https://cdn.jsdelivr.net/npm/@codemirror/lang-markdown@6/dist/index.js";
  import {oneDark} from "https://cdn.jsdelivr.net/npm/@codemirror/theme-one-dark@6/dist/index.js";
</script>

<!-- או גרסה פשוטה יותר עם CodeMirror 5 -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/theme/dracula.min.css">
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/python/python.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/javascript/javascript.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/htmlmixed/htmlmixed.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/css/css.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/yaml/yaml.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/markdown/markdown.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/shell/shell.min.js"></script>

<!-- Bootstrap Icons -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.1/font/bootstrap-icons.css">
```

---

## Base Template מעודכן

צור קובץ `webapp/templates/repo/base_repo.html`:

```html
{% extends "base.html" %}

{% block extra_head %}
<!-- CodeMirror 5 (פשוט יותר לשימוש) -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/theme/dracula.min.css">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/fold/foldgutter.min.css">

<!-- Custom Repo Browser Styles -->
<link rel="stylesheet" href="{{ url_for('static', filename='css/repo-browser.css') }}">
{% endblock %}

{% block content %}
<div class="repo-browser-container">
    <!-- Top Search Bar -->
    <div class="repo-search-bar">
        <div class="search-wrapper">
            <i class="bi bi-search search-icon"></i>
            <input type="text" 
                   id="global-search" 
                   class="search-input" 
                   placeholder="חפש קבצים, פונקציות, קוד... (Ctrl+K)"
                   autocomplete="off">
            <div class="search-shortcuts">
                <kbd>Ctrl</kbd><kbd>K</kbd>
            </div>
        </div>
        <div class="repo-info">
            <span class="repo-name">
                <i class="bi bi-github"></i>
                {{ repo_name }}
            </span>
            {% if metadata %}
            <span class="repo-stats">
                <i class="bi bi-file-code"></i> {{ metadata.total_files | default(0) }} files
            </span>
            {% endif %}
        </div>
    </div>

    <!-- Search Results Dropdown -->
    <div id="search-results-dropdown" class="search-results-dropdown hidden">
        <div class="search-results-list"></div>
    </div>

    <!-- Main Content: Split Pane -->
    <div class="repo-main-content">
        <!-- Left: Tree View -->
        <div class="repo-sidebar" id="repo-sidebar">
            <div class="sidebar-header">
                <span class="sidebar-title">
                    <i class="bi bi-folder2-open"></i>
                    Explorer
                </span>
                <button class="btn-icon" id="collapse-all" title="Collapse All">
                    <i class="bi bi-arrows-collapse"></i>
                </button>
            </div>
            <div class="tree-view-container" id="tree-view">
                {% block tree_content %}
                <!-- Tree will be loaded here -->
                <div class="loading-tree">
                    <div class="spinner-border spinner-border-sm" role="status"></div>
                    <span>Loading...</span>
                </div>
                {% endblock %}
            </div>
            <div class="sidebar-footer">
                {% if metadata %}
                <div class="stats-mini">
                    <span title="Python files"><i class="bi bi-filetype-py"></i> {{ metadata.get('file_types', {}).get('.py', 0) }}</span>
                    <span title="JavaScript files"><i class="bi bi-filetype-js"></i> {{ metadata.get('file_types', {}).get('.js', 0) }}</span>
                    <span title="Total"><i class="bi bi-files"></i> {{ metadata.total_files | default(0) }}</span>
                </div>
                {% endif %}
            </div>
        </div>

        <!-- Resizer -->
        <div class="resizer" id="sidebar-resizer"></div>

        <!-- Right: Code Viewer -->
        <div class="repo-content" id="repo-content">
            {% block code_content %}
            <!-- Content will be loaded here -->
            <div class="welcome-screen">
                <div class="welcome-icon">
                    <i class="bi bi-code-square"></i>
                </div>
                <h3>ברוכים הבאים לדפדפן הקוד</h3>
                <p>בחר קובץ מהעץ משמאל, או השתמש בחיפוש למעלה</p>
                <div class="quick-actions">
                    <button class="btn btn-outline-primary" onclick="focusSearch()">
                        <i class="bi bi-search"></i>
                        חפש (Ctrl+K)
                    </button>
                </div>
            </div>
            {% endblock %}
        </div>
    </div>
</div>

<!-- CodeMirror Scripts -->
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/codemirror.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/python/python.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/javascript/javascript.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/htmlmixed/htmlmixed.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/xml/xml.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/css/css.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/yaml/yaml.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/markdown/markdown.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/shell/shell.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/mode/sql/sql.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/fold/foldcode.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/fold/foldgutter.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/fold/brace-fold.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/codemirror/5.65.16/addon/fold/indent-fold.min.js"></script>

<!-- Custom Scripts -->
<script src="{{ url_for('static', filename='js/repo-browser.js') }}"></script>
{% endblock %}
```

---

## Tree View Component

צור קובץ `webapp/templates/repo/index.html`:

```html
{% extends "repo/base_repo.html" %}

{% block tree_content %}
<div class="tree-view" id="file-tree">
    <!-- Tree will be populated by JavaScript -->
</div>
{% endblock %}

{% block code_content %}
<div class="code-viewer-container" id="code-viewer-container">
    <!-- Breadcrumbs -->
    <div class="code-header" id="code-header" style="display: none;">
        <nav aria-label="breadcrumb" class="file-breadcrumb">
            <ol class="breadcrumb" id="file-breadcrumb">
                <!-- Populated by JS -->
            </ol>
        </nav>
        <div class="file-actions">
            <button class="btn-icon" id="copy-path" title="Copy path">
                <i class="bi bi-clipboard"></i>
            </button>
            <button class="btn-icon" id="copy-content" title="Copy content">
                <i class="bi bi-files"></i>
            </button>
            <a class="btn-icon" id="github-link" href="#" target="_blank" title="View on GitHub">
                <i class="bi bi-github"></i>
            </a>
        </div>
    </div>

    <!-- Code Editor Container -->
    <div class="code-editor-wrapper" id="code-editor-wrapper" style="display: none;">
        <textarea id="code-editor"></textarea>
    </div>

    <!-- File Info Footer -->
    <div class="code-footer" id="code-footer" style="display: none;">
        <span class="file-info" id="file-info">
            <!-- Lines: 245 | Size: 8.2KB | Python -->
        </span>
    </div>

    <!-- Welcome Screen (shown when no file selected) -->
    <div class="welcome-screen" id="welcome-screen">
        <div class="welcome-icon">
            <i class="bi bi-code-square"></i>
        </div>
        <h3>ברוכים הבאים לדפדפן הקוד</h3>
        <p>בחר קובץ מהעץ משמאל, או השתמש בחיפוש למעלה</p>
        <div class="quick-actions">
            <button class="btn btn-outline-primary" onclick="focusSearch()">
                <i class="bi bi-search"></i>
                חפש קובץ (Ctrl+K)
            </button>
        </div>
        
        <!-- Recent Files -->
        <div class="recent-files" id="recent-files">
            <h5><i class="bi bi-clock-history"></i> קבצים אחרונים</h5>
            <ul class="recent-files-list" id="recent-files-list">
                <!-- Populated from localStorage -->
            </ul>
        </div>
    </div>
</div>
{% endblock %}
```

---

## CSS מלא

צור קובץ `webapp/static/css/repo-browser.css`:

```css
/* ========================================
   Repo Browser - Modern UI Styles
   ======================================== */

:root {
    --sidebar-width: 280px;
    --sidebar-min-width: 200px;
    --sidebar-max-width: 500px;
    --header-height: 56px;
    --search-height: 52px;
    --footer-height: 32px;
    
    /* Colors - Dark Theme */
    --bg-primary: #1e1e2e;
    --bg-secondary: #181825;
    --bg-tertiary: #11111b;
    --bg-hover: #313244;
    --bg-active: #45475a;
    
    --text-primary: #cdd6f4;
    --text-secondary: #a6adc8;
    --text-muted: #6c7086;
    
    --accent-blue: #89b4fa;
    --accent-green: #a6e3a1;
    --accent-yellow: #f9e2af;
    --accent-red: #f38ba8;
    --accent-purple: #cba6f7;
    --accent-teal: #94e2d5;
    
    --border-color: #313244;
    --scrollbar-thumb: #45475a;
    --scrollbar-track: #1e1e2e;
}

/* Light theme override */
[data-theme="light"] {
    --bg-primary: #eff1f5;
    --bg-secondary: #e6e9ef;
    --bg-tertiary: #dce0e8;
    --bg-hover: #ccd0da;
    --bg-active: #bcc0cc;
    
    --text-primary: #4c4f69;
    --text-secondary: #5c5f77;
    --text-muted: #8c8fa1;
    
    --border-color: #ccd0da;
}

/* ========================================
   Layout
   ======================================== */

.repo-browser-container {
    display: flex;
    flex-direction: column;
    height: calc(100vh - var(--header-height));
    background: var(--bg-primary);
    color: var(--text-primary);
    overflow: hidden;
}

/* Search Bar */
.repo-search-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
    height: var(--search-height);
    gap: 16px;
}

.search-wrapper {
    flex: 1;
    max-width: 600px;
    position: relative;
    display: flex;
    align-items: center;
}

.search-icon {
    position: absolute;
    left: 12px;
    color: var(--text-muted);
    font-size: 14px;
}

.search-input {
    width: 100%;
    padding: 8px 12px 8px 36px;
    background: var(--bg-tertiary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    color: var(--text-primary);
    font-size: 14px;
    transition: all 0.2s ease;
}

.search-input:focus {
    outline: none;
    border-color: var(--accent-blue);
    box-shadow: 0 0 0 3px rgba(137, 180, 250, 0.2);
}

.search-input::placeholder {
    color: var(--text-muted);
}

.search-shortcuts {
    position: absolute;
    right: 12px;
    display: flex;
    gap: 4px;
}

.search-shortcuts kbd {
    padding: 2px 6px;
    background: var(--bg-hover);
    border-radius: 4px;
    font-size: 11px;
    color: var(--text-muted);
    border: 1px solid var(--border-color);
}

.repo-info {
    display: flex;
    align-items: center;
    gap: 16px;
    font-size: 13px;
}

.repo-name {
    display: flex;
    align-items: center;
    gap: 6px;
    color: var(--text-primary);
    font-weight: 500;
}

.repo-stats {
    color: var(--text-muted);
    display: flex;
    align-items: center;
    gap: 4px;
}

/* Search Results Dropdown */
.search-results-dropdown {
    position: absolute;
    top: var(--search-height);
    left: 16px;
    right: 16px;
    max-width: 700px;
    max-height: 400px;
    background: var(--bg-secondary);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.3);
    z-index: 1000;
    overflow: hidden;
}

.search-results-dropdown.hidden {
    display: none;
}

.search-results-list {
    max-height: 380px;
    overflow-y: auto;
}

.search-result-item {
    padding: 10px 14px;
    cursor: pointer;
    border-bottom: 1px solid var(--border-color);
    transition: background 0.15s ease;
}

.search-result-item:hover,
.search-result-item.active {
    background: var(--bg-hover);
}

.search-result-item:last-child {
    border-bottom: none;
}

.search-result-path {
    font-size: 13px;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 8px;
}

.search-result-path .file-icon {
    color: var(--accent-blue);
}

.search-result-preview {
    font-size: 12px;
    color: var(--text-muted);
    margin-top: 4px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.search-result-preview mark {
    background: var(--accent-yellow);
    color: var(--bg-primary);
    padding: 0 2px;
    border-radius: 2px;
}

.search-result-line {
    font-size: 11px;
    color: var(--text-muted);
    background: var(--bg-tertiary);
    padding: 2px 6px;
    border-radius: 4px;
    margin-left: auto;
}

/* Main Content Area */
.repo-main-content {
    display: flex;
    flex: 1;
    overflow: hidden;
}

/* ========================================
   Sidebar / Tree View
   ======================================== */

.repo-sidebar {
    width: var(--sidebar-width);
    min-width: var(--sidebar-min-width);
    max-width: var(--sidebar-max-width);
    background: var(--bg-secondary);
    border-right: 1px solid var(--border-color);
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

.sidebar-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 14px;
    border-bottom: 1px solid var(--border-color);
    background: var(--bg-tertiary);
}

.sidebar-title {
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--text-secondary);
    display: flex;
    align-items: center;
    gap: 8px;
}

.btn-icon {
    background: transparent;
    border: none;
    color: var(--text-muted);
    padding: 4px 8px;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.15s ease;
}

.btn-icon:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
}

.tree-view-container {
    flex: 1;
    overflow-y: auto;
    overflow-x: hidden;
    padding: 8px 0;
}

/* Tree Node Styles */
.tree-node {
    user-select: none;
}

.tree-item {
    display: flex;
    align-items: center;
    padding: 4px 8px 4px 0;
    cursor: pointer;
    color: var(--text-secondary);
    font-size: 13px;
    transition: all 0.1s ease;
    white-space: nowrap;
}

.tree-item:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
}

.tree-item.active {
    background: var(--bg-active);
    color: var(--text-primary);
}

.tree-item.selected {
    background: rgba(137, 180, 250, 0.15);
    color: var(--accent-blue);
}

.tree-indent {
    display: inline-block;
    width: 16px;
    flex-shrink: 0;
}

.tree-toggle {
    width: 16px;
    height: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    color: var(--text-muted);
    transition: transform 0.15s ease;
}

.tree-toggle.expanded {
    transform: rotate(90deg);
}

.tree-toggle.hidden {
    visibility: hidden;
}

.tree-icon {
    width: 18px;
    height: 18px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-right: 6px;
    flex-shrink: 0;
    font-size: 14px;
}

/* Folder Icons */
.tree-icon.folder {
    color: var(--accent-yellow);
}

.tree-icon.folder-open {
    color: var(--accent-yellow);
}

/* File Icons by Type */
.tree-icon.file-python { color: #3776ab; }
.tree-icon.file-javascript { color: #f7df1e; }
.tree-icon.file-typescript { color: #3178c6; }
.tree-icon.file-html { color: #e34f26; }
.tree-icon.file-css { color: #1572b6; }
.tree-icon.file-json { color: #cbcb41; }
.tree-icon.file-markdown { color: #083fa1; }
.tree-icon.file-yaml { color: #cb171e; }
.tree-icon.file-shell { color: var(--accent-green); }
.tree-icon.file-sql { color: #336791; }
.tree-icon.file-default { color: var(--text-muted); }

.tree-name {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
}

.tree-children {
    display: none;
}

.tree-children.expanded {
    display: block;
}

/* Sidebar Footer */
.sidebar-footer {
    padding: 8px 12px;
    border-top: 1px solid var(--border-color);
    background: var(--bg-tertiary);
}

.stats-mini {
    display: flex;
    gap: 12px;
    font-size: 11px;
    color: var(--text-muted);
}

.stats-mini span {
    display: flex;
    align-items: center;
    gap: 4px;
}

/* Resizer */
.resizer {
    width: 4px;
    background: var(--border-color);
    cursor: col-resize;
    transition: background 0.15s ease;
}

.resizer:hover,
.resizer.active {
    background: var(--accent-blue);
}

/* ========================================
   Code Viewer
   ======================================== */

.repo-content {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
    background: var(--bg-primary);
}

.code-viewer-container {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
}

/* Code Header - Breadcrumbs & Actions */
.code-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 8px 16px;
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border-color);
    min-height: 40px;
}

.file-breadcrumb {
    margin: 0;
}

.file-breadcrumb .breadcrumb {
    margin: 0;
    background: transparent;
    padding: 0;
    font-size: 13px;
}

.file-breadcrumb .breadcrumb-item {
    color: var(--text-muted);
}

.file-breadcrumb .breadcrumb-item a {
    color: var(--text-secondary);
    text-decoration: none;
    transition: color 0.15s ease;
}

.file-breadcrumb .breadcrumb-item a:hover {
    color: var(--accent-blue);
}

.file-breadcrumb .breadcrumb-item.active {
    color: var(--text-primary);
}

.file-breadcrumb .breadcrumb-item + .breadcrumb-item::before {
    content: "/";
    color: var(--text-muted);
}

.file-actions {
    display: flex;
    gap: 4px;
}

/* Code Editor Wrapper */
.code-editor-wrapper {
    flex: 1;
    overflow: hidden;
    position: relative;
}

/* CodeMirror Overrides */
.CodeMirror {
    height: 100% !important;
    font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 13px;
    line-height: 1.5;
    background: var(--bg-primary) !important;
}

.CodeMirror-gutters {
    background: var(--bg-secondary) !important;
    border-right: 1px solid var(--border-color) !important;
}

.CodeMirror-linenumber {
    color: var(--text-muted) !important;
    padding: 0 12px 0 8px !important;
}

.CodeMirror-line {
    padding-left: 8px !important;
}

/* Highlight current line */
.CodeMirror-activeline-background {
    background: var(--bg-hover) !important;
}

/* Code Footer */
.code-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 6px 16px;
    background: var(--bg-secondary);
    border-top: 1px solid var(--border-color);
    font-size: 12px;
    color: var(--text-muted);
}

.file-info {
    display: flex;
    gap: 16px;
}

.file-info span {
    display: flex;
    align-items: center;
    gap: 4px;
}

/* ========================================
   Welcome Screen
   ======================================== */

.welcome-screen {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 40px;
    text-align: center;
}

.welcome-icon {
    font-size: 64px;
    color: var(--text-muted);
    margin-bottom: 24px;
    opacity: 0.5;
}

.welcome-screen h3 {
    color: var(--text-primary);
    margin-bottom: 8px;
    font-weight: 500;
}

.welcome-screen p {
    color: var(--text-muted);
    margin-bottom: 24px;
}

.quick-actions {
    display: flex;
    gap: 12px;
}

.quick-actions .btn {
    padding: 10px 20px;
    border-radius: 8px;
    font-size: 14px;
}

/* Recent Files */
.recent-files {
    margin-top: 40px;
    width: 100%;
    max-width: 400px;
    text-align: right;
}

.recent-files h5 {
    color: var(--text-secondary);
    font-size: 13px;
    margin-bottom: 12px;
    display: flex;
    align-items: center;
    gap: 8px;
}

.recent-files-list {
    list-style: none;
    padding: 0;
    margin: 0;
}

.recent-files-list li {
    padding: 8px 12px;
    background: var(--bg-secondary);
    border-radius: 6px;
    margin-bottom: 6px;
    cursor: pointer;
    transition: all 0.15s ease;
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: var(--text-secondary);
}

.recent-files-list li:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
}

.recent-files-list li i {
    color: var(--accent-blue);
}

/* ========================================
   Loading States
   ======================================== */

.loading-tree {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 20px;
    color: var(--text-muted);
    font-size: 13px;
}

.loading-content {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
}

/* ========================================
   Scrollbars
   ======================================== */

::-webkit-scrollbar {
    width: 8px;
    height: 8px;
}

::-webkit-scrollbar-track {
    background: var(--scrollbar-track);
}

::-webkit-scrollbar-thumb {
    background: var(--scrollbar-thumb);
    border-radius: 4px;
}

::-webkit-scrollbar-thumb:hover {
    background: var(--text-muted);
}

/* ========================================
   Responsive
   ======================================== */

@media (max-width: 768px) {
    .repo-sidebar {
        position: absolute;
        left: 0;
        top: var(--search-height);
        bottom: 0;
        z-index: 100;
        transform: translateX(-100%);
        transition: transform 0.3s ease;
    }
    
    .repo-sidebar.open {
        transform: translateX(0);
    }
    
    .search-shortcuts {
        display: none;
    }
    
    .repo-info {
        display: none;
    }
}

/* ========================================
   Animations
   ======================================== */

@keyframes slideIn {
    from {
        opacity: 0;
        transform: translateX(20px);
    }
    to {
        opacity: 1;
        transform: translateX(0);
    }
}

@keyframes slideOut {
    from {
        opacity: 1;
        transform: translateX(0);
    }
    to {
        opacity: 0;
        transform: translateX(20px);
    }
}

@keyframes fadeIn {
    from { opacity: 0; }
    to { opacity: 1; }
}

@keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
}
```

---

## JavaScript Components

צור קובץ `webapp/static/js/repo-browser.js`:

```javascript
/**
 * Repo Browser - Main JavaScript Module
 * 
 * Features:
 * - Tree View with lazy loading
 * - CodeMirror integration
 * - Global search with keyboard shortcuts
 * - Resizable sidebar
 * - Recent files (localStorage)
 */

// ========================================
// Configuration
// ========================================

const CONFIG = {
    repoName: 'CodeBot',  // יוחלף דינמית
    apiBase: '/repo/api',
    maxRecentFiles: 5,
    searchDebounceMs: 300,
    modeMap: {
        'python': 'python',
        'javascript': 'javascript',
        'typescript': 'javascript',
        'html': 'htmlmixed',
        'css': 'css',
        'scss': 'css',
        'json': 'javascript',
        'yaml': 'yaml',
        'markdown': 'markdown',
        'shell': 'shell',
        'bash': 'shell',
        'sql': 'sql',
        'text': 'null'
    }
};

// ========================================
// State
// ========================================

let state = {
    currentFile: null,
    treeData: null,
    editor: null,
    expandedFolders: new Set(),
    selectedElement: null,
    searchTimeout: null
};

// ========================================
// Initialization
// ========================================

document.addEventListener('DOMContentLoaded', () => {
    initTree();
    initSearch();
    initResizer();
    initKeyboardShortcuts();
    loadRecentFiles();
});

// ========================================
// Tree View
// ========================================

async function initTree() {
    const treeContainer = document.getElementById('file-tree');
    if (!treeContainer) return;

    try {
        const response = await fetch(`${CONFIG.apiBase}/tree`);
        const data = await response.json();
        state.treeData = data;
        renderTree(treeContainer, data);
    } catch (error) {
        console.error('Failed to load tree:', error);
        treeContainer.innerHTML = `
            <div class="error-message">
                <i class="bi bi-exclamation-triangle"></i>
                <span>Failed to load file tree</span>
            </div>
        `;
    }
}

function renderTree(container, data, level = 0) {
    container.innerHTML = '';
    
    // Sort: folders first, then files, alphabetically
    const items = [...data].sort((a, b) => {
        if (a.type === 'directory' && b.type !== 'directory') return -1;
        if (a.type !== 'directory' && b.type === 'directory') return 1;
        return a.name.localeCompare(b.name);
    });

    items.forEach(item => {
        const node = createTreeNode(item, level);
        container.appendChild(node);
    });
}

function createTreeNode(item, level) {
    const node = document.createElement('div');
    node.className = 'tree-node';
    node.dataset.path = item.path;
    node.dataset.type = item.type;

    const itemEl = document.createElement('div');
    itemEl.className = 'tree-item';
    itemEl.style.paddingLeft = `${8 + level * 16}px`;

    // Toggle arrow for folders
    const toggle = document.createElement('span');
    toggle.className = `tree-toggle ${item.type !== 'directory' ? 'hidden' : ''}`;
    toggle.innerHTML = '<i class="bi bi-chevron-right"></i>';

    // Icon
    const icon = document.createElement('span');
    icon.className = `tree-icon ${getIconClass(item)}`;
    icon.innerHTML = getIcon(item);

    // Name
    const name = document.createElement('span');
    name.className = 'tree-name';
    name.textContent = item.name;

    itemEl.appendChild(toggle);
    itemEl.appendChild(icon);
    itemEl.appendChild(name);
    node.appendChild(itemEl);

    // Children container for folders
    if (item.type === 'directory') {
        const children = document.createElement('div');
        children.className = 'tree-children';
        node.appendChild(children);

        itemEl.addEventListener('click', (e) => {
            e.stopPropagation();
            toggleFolder(node, item);
        });
    } else {
        itemEl.addEventListener('click', (e) => {
            e.stopPropagation();
            selectFile(item.path, itemEl);
        });
    }

    return node;
}

async function toggleFolder(node, item) {
    const children = node.querySelector('.tree-children');
    const toggle = node.querySelector('.tree-toggle');
    const icon = node.querySelector('.tree-icon');
    const isExpanded = children.classList.contains('expanded');

    if (isExpanded) {
        // Collapse
        children.classList.remove('expanded');
        toggle.classList.remove('expanded');
        // עדכון class + innerHTML לאייקון (חשוב ל-Collapse All)
        icon.classList.remove('folder-open');
        icon.classList.add('folder');
        icon.innerHTML = '<i class="bi bi-folder-fill"></i>';
        state.expandedFolders.delete(item.path);
    } else {
        // Expand
        if (children.children.length === 0) {
            // Load children
            try {
                const response = await fetch(`${CONFIG.apiBase}/tree?path=${encodeURIComponent(item.path)}`);
                const data = await response.json();
                renderTree(children, data, getLevel(node) + 1);
            } catch (error) {
                console.error('Failed to load folder:', error);
            }
        }
        children.classList.add('expanded');
        toggle.classList.add('expanded');
        // עדכון class + innerHTML לאייקון
        icon.classList.remove('folder');
        icon.classList.add('folder-open');
        icon.innerHTML = '<i class="bi bi-folder2-open"></i>';
        state.expandedFolders.add(item.path);
    }
}

function getLevel(node) {
    let level = 0;
    let parent = node.parentElement;
    while (parent && !parent.id) {
        if (parent.classList.contains('tree-children')) {
            level++;
        }
        parent = parent.parentElement;
    }
    return level;
}

function getIconClass(item) {
    if (item.type === 'directory') {
        return 'folder';
    }
    const ext = item.name.split('.').pop().toLowerCase();
    const classes = {
        'py': 'file-python',
        'js': 'file-javascript',
        'jsx': 'file-javascript',
        'ts': 'file-typescript',
        'tsx': 'file-typescript',
        'html': 'file-html',
        'htm': 'file-html',
        'css': 'file-css',
        'scss': 'file-css',
        'json': 'file-json',
        'md': 'file-markdown',
        'yml': 'file-yaml',
        'yaml': 'file-yaml',
        'sh': 'file-shell',
        'bash': 'file-shell',
        'sql': 'file-sql'
    };
    return classes[ext] || 'file-default';
}

function getIcon(item) {
    if (item.type === 'directory') {
        return '<i class="bi bi-folder-fill"></i>';
    }
    const ext = item.name.split('.').pop().toLowerCase();
    const icons = {
        'py': '<i class="bi bi-filetype-py"></i>',
        'js': '<i class="bi bi-filetype-js"></i>',
        'jsx': '<i class="bi bi-filetype-jsx"></i>',
        'ts': '<i class="bi bi-filetype-ts"></i>',   // תוקן: היה tsx בטעות
        'tsx': '<i class="bi bi-filetype-tsx"></i>',
        'html': '<i class="bi bi-filetype-html"></i>',
        'css': '<i class="bi bi-filetype-css"></i>',
        'scss': '<i class="bi bi-filetype-scss"></i>',
        'json': '<i class="bi bi-filetype-json"></i>',
        'md': '<i class="bi bi-filetype-md"></i>',
        'yml': '<i class="bi bi-filetype-yml"></i>',
        'yaml': '<i class="bi bi-filetype-yml"></i>',
        'sh': '<i class="bi bi-terminal"></i>',
        'sql': '<i class="bi bi-filetype-sql"></i>'
    };
    return icons[ext] || '<i class="bi bi-file-earmark-code"></i>';
}

// ========================================
// File Selection & CodeMirror
// ========================================

async function selectFile(path, element) {
    // Update selection UI
    if (state.selectedElement) {
        state.selectedElement.classList.remove('selected');
    }
    if (element) {
        element.classList.add('selected');
        state.selectedElement = element;
    }

    state.currentFile = path;

    // Show loading
    const wrapper = document.getElementById('code-editor-wrapper');
    const welcome = document.getElementById('welcome-screen');
    const header = document.getElementById('code-header');
    const footer = document.getElementById('code-footer');

    welcome.style.display = 'none';
    wrapper.style.display = 'block';
    header.style.display = 'flex';
    footer.style.display = 'flex';

    try {
        // Fetch file content
        const response = await fetch(`${CONFIG.apiBase}/file/${encodeURIComponent(path)}`);
        const data = await response.json();

        if (data.error) {
            throw new Error(data.error);
        }

        // Update breadcrumbs
        updateBreadcrumbs(path);

        // Update file info
        updateFileInfo(data);

        // Initialize or update CodeMirror
        initCodeMirror(data.content, data.language || detectLanguage(path));

        // Save to recent files
        addToRecentFiles(path);

    } catch (error) {
        console.error('Failed to load file:', error);
        wrapper.innerHTML = `
            <div class="error-message" style="padding: 20px; color: var(--accent-red);">
                <i class="bi bi-exclamation-triangle"></i>
                <span>Failed to load file: ${error.message}</span>
            </div>
        `;
    }
}

function initCodeMirror(content, language) {
    const textarea = document.getElementById('code-editor');
    
    // Destroy existing editor
    if (state.editor) {
        state.editor.toTextArea();
    }

    // Get mode from language
    const mode = CONFIG.modeMap[language] || 'null';

    // Create new editor
    state.editor = CodeMirror.fromTextArea(textarea, {
        value: content,
        mode: mode,
        theme: 'dracula',
        lineNumbers: true,
        readOnly: true,
        lineWrapping: false,
        foldGutter: true,
        gutters: ['CodeMirror-linenumbers', 'CodeMirror-foldgutter'],
        styleActiveLine: true,
        matchBrackets: true,
        autoCloseBrackets: true,
        tabSize: 4,
        indentUnit: 4
    });

    state.editor.setValue(content);
    state.editor.refresh();
}

function detectLanguage(path) {
    const ext = path.split('.').pop().toLowerCase();
    const langMap = {
        'py': 'python',
        'js': 'javascript',
        'jsx': 'javascript',
        'ts': 'typescript',
        'tsx': 'typescript',
        'html': 'html',
        'htm': 'html',
        'css': 'css',
        'scss': 'css',
        'json': 'json',
        'md': 'markdown',
        'yml': 'yaml',
        'yaml': 'yaml',
        'sh': 'shell',
        'bash': 'shell',
        'sql': 'sql'
    };
    return langMap[ext] || 'text';
}

function updateBreadcrumbs(path) {
    const breadcrumb = document.getElementById('file-breadcrumb');
    const parts = path.split('/');
    
    breadcrumb.innerHTML = parts.map((part, index) => {
        const isLast = index === parts.length - 1;
        const partPath = parts.slice(0, index + 1).join('/');
        
        if (isLast) {
            return `<li class="breadcrumb-item active">${part}</li>`;
        }
        return `<li class="breadcrumb-item"><a href="#" onclick="navigateToFolder('${partPath}')">${part}</a></li>`;
    }).join('');

    // Update copy button
    document.getElementById('copy-path').onclick = () => {
        navigator.clipboard.writeText(path);
        showToast('Path copied!');
    };
}

function updateFileInfo(data) {
    const info = document.getElementById('file-info');
    const lines = data.content ? data.content.split('\n').length : 0;
    const size = data.content ? formatBytes(data.content.length) : '0 B';
    const lang = data.language || 'text';
    
    info.innerHTML = `
        <span><i class="bi bi-list-ol"></i> ${lines} lines</span>
        <span><i class="bi bi-hdd"></i> ${size}</span>
        <span><i class="bi bi-code"></i> ${lang}</span>
    `;
}

function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

// ========================================
// Search
// ========================================

function initSearch() {
    const searchInput = document.getElementById('global-search');
    const dropdown = document.getElementById('search-results-dropdown');
    const resultsList = dropdown.querySelector('.search-results-list');

    if (!searchInput) return;

    searchInput.addEventListener('input', (e) => {
        clearTimeout(state.searchTimeout);
        const query = e.target.value.trim();

        if (query.length < 2) {
            dropdown.classList.add('hidden');
            return;
        }

        state.searchTimeout = setTimeout(async () => {
            try {
                const response = await fetch(`${CONFIG.apiBase}/search?q=${encodeURIComponent(query)}&type=content`);
                const data = await response.json();
                
                renderSearchResults(resultsList, data.results || [], query);
                dropdown.classList.remove('hidden');
            } catch (error) {
                console.error('Search failed:', error);
            }
        }, CONFIG.searchDebounceMs);
    });

    searchInput.addEventListener('focus', () => {
        if (searchInput.value.length >= 2) {
            dropdown.classList.remove('hidden');
        }
    });

    // Close dropdown when clicking outside
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.search-wrapper') && !e.target.closest('.search-results-dropdown')) {
            dropdown.classList.add('hidden');
        }
    });
}

function renderSearchResults(container, results, query) {
    if (results.length === 0) {
        container.innerHTML = `
            <div class="search-result-item">
                <span class="text-muted">No results found</span>
            </div>
        `;
        return;
    }

    container.innerHTML = results.slice(0, 20).map(result => {
        const highlightedContent = result.content 
            ? highlightMatch(result.content, query)
            : '';
        
        return `
            <div class="search-result-item" onclick="selectFile('${result.path}')">
                <div class="search-result-path">
                    <span class="file-icon">${getIcon({name: result.path, type: 'file'})}</span>
                    <span>${result.path}</span>
                    ${result.line ? `<span class="search-result-line">L${result.line}</span>` : ''}
                </div>
                ${highlightedContent ? `<div class="search-result-preview">${highlightedContent}</div>` : ''}
            </div>
        `;
    }).join('');
}

function highlightMatch(text, query) {
    const escaped = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const regex = new RegExp(`(${escaped})`, 'gi');
    return text.replace(regex, '<mark>$1</mark>');
}

function focusSearch() {
    const searchInput = document.getElementById('global-search');
    if (searchInput) {
        searchInput.focus();
        searchInput.select();
    }
}

// ========================================
// Keyboard Shortcuts
// ========================================

function initKeyboardShortcuts() {
    document.addEventListener('keydown', (e) => {
        // Ctrl+K or Cmd+K - Focus search
        if ((e.ctrlKey || e.metaKey) && e.key === 'k') {
            e.preventDefault();
            focusSearch();
        }
        
        // Escape - Close search dropdown
        if (e.key === 'Escape') {
            const dropdown = document.getElementById('search-results-dropdown');
            dropdown?.classList.add('hidden');
        }
    });
}

// ========================================
// Resizable Sidebar
// ========================================

function initResizer() {
    const resizer = document.getElementById('sidebar-resizer');
    const sidebar = document.getElementById('repo-sidebar');
    
    if (!resizer || !sidebar) return;

    let isResizing = false;
    let startX, startWidth;

    resizer.addEventListener('mousedown', (e) => {
        isResizing = true;
        startX = e.clientX;
        startWidth = sidebar.offsetWidth;
        resizer.classList.add('active');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });

    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        
        const width = startWidth + (e.clientX - startX);
        const minWidth = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-min-width'));
        const maxWidth = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--sidebar-max-width'));
        
        if (width >= minWidth && width <= maxWidth) {
            sidebar.style.width = `${width}px`;
        }
    });

    document.addEventListener('mouseup', () => {
        if (isResizing) {
            isResizing = false;
            resizer.classList.remove('active');
            document.body.style.cursor = '';
            document.body.style.userSelect = '';
        }
    });
}

// ========================================
// Recent Files
// ========================================

function loadRecentFiles() {
    const container = document.getElementById('recent-files-list');
    if (!container) return;

    const recent = getRecentFiles();
    
    if (recent.length === 0) {
        container.innerHTML = '<li class="text-muted" style="cursor: default;">No recent files</li>';
        return;
    }

    container.innerHTML = recent.map(path => `
        <li onclick="selectFile('${path}')">
            ${getIcon({name: path, type: 'file'})}
            <span>${path.split('/').pop()}</span>
        </li>
    `).join('');
}

function getRecentFiles() {
    try {
        return JSON.parse(localStorage.getItem('recentFiles') || '[]');
    } catch {
        return [];
    }
}

function addToRecentFiles(path) {
    let recent = getRecentFiles();
    recent = recent.filter(p => p !== path);
    recent.unshift(path);
    recent = recent.slice(0, CONFIG.maxRecentFiles);
    localStorage.setItem('recentFiles', JSON.stringify(recent));
    loadRecentFiles();
}

// ========================================
// Utilities
// ========================================

function showToast(message, duration = 2000) {
    const toast = document.createElement('div');
    toast.className = 'toast-message';
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        padding: 12px 20px;
        background: var(--bg-secondary);
        color: var(--text-primary);
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        z-index: 9999;
        animation: slideIn 0.3s ease;
    `;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, duration);
}

function navigateToFolder(path) {
    // Find and expand the folder in tree
    const node = document.querySelector(`[data-path="${path}"]`);
    if (node) {
        const item = node.querySelector('.tree-item');
        item?.click();
    }
}

// Collapse all folders
document.getElementById('collapse-all')?.addEventListener('click', () => {
    // Remove expanded class from children containers
    document.querySelectorAll('.tree-children.expanded').forEach(el => {
        el.classList.remove('expanded');
    });
    
    // Remove expanded class from toggle arrows
    document.querySelectorAll('.tree-toggle.expanded').forEach(el => {
        el.classList.remove('expanded');
    });
    
    // Reset folder icons from open to closed
    // תיקון: בלי זה, האייקונים נשארים פתוחים למרות שהתיקייה סגורה
    document.querySelectorAll('.tree-icon.folder-open').forEach(el => {
        el.classList.remove('folder-open');
        el.classList.add('folder');
        el.innerHTML = '<i class="bi bi-folder-fill"></i>';
    });
    
    // Clear state
    state.expandedFolders.clear();
});
```

---

## API Endpoints נוספים

עדכן את `webapp/routes/repo_browser.py`:

```python
"""
Repository Browser Routes - Extended API

UI לגלישה בקוד הריפו עם API מתקדם
"""

import logging
import re
from flask import Blueprint, render_template, request, jsonify, abort
from functools import lru_cache

from services.git_mirror_service import get_mirror_service
from services.repo_search_service import create_search_service
from database.db_manager import get_db

logger = logging.getLogger(__name__)

repo_bp = Blueprint('repo', __name__, url_prefix='/repo')


@repo_bp.route('/')
def repo_index():
    """דף ראשי של דפדפן הקוד"""
    db = get_db()
    git_service = get_mirror_service()
    
    repo_name = "CodeBot"
    
    metadata = db.repo_metadata.find_one({"repo_name": repo_name})
    mirror_info = git_service.get_mirror_info(repo_name)
    
    # Get file type stats
    if metadata:
        file_types = {}
        cursor = db.repo_files.aggregate([
            {"$match": {"repo_name": repo_name}},
            {"$group": {"_id": "$language", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}},
            {"$limit": 10}
        ])
        for doc in cursor:
            if doc["_id"]:
                file_types[doc["_id"]] = doc["count"]
        metadata["file_types"] = file_types
    
    return render_template(
        'repo/index.html',
        repo_name=repo_name,
        metadata=metadata,
        mirror_info=mirror_info
    )


@repo_bp.route('/api/tree')
def api_tree():
    """
    API לקבלת עץ הקבצים
    
    Query params:
        path: נתיב לתיקייה ספציפית (אופציונלי)
    """
    db = get_db()
    repo_name = "CodeBot"
    path = request.args.get('path', '')
    
    # Build tree from MongoDB
    if path:
        # Get children of specific folder
        safe_path = re.escape(path)
        pattern = f"^{safe_path}/[^/]+$"
    else:
        # Get root level
        pattern = "^[^/]+$"
    
    # Get files matching pattern
    files = list(db.repo_files.find(
        {
            "repo_name": repo_name,
            "path": {"$regex": pattern}
        },
        {"path": 1, "language": 1, "size": 1, "lines": 1}
    ).sort("path", 1))
    
    # Get all paths to find directories
    all_paths = db.repo_files.distinct("path", {"repo_name": repo_name})
    
    # Extract unique directories at this level
    directories = set()
    prefix = path + "/" if path else ""
    prefix_len = len(prefix)
    
    for p in all_paths:
        if p.startswith(prefix):
            remaining = p[prefix_len:]
            if "/" in remaining:
                dir_name = remaining.split("/")[0]
                directories.add(dir_name)
    
    # Build result
    result = []
    
    # Add directories first
    for dir_name in sorted(directories):
        dir_path = f"{path}/{dir_name}" if path else dir_name
        result.append({
            "name": dir_name,
            "path": dir_path,
            "type": "directory"
        })
    
    # Add files
    for f in files:
        name = f["path"].split("/")[-1]
        result.append({
            "name": name,
            "path": f["path"],
            "type": "file",
            "language": f.get("language", "text"),
            "size": f.get("size", 0),
            "lines": f.get("lines", 0)
        })
    
    return jsonify(result)


@repo_bp.route('/api/file/<path:file_path>')
def api_get_file(file_path: str):
    """API לקבלת תוכן קובץ"""
    db = get_db()
    git_service = get_mirror_service()
    repo_name = "CodeBot"
    
    # Get metadata from MongoDB
    metadata = db.repo_files.find_one({
        "repo_name": repo_name,
        "path": file_path
    })
    
    # Get content from git mirror
    content = git_service.get_file_content(repo_name, file_path)
    
    if content is None:
        return jsonify({"error": "File not found"}), 404
    
    return jsonify({
        "path": file_path,
        "content": content,
        "language": metadata.get("language", "text") if metadata else "text",
        "size": metadata.get("size", len(content)) if metadata else len(content),
        "lines": metadata.get("lines", content.count("\n") + 1) if metadata else content.count("\n") + 1
    })


@repo_bp.route('/api/search')
def api_search():
    """API לחיפוש משופר"""
    query = request.args.get('q', '')
    search_type = request.args.get('type', 'content')
    file_pattern = request.args.get('pattern', '')
    language = request.args.get('language', '')
    
    if not query or len(query) < 2:
        return jsonify({"error": "Query too short", "results": []})
    
    db = get_db()
    search_service = create_search_service(db)
    repo_name = "CodeBot"
    
    result = search_service.search(
        repo_name=repo_name,
        query=query,
        search_type=search_type,
        file_pattern=file_pattern or None,
        language=language or None,
        max_results=50
    )
    
    return jsonify(result)


@repo_bp.route('/api/stats')
def api_stats():
    """API לסטטיסטיקות"""
    db = get_db()
    git_service = get_mirror_service()
    repo_name = "CodeBot"
    
    # Get from git service
    stats = git_service.get_repo_stats(repo_name)
    
    if stats is None:
        return jsonify({"error": "Stats not available"}), 404
    
    # Enrich with MongoDB stats
    metadata = db.repo_metadata.find_one({"repo_name": repo_name})
    if metadata:
        stats["last_sync"] = metadata.get("last_sync_time")
        stats["sync_status"] = metadata.get("sync_status")
    
    return jsonify(stats)
```

---

## סיכום

### מה נבנה:

1. **Tree View מודרני**
   - אייקונים לפי סוג קובץ
   - טעינה מדורגת (lazy loading)
   - קיפול/פתיחה אנימטיבי

2. **Code Viewer עם CodeMirror**
   - Syntax highlighting לכל השפות
   - מספרי שורות
   - Code folding
   - Theme כהה (Dracula)

3. **Search Bar משולב**
   - חיפוש בזמן אמת
   - Keyboard shortcuts (Ctrl+K)
   - תצוגת תוצאות עם preview

4. **UI מודרני**
   - Theme כהה מקצועי (Catppuccin inspired)
   - Split pane עם resize
   - Breadcrumbs לניווט
   - Recent files

5. **Responsive**
   - Mobile friendly
   - Sidebar מתקפל

### קבצים שנוצרו:

```
webapp/
├── templates/
│   └── repo/
│       ├── base_repo.html
│       └── index.html
├── static/
│   ├── css/
│   │   └── repo-browser.css
│   └── js/
│       └── repo-browser.js
└── routes/
    └── repo_browser.py (updated)
```

---

*מדריך זה הוא המשך ל-REPO_SYNC_ENGINE_GUIDE.md*
