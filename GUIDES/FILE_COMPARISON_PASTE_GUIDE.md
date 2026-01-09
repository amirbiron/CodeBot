# מדריך מימוש: השוואת קבצים בהדבקה (Paste Compare) 📋🔍

> **תיאור**: מדריך להרחבת פיצ'ר השוואת הקבצים כך שיתמוך גם בהשוואת קוד שמודבק ישירות (לא שמור במערכת).
>
> **מצב נוכחי**: קיימת תשתית מלאה להשוואת קבצים/גרסאות שמורים במערכת.
>
> **הרחבה נדרשת**: הוספת ממשק להדבקת קוד חופשי משני מקורות.

---

## תוכן עניינים

- [סקירת המצב הנוכחי](#סקירת-המצב-הנוכחי)
- [מה קיים ב-Backend](#מה-קיים-ב-backend)
- [ארכיטקטורת ההרחבה](#ארכיטקטורת-ההרחבה)
- [שינויים נדרשים](#שינויים-נדרשים)
  - [1. Route חדש](#1-route-חדש)
  - [2. Template חדש](#2-template-חדש)
  - [3. הרחבת JavaScript](#3-הרחבת-javascript)
  - [4. CSS נוסף (אופציונלי)](#4-css-נוסף-אופציונלי)
- [ניווט ואינטגרציה](#ניווט-ואינטגרציה)
- [צ'קליסט מימוש](#צקליסט-מימוש)
- [שיקולי UX](#שיקולי-ux)
- [בדיקות](#בדיקות)

---

## סקירת המצב הנוכחי

### מבנה הפיצ'ר הקיים

הפרויקט כבר מכיל מערכת השוואה מלאה:

| רכיב | מיקום | תפקיד |
|------|-------|-------|
| **DiffService** | `services/diff_service.py` | לוגיקת השוואה (difflib) |
| **Compare API** | `webapp/app.py` (שורות 2642-2750) | REST endpoints |
| **compare.html** | `webapp/templates/compare.html` | השוואת גרסאות של קובץ |
| **compare_files.html** | `webapp/templates/compare_files.html` | השוואת קבצים שמורים |
| **compare.js** | `webapp/static/js/compare.js` | Frontend logic |
| **compare.css** | `webapp/static/css/compare.css` | עיצוב |

### מצבי השוואה קיימים

```
┌─────────────────────────────────────────────────────────────┐
│                    מצבי השוואה קיימים                        │
├─────────────────────────────────────────────────────────────┤
│  1. השוואת גרסאות (versions)                                │
│     └── /compare/<file_id>                                  │
│     └── בין גרסאות שונות של אותו קובץ שמור                  │
│                                                             │
│  2. השוואת קבצים (files)                                    │
│     └── /compare                                            │
│     └── בין שני קבצים שונים שמורים במערכת                   │
│                                                             │
│  3. [חדש] השוואה בהדבקה (paste) ← צריך לממש                 │
│     └── /compare/paste                                      │
│     └── בין שני קטעי קוד שהמשתמש מדביק ישירות              │
└─────────────────────────────────────────────────────────────┘
```

---

## מה קיים ב-Backend

### ה-API כבר קיים! ✅

**חדשות טובות**: ה-endpoint הנדרש כבר ממומש ב-`webapp/app.py`:

```python
@compare_bp.route('/diff', methods=['POST'])
def compare_raw():
    """
    השוואה בין שני טקסטים גולמיים.
    """
    data = request.get_json() or {}
    left_content = data.get('left_content', '')
    right_content = data.get('right_content', '')

    diff_service = get_diff_service()
    result = diff_service.compute_diff(left_content, right_content)

    return jsonify(result.to_dict())
```

### שימוש ב-API

```bash
# בדיקת ה-API הקיים
curl -X POST http://localhost:5000/api/compare/diff \
  -H "Content-Type: application/json" \
  -d '{
    "left_content": "line1\nline2\nline3",
    "right_content": "line1\nline2_modified\nline3\nline4"
  }'
```

**תגובה צפויה:**
```json
{
  "lines": [
    {"line_num_left": 1, "line_num_right": 1, "content_left": "line1", "content_right": "line1", "change_type": "unchanged"},
    {"line_num_left": 2, "line_num_right": 2, "content_left": "line2", "content_right": "line2_modified", "change_type": "modified"},
    {"line_num_left": 3, "line_num_right": 3, "content_left": "line3", "content_right": "line3", "change_type": "unchanged"},
    {"line_num_left": null, "line_num_right": 4, "content_left": null, "content_right": "line4", "change_type": "added"}
  ],
  "stats": {"added": 1, "removed": 0, "modified": 1, "unchanged": 2},
  "left_info": {"total_lines": 3},
  "right_info": {"total_lines": 4}
}
```

---

## ארכיטקטורת ההרחבה

```
┌─────────────────────────────────────────────────────────────────┐
│                     זרימת הפיצ'ר החדש                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────────┐                                           │
│  │ /compare/paste   │ ← Route חדש (פשוט, ללא DB)                │
│  └────────┬─────────┘                                           │
│           │                                                     │
│           ▼                                                     │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              compare_paste.html (Template חדש)            │   │
│  │  ┌─────────────────┐        ┌─────────────────┐          │   │
│  │  │   textarea      │        │   textarea      │          │   │
│  │  │   (קוד שמאלי)   │   VS   │   (קוד ימני)    │          │   │
│  │  └─────────────────┘        └─────────────────┘          │   │
│  │                                                          │   │
│  │              [ כפתור השוואה ]                             │   │
│  └──────────────────────────────────────────────────────────┘   │
│                      │                                          │
│                      │ POST /api/compare/diff                   │
│                      ▼                                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              DiffService.compute_diff()                   │   │
│  │              (קיים! לא צריך לשנות)                        │   │
│  └──────────────────────────────────────────────────────────┘   │
│                      │                                          │
│                      ▼                                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              תצוגת תוצאות (כמו compare_files)             │   │
│  │              Side-by-Side / Unified / Inline              │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## שינויים נדרשים

### 1. Route חדש

**קובץ:** `webapp/app.py`

**מיקום מוצע:** אחרי ה-route של `compare_files_page` (בערך שורה 10560)

```python
@app.route('/compare/paste')
@login_required
def compare_paste_page():
    """דף השוואת קוד בהדבקה - ללא צורך בקבצים שמורים."""
    return render_template('compare_paste.html')
```

> **הערה**: ה-route פשוט מאוד - רק מחזיר template. כל הלוגיקה קורית ב-frontend שפונה ל-API הקיים.

---

### 2. Template חדש

**קובץ:** `webapp/templates/compare_paste.html`

```html
{% extends "base.html" %}

{% block title %}השוואת קוד בהדבקה - Code Keeper Bot{% endblock %}

{% block extra_css %}
<link rel="stylesheet" href="{{ url_for('static', filename='css/compare.css') }}">
<style>
/* =================================================================
   Compare Paste Page - Specific Styles
   ================================================================= */

/* Paste Input Grid */
.paste-input-grid {
    display: grid;
    grid-template-columns: 1fr auto 1fr;
    gap: 1rem;
    margin-bottom: 1.5rem;
}

@media (max-width: 992px) {
    .paste-input-grid {
        grid-template-columns: 1fr;
        gap: 1rem;
    }
    
    .swap-column-paste {
        justify-self: center;
    }
}

/* Paste Area Wrapper */
.paste-area-wrapper {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
}

.paste-area-wrapper label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    font-weight: 600;
    color: var(--text-primary, #fff);
}

.paste-area-wrapper label i {
    font-size: 1.1rem;
}

/* Paste Textarea */
.paste-textarea {
    width: 100%;
    min-height: 300px;
    max-height: 60vh;
    padding: 1rem;
    font-family: 'Fira Code', 'Consolas', 'Monaco', 'Menlo', monospace;
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-primary, #fff);
    background: var(--glass-bg, rgba(255, 255, 255, 0.05));
    border: 1px solid var(--glass-border, rgba(255, 255, 255, 0.15));
    border-radius: 12px;
    resize: vertical;
    direction: ltr;
    text-align: left;
    tab-size: 4;
}

.paste-textarea:focus {
    outline: none;
    border-color: var(--accent-color, #6366f1);
    box-shadow: 0 0 0 3px rgba(99, 102, 241, 0.25);
}

.paste-textarea::placeholder {
    color: var(--text-muted, rgba(255, 255, 255, 0.4));
    font-family: inherit;
}

/* Left textarea accent */
.paste-area-wrapper.left-area .paste-textarea {
    border-left: 3px solid var(--bs-danger, #dc3545);
}

/* Right textarea accent */
.paste-area-wrapper.right-area .paste-textarea {
    border-left: 3px solid var(--bs-success, #28a745);
}

/* Swap Button */
.swap-column-paste {
    display: flex;
    align-items: center;
    justify-content: center;
    padding-top: 2rem;
}

.btn-swap-paste {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--glass-bg, rgba(255, 255, 255, 0.08));
    border: 1px solid var(--glass-border, rgba(255, 255, 255, 0.18));
    color: var(--text-primary, #fff);
    cursor: pointer;
    transition: all 0.3s ease;
}

.btn-swap-paste:hover {
    background: var(--accent-color, #6366f1);
    border-color: var(--accent-color, #6366f1);
    transform: rotate(180deg);
}

/* Action Bar */
.paste-action-bar {
    display: flex;
    justify-content: center;
    gap: 1rem;
    flex-wrap: wrap;
    padding: 1rem 0;
    border-top: 1px solid var(--glass-border, rgba(255, 255, 255, 0.1));
}

/* Clear Buttons */
.paste-actions-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 0.5rem;
}

.btn-clear-text {
    font-size: 0.8rem;
    padding: 0.25rem 0.5rem;
    background: transparent;
    border: 1px solid var(--glass-border, rgba(255, 255, 255, 0.2));
    border-radius: 4px;
    color: var(--text-muted, rgba(255, 255, 255, 0.6));
    cursor: pointer;
    transition: all 0.2s ease;
}

.btn-clear-text:hover {
    background: rgba(220, 53, 69, 0.2);
    border-color: var(--bs-danger, #dc3545);
    color: var(--bs-danger, #dc3545);
}

/* Character count */
.char-count {
    font-size: 0.75rem;
    color: var(--text-muted, rgba(255, 255, 255, 0.5));
}

/* Language Detection Badge */
.detected-language {
    font-size: 0.75rem;
    padding: 0.15rem 0.5rem;
    background: rgba(99, 102, 241, 0.2);
    border-radius: 4px;
    color: var(--accent-color, #6366f1);
    margin-right: auto;
}

/* Light theme */
[data-theme="light"] .paste-textarea {
    background: rgba(0, 0, 0, 0.03);
    border-color: rgba(0, 0, 0, 0.15);
    color: var(--text-primary, #1e1e2e);
}

[data-theme="light"] .btn-swap-paste {
    background: rgba(0, 0, 0, 0.05);
    border-color: rgba(0, 0, 0, 0.1);
}
</style>
{% endblock %}

{% block content %}
<div class="container-fluid py-4">
    <!-- Header -->
    <div class="compare-header glass-card p-4 mb-4">
        <div class="d-flex justify-content-between align-items-start flex-wrap gap-3 mb-4">
            <div>
                <h1 class="h3 mb-2">
                    <i class="fas fa-paste me-2"></i>
                    השוואת קוד בהדבקה
                </h1>
                <p class="text-muted mb-0">הדבק שני קטעי קוד להשוואה מיידית - ללא צורך בשמירה</p>
            </div>
            
            <!-- View Mode Toggle (shown after comparison) -->
            <div id="view-mode-toggle" class="btn-group d-none" role="group" aria-label="מצב תצוגה">
                <button type="button" class="btn btn-outline-primary active" data-mode="side-by-side">
                    <i class="fas fa-columns"></i> צד לצד
                </button>
                <button type="button" class="btn btn-outline-primary" data-mode="unified">
                    <i class="fas fa-align-left"></i> אחיד
                </button>
                <button type="button" class="btn btn-outline-primary" data-mode="inline">
                    <i class="fas fa-highlighter"></i> Inline
                </button>
            </div>
        </div>
        
        <!-- Paste Input Areas -->
        <form id="paste-compare-form">
            <div class="paste-input-grid">
                <!-- Left Code Input -->
                <div class="paste-area-wrapper left-area">
                    <label for="paste-left">
                        <i class="fas fa-file-code text-danger"></i>
                        קוד מקורי / ישן
                    </label>
                    <textarea 
                        id="paste-left" 
                        class="paste-textarea" 
                        placeholder="הדבק כאן את הקוד המקורי...&#10;&#10;דוגמה:&#10;function hello() {&#10;    console.log('Hello');&#10;}"
                        spellcheck="false"
                        autocomplete="off"
                        autocorrect="off"
                        autocapitalize="off"
                    ></textarea>
                    <div class="paste-actions-row">
                        <span class="detected-language" id="lang-left">-</span>
                        <span class="char-count" id="count-left">0 תווים</span>
                        <button type="button" class="btn-clear-text" data-target="paste-left">
                            <i class="fas fa-eraser"></i> נקה
                        </button>
                    </div>
                </div>
                
                <!-- Swap Button -->
                <div class="swap-column-paste">
                    <button type="button" id="swap-paste" class="btn-swap-paste" title="החלף צדדים">
                        <i class="fas fa-exchange-alt"></i>
                    </button>
                </div>
                
                <!-- Right Code Input -->
                <div class="paste-area-wrapper right-area">
                    <label for="paste-right">
                        <i class="fas fa-file-code text-success"></i>
                        קוד חדש / משונה
                    </label>
                    <textarea 
                        id="paste-right" 
                        class="paste-textarea" 
                        placeholder="הדבק כאן את הקוד החדש...&#10;&#10;דוגמה:&#10;function hello(name) {&#10;    console.log('Hello ' + name);&#10;}"
                        spellcheck="false"
                        autocomplete="off"
                        autocorrect="off"
                        autocapitalize="off"
                    ></textarea>
                    <div class="paste-actions-row">
                        <span class="detected-language" id="lang-right">-</span>
                        <span class="char-count" id="count-right">0 תווים</span>
                        <button type="button" class="btn-clear-text" data-target="paste-right">
                            <i class="fas fa-eraser"></i> נקה
                        </button>
                    </div>
                </div>
            </div>
            
            <!-- Compare Action Bar -->
            <div class="paste-action-bar">
                <a href="{{ url_for('compare_files_page') }}" class="btn btn-secondary">
                    <i class="fas fa-folder-open"></i> השוואת קבצים שמורים
                </a>
                <button type="submit" id="btn-paste-compare" class="btn-compare">
                    <span class="spinner"></span>
                    <span class="btn-text">
                        <i class="fas fa-code-compare"></i>
                        השווה קוד
                    </span>
                </button>
                <button type="button" id="btn-clear-all" class="btn btn-outline-danger">
                    <i class="fas fa-trash-alt"></i> נקה הכל
                </button>
            </div>
        </form>
    </div>
    
    <!-- Stats Bar (hidden until comparison) -->
    <div id="stats-bar" class="stats-bar glass-card p-3 mb-4 d-none">
        <div class="row text-center">
            <div class="col">
                <span class="badge bg-success fs-6" id="stat-added">
                    <i class="fas fa-plus"></i> +<span>0</span>
                </span>
            </div>
            <div class="col">
                <span class="badge bg-danger fs-6" id="stat-removed">
                    <i class="fas fa-minus"></i> -<span>0</span>
                </span>
            </div>
            <div class="col">
                <span class="badge bg-warning fs-6" id="stat-modified">
                    <i class="fas fa-pen"></i> ~<span>0</span>
                </span>
            </div>
            <div class="col">
                <span class="badge bg-secondary fs-6" id="stat-unchanged">
                    <i class="fas fa-equals"></i> =<span>0</span>
                </span>
            </div>
        </div>
    </div>
    
    <!-- Diff Container (hidden until comparison) -->
    <div id="diff-container" class="diff-container glass-card d-none">
        <!-- Side by Side View -->
        <div id="side-by-side-view" class="diff-view active">
            <div class="diff-pane left-pane">
                <div class="pane-header">
                    <span class="file-label" id="left-file-label">קוד מקורי</span>
                </div>
                <div class="pane-content" id="left-content"></div>
            </div>
            <div class="diff-pane right-pane">
                <div class="pane-header">
                    <span class="file-label" id="right-file-label">קוד חדש</span>
                </div>
                <div class="pane-content" id="right-content"></div>
            </div>
        </div>
        
        <!-- Unified View -->
        <div id="unified-view" class="diff-view">
            <div class="unified-content" id="unified-content"></div>
        </div>
        
        <!-- Inline View -->
        <div id="inline-view" class="diff-view">
            <div class="inline-content" id="inline-content"></div>
        </div>
    </div>
    
    <!-- Action Bar (shown after comparison) -->
    <div id="result-actions" class="action-bar glass-card p-3 mt-4 d-none">
        <div class="d-flex justify-content-between align-items-center flex-wrap gap-2">
            <button type="button" id="btn-new-compare" class="btn btn-secondary">
                <i class="fas fa-redo"></i> השוואה חדשה
            </button>
            <div class="d-flex gap-2">
                <button id="btn-copy-diff" class="btn btn-outline-primary">
                    <i class="fas fa-copy"></i> העתק Diff
                </button>
                <button id="btn-download-diff" class="btn btn-outline-primary">
                    <i class="fas fa-download"></i> הורד Patch
                </button>
            </div>
        </div>
    </div>
</div>
{% endblock %}

{% block extra_js %}
<script src="{{ url_for('static', filename='js/compare.js') }}"></script>
<script>
(function() {
    'use strict';
    
    // =================================================================
    // Paste Compare Mode - Initialization
    // =================================================================
    
    // State
    const pasteState = {
        leftContent: '',
        rightContent: '',
        diffData: null,
        viewMode: 'side-by-side',
    };
    
    // Elements
    const els = {
        form: document.getElementById('paste-compare-form'),
        pasteLeft: document.getElementById('paste-left'),
        pasteRight: document.getElementById('paste-right'),
        swapBtn: document.getElementById('swap-paste'),
        compareBtn: document.getElementById('btn-paste-compare'),
        clearAllBtn: document.getElementById('btn-clear-all'),
        newCompareBtn: document.getElementById('btn-new-compare'),
        countLeft: document.getElementById('count-left'),
        countRight: document.getElementById('count-right'),
        langLeft: document.getElementById('lang-left'),
        langRight: document.getElementById('lang-right'),
        statsBar: document.getElementById('stats-bar'),
        diffContainer: document.getElementById('diff-container'),
        resultActions: document.getElementById('result-actions'),
        viewModeToggle: document.getElementById('view-mode-toggle'),
        modeButtons: document.querySelectorAll('[data-mode]'),
        copyDiffBtn: document.getElementById('btn-copy-diff'),
        downloadDiffBtn: document.getElementById('btn-download-diff'),
        clearTextBtns: document.querySelectorAll('.btn-clear-text'),
    };
    
    // =================================================================
    // Event Listeners
    // =================================================================
    
    // Text input changes
    els.pasteLeft.addEventListener('input', () => updateInputMeta('left'));
    els.pasteRight.addEventListener('input', () => updateInputMeta('right'));
    
    // Form submit
    els.form.addEventListener('submit', handleCompare);
    
    // Swap sides
    els.swapBtn.addEventListener('click', swapSides);
    
    // Clear all
    els.clearAllBtn.addEventListener('click', clearAll);
    
    // New comparison (scroll to top and focus)
    els.newCompareBtn?.addEventListener('click', () => {
        document.querySelector('.compare-header').scrollIntoView({ behavior: 'smooth' });
        setTimeout(() => els.pasteLeft.focus(), 300);
    });
    
    // Clear individual textarea
    els.clearTextBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.dataset.target;
            const textarea = document.getElementById(targetId);
            if (textarea) {
                textarea.value = '';
                textarea.focus();
                updateInputMeta(targetId === 'paste-left' ? 'left' : 'right');
            }
        });
    });
    
    // View mode buttons
    els.modeButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            const mode = btn.dataset.mode;
            setViewMode(mode);
        });
    });
    
    // Copy and download
    els.copyDiffBtn?.addEventListener('click', copyDiff);
    els.downloadDiffBtn?.addEventListener('click', downloadDiff);
    
    // Enable keyboard shortcuts
    document.addEventListener('keydown', (e) => {
        // Ctrl/Cmd + Enter to compare
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            handleCompare(e);
        }
    });
    
    // =================================================================
    // Functions
    // =================================================================
    
    function updateInputMeta(side) {
        const textarea = side === 'left' ? els.pasteLeft : els.pasteRight;
        const countEl = side === 'left' ? els.countLeft : els.countRight;
        const langEl = side === 'left' ? els.langLeft : els.langRight;
        
        const text = textarea.value;
        const charCount = text.length;
        const lineCount = text.split('\n').length;
        
        // Update character count
        countEl.textContent = `${charCount.toLocaleString('he-IL')} תווים, ${lineCount} שורות`;
        
        // Simple language detection
        const lang = detectLanguage(text);
        langEl.textContent = lang || '-';
    }
    
    function detectLanguage(code) {
        if (!code || code.trim().length < 10) return null;
        
        // Simple heuristics
        if (/^\s*(import|from)\s+[\w.]+/.test(code) || /def\s+\w+\s*\(/.test(code)) return 'Python';
        if (/^\s*(const|let|var|function|=>|async|await)/.test(code) || /console\.log/.test(code)) return 'JavaScript';
        if (/^\s*(public|private|class|interface|void)\s+/.test(code)) return 'Java/C#';
        if (/^\s*#include|int main\(/.test(code)) return 'C/C++';
        if (/^\s*<[a-zA-Z][\s\S]*>/.test(code)) return 'HTML/XML';
        if (/^\s*\{[\s\S]*"[\w]+"\s*:/.test(code)) return 'JSON';
        if (/^\s*[\w-]+\s*:\s*[^;]+;/.test(code)) return 'CSS';
        if (/^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER)/i.test(code)) return 'SQL';
        if (/^\s*#!/.test(code)) return 'Shell';
        
        return null;
    }
    
    function swapSides() {
        const leftVal = els.pasteLeft.value;
        els.pasteLeft.value = els.pasteRight.value;
        els.pasteRight.value = leftVal;
        
        updateInputMeta('left');
        updateInputMeta('right');
        
        // If already compared, re-run
        if (pasteState.diffData) {
            handleCompare(new Event('submit'));
        }
    }
    
    function clearAll() {
        els.pasteLeft.value = '';
        els.pasteRight.value = '';
        updateInputMeta('left');
        updateInputMeta('right');
        
        // Hide results
        els.statsBar.classList.add('d-none');
        els.diffContainer.classList.add('d-none');
        els.resultActions.classList.add('d-none');
        els.viewModeToggle.classList.add('d-none');
        
        pasteState.diffData = null;
        
        els.pasteLeft.focus();
    }
    
    async function handleCompare(e) {
        e.preventDefault();
        
        const leftContent = els.pasteLeft.value;
        const rightContent = els.pasteRight.value;
        
        if (!leftContent.trim() && !rightContent.trim()) {
            showToast('יש להדביק קוד בלפחות אחד מהשדות', 'warning');
            return;
        }
        
        setLoading(true);
        
        try {
            const response = await fetch('/api/compare/diff', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    left_content: leftContent,
                    right_content: rightContent,
                }),
            });
            
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            
            pasteState.diffData = await response.json();
            pasteState.leftContent = leftContent;
            pasteState.rightContent = rightContent;
            
            // Show results
            showResults();
            
        } catch (error) {
            console.error('Compare failed:', error);
            showToast('שגיאה בביצוע ההשוואה: ' + error.message, 'error');
        } finally {
            setLoading(false);
        }
    }
    
    function showResults() {
        // Use the existing CompareView module for rendering
        if (window.CompareView) {
            // Inject the diff data manually since we're in paste mode
            window.CompareView._pasteData = pasteState.diffData;
        }
        
        // Show UI elements
        els.statsBar.classList.remove('d-none');
        els.diffContainer.classList.remove('d-none');
        els.resultActions.classList.remove('d-none');
        els.viewModeToggle.classList.remove('d-none');
        
        // Update stats
        updateStats(pasteState.diffData.stats);
        
        // Render diff
        renderDiff();
        
        // Scroll to results
        els.statsBar.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    
    function updateStats(stats) {
        document.querySelector('#stat-added span').textContent = stats.added || 0;
        document.querySelector('#stat-removed span').textContent = stats.removed || 0;
        document.querySelector('#stat-modified span').textContent = stats.modified || 0;
        document.querySelector('#stat-unchanged span').textContent = stats.unchanged || 0;
    }
    
    function renderDiff() {
        const data = pasteState.diffData;
        if (!data) return;
        
        // Update view visibility
        document.getElementById('side-by-side-view').classList.toggle('active', pasteState.viewMode === 'side-by-side');
        document.getElementById('unified-view').classList.toggle('active', pasteState.viewMode === 'unified');
        document.getElementById('inline-view').classList.toggle('active', pasteState.viewMode === 'inline');
        
        switch (pasteState.viewMode) {
            case 'side-by-side':
                renderSideBySide(data);
                break;
            case 'unified':
                renderUnified(data);
                break;
            case 'inline':
                renderInline(data);
                break;
        }
    }
    
    function renderSideBySide(data) {
        const leftLines = [];
        const rightLines = [];
        
        data.lines.forEach((line, idx) => {
            leftLines.push(createDiffLine(
                line.line_num_left,
                line.content_left,
                getLeftClass(line.change_type),
                `row-${idx}`
            ));
            rightLines.push(createDiffLine(
                line.line_num_right,
                line.content_right,
                getRightClass(line.change_type),
                `row-${idx}`
            ));
        });
        
        document.getElementById('left-content').innerHTML = leftLines.join('');
        document.getElementById('right-content').innerHTML = rightLines.join('');
        
        // Sync scroll
        setupScrollSync();
    }
    
    function renderUnified(data) {
        const lines = data.lines.map(line => {
            const cssClass = line.change_type !== 'unchanged' ? line.change_type : '';
            const content = line.change_type === 'removed' ? line.content_left :
                           line.change_type === 'added' ? line.content_right :
                           line.content_left ?? line.content_right ?? '';
            
            return `
                <div class="unified-line ${cssClass}">
                    <div class="line-numbers">
                        <span>${line.line_num_left ?? ''}</span>
                        <span>${line.line_num_right ?? ''}</span>
                    </div>
                    <div class="line-content">${escapeHtml(content)}</div>
                </div>
            `;
        });
        
        document.getElementById('unified-content').innerHTML = lines.join('');
    }
    
    function renderInline(data) {
        const lines = data.lines.map(line => {
            return createDiffLine(
                line.line_num_left ?? line.line_num_right,
                line.content_left ?? line.content_right,
                line.change_type
            );
        });
        
        document.getElementById('inline-content').innerHTML = lines.join('');
    }
    
    function createDiffLine(lineNum, content, cssClass, rowId) {
        const escaped = escapeHtml(content ?? '') || '&nbsp;';
        const dataRow = rowId ? `data-row="${rowId}"` : '';
        
        return `
            <div class="diff-line ${cssClass || ''}" ${dataRow}>
                <div class="line-number">${lineNum ?? ''}</div>
                <div class="line-content"><pre>${escaped}</pre></div>
            </div>
        `;
    }
    
    function getLeftClass(changeType) {
        switch (changeType) {
            case 'removed': return 'removed';
            case 'modified': return 'modified';
            case 'added': return 'empty';
            default: return '';
        }
    }
    
    function getRightClass(changeType) {
        switch (changeType) {
            case 'added': return 'added';
            case 'modified': return 'modified';
            case 'removed': return 'empty';
            default: return '';
        }
    }
    
    function setupScrollSync() {
        const left = document.getElementById('left-content');
        const right = document.getElementById('right-content');
        
        if (!left || !right) return;
        
        let isScrolling = null;
        
        function sync(source, target) {
            if (isScrolling === target) return;
            isScrolling = source;
            
            const pct = source.scrollTop / (source.scrollHeight - source.clientHeight || 1);
            target.scrollTop = pct * (target.scrollHeight - target.clientHeight);
            
            clearTimeout(isScrolling._timeout);
            isScrolling._timeout = setTimeout(() => { isScrolling = null; }, 100);
        }
        
        left.addEventListener('scroll', () => sync(left, right), { passive: true });
        right.addEventListener('scroll', () => sync(right, left), { passive: true });
    }
    
    function setViewMode(mode) {
        pasteState.viewMode = mode;
        
        els.modeButtons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === mode);
        });
        
        renderDiff();
    }
    
    function setLoading(isLoading) {
        els.compareBtn.classList.toggle('loading', isLoading);
        els.compareBtn.disabled = isLoading;
    }
    
    function copyDiff() {
        const text = generateUnifiedText();
        navigator.clipboard.writeText(text).then(() => {
            showToast('ה-Diff הועתק ללוח!', 'success');
        }).catch(() => {
            showToast('שגיאה בהעתקה', 'error');
        });
    }
    
    function downloadDiff() {
        const text = generateUnifiedText();
        const blob = new Blob([text], { type: 'text/plain' });
        const url = URL.createObjectURL(blob);
        
        const a = document.createElement('a');
        a.href = url;
        a.download = `paste-compare-${Date.now()}.patch`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        
        showToast('הקובץ הורד', 'success');
    }
    
    function generateUnifiedText() {
        if (!pasteState.diffData) return '';
        
        const lines = ['--- original', '+++ modified'];
        
        pasteState.diffData.lines.forEach(line => {
            if (line.change_type === 'unchanged') {
                lines.push(` ${line.content_left || ''}`);
            } else if (line.change_type === 'removed') {
                lines.push(`-${line.content_left || ''}`);
            } else if (line.change_type === 'added') {
                lines.push(`+${line.content_right || ''}`);
            } else if (line.change_type === 'modified') {
                lines.push(`-${line.content_left || ''}`);
                lines.push(`+${line.content_right || ''}`);
            }
        });
        
        return lines.join('\n');
    }
    
    function escapeHtml(text) {
        if (text == null) return '';
        const div = document.createElement('div');
        div.textContent = String(text);
        return div.innerHTML;
    }
    
    function showToast(message, type = 'info') {
        // Use existing toast system if available
        if (window.Toast && typeof window.Toast.show === 'function') {
            window.Toast.show(message, type);
            return;
        }
        
        // Fallback
        const toast = document.createElement('div');
        toast.innerHTML = `
            <i class="fas fa-${type === 'success' ? 'check-circle' : type === 'error' ? 'exclamation-circle' : 'info-circle'}"></i>
            <span>${escapeHtml(message)}</span>
        `;
        toast.style.cssText = `
            position: fixed;
            bottom: 20px;
            left: 50%;
            transform: translateX(-50%);
            padding: 12px 24px;
            background: ${type === 'success' ? '#28a745' : type === 'error' ? '#dc3545' : '#6366f1'};
            color: white;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            z-index: 9999;
            display: flex;
            align-items: center;
            gap: 8px;
        `;
        
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }
    
    // Initial focus
    els.pasteLeft.focus();
    
})();
</script>
{% endblock %}
```

---

### 3. הרחבת JavaScript

ה-JavaScript הנדרש כבר כלול ב-template למעלה (inline script). אם תרצו להפריד לקובץ נפרד:

**קובץ (אופציונלי):** `webapp/static/js/compare-paste.js`

> **המלצה:** להשאיר את הקוד inline ב-template כי:
> 1. הקוד ספציפי לדף זה בלבד
> 2. פחות requests לשרת
> 3. קל יותר לתחזוקה

---

### 4. CSS נוסף (אופציונלי)

הסגנונות כבר כלולים ב-template. אם תרצו להפריד:

**קובץ:** `webapp/static/css/compare-paste.css`

או להוסיף ל-`compare.css` הקיים את הסגנונות מתוך ה-template.

---

## ניווט ואינטגרציה

### הוספת לינק בתפריט/navbar

**מיקום מוצע:** `webapp/templates/base.html` - בתפריט הכלים

```html
<!-- בתוך dropdown של כלים -->
<a class="dropdown-item" href="{{ url_for('compare_paste_page') }}">
    <i class="fas fa-paste"></i> השוואה בהדבקה
</a>
```

### הוספת לינק בדף השוואת קבצים

**קובץ:** `webapp/templates/compare_files.html`

הוסף כפתור ליד "חזור לקבצים":

```html
<a href="{{ url_for('compare_paste_page') }}" class="btn btn-outline-primary">
    <i class="fas fa-paste"></i> השוואה בהדבקה
</a>
```

### הוספת לדף הבית/Dashboard

**קובץ:** `webapp/templates/dashboard.html` (אם קיים)

הוסף כרטיס פעולה מהירה:

```html
<div class="quick-action-card">
    <a href="{{ url_for('compare_paste_page') }}">
        <i class="fas fa-paste"></i>
        <span>השוואת קוד בהדבקה</span>
    </a>
</div>
```

---

## צ'קליסט מימוש

### Backend
- [ ] הוספת route `compare_paste_page` ב-`webapp/app.py`
- [ ] וידוא ש-`login_required` מוגדר (או הסרה אם רוצים גישה ללא התחברות)

### Frontend
- [ ] יצירת `webapp/templates/compare_paste.html`
- [ ] בדיקה שה-CSS של `compare.css` נטען
- [ ] בדיקת תאימות ל-`compare.js` הקיים

### ניווט
- [ ] הוספת לינק ל-navbar/תפריט
- [ ] הוספת לינק מדף `compare_files.html`
- [ ] (אופציונלי) הוספת לינק ב-dashboard

### בדיקות
- [ ] בדיקה ידנית: הדבקת קוד משני מקורות
- [ ] בדיקה: החלפת צדדים
- [ ] בדיקה: כל 3 מצבי התצוגה
- [ ] בדיקה: העתקה והורדה
- [ ] בדיקה: responsive (מובייל/טאבלט)
- [ ] (אופציונלי) הוספת unit tests

---

## שיקולי UX

### למה פיצ'ר זה שימושי?

1. **השוואה מהירה** - לא צריך לשמור קבצים קודם
2. **קוד חיצוני** - השוואת קוד מ-Stack Overflow, GitHub, email
3. **Code Review** - להדביק גרסאות שונות לבדיקה
4. **Debug** - השוואת output מריצות שונות
5. **שיתוף** - קל להדביק ולראות הבדלים

### טיפים לשיפור UX

1. **זיהוי שפה אוטומטי** - מוצג כ-badge (כבר ממומש)
2. **Syntax Highlighting** - אפשר להוסיף עם Prism.js/Highlight.js
3. **שמירה זמנית** - localStorage לשמירת הקלט בין רענונים
4. **גרור ושחרר** - תמיכה ב-drag & drop של קבצים
5. **קיצורי מקלדת** - Ctrl+Enter להשוואה (כבר ממומש)

### תמיכה ב-Drag & Drop (הרחבה עתידית)

```javascript
// הוספה אפשרית לטעינת קבצים
textarea.addEventListener('dragover', (e) => {
    e.preventDefault();
    textarea.classList.add('drag-over');
});

textarea.addEventListener('drop', async (e) => {
    e.preventDefault();
    textarea.classList.remove('drag-over');
    
    const file = e.dataTransfer.files[0];
    if (file) {
        const text = await file.text();
        textarea.value = text;
        updateInputMeta(side);
    }
});
```

---

## בדיקות

### בדיקת API (ידנית)

```bash
# בדיקה בסיסית
curl -X POST http://localhost:5000/api/compare/diff \
  -H "Content-Type: application/json" \
  -d '{"left_content": "hello\nworld", "right_content": "hello\nuniverse"}'

# צפוי:
# {
#   "lines": [...],
#   "stats": {"added": 0, "removed": 0, "modified": 1, "unchanged": 1},
#   ...
# }
```

### בדיקת Unit (pytest)

**קובץ:** `tests/test_compare_paste.py`

```python
import importlib
import os

def _import_app():
    os.environ.setdefault("COMMUNITY_LIBRARY_ENABLED", "1")
    os.environ.setdefault("CHATOPS_ALLOW_ALL_IF_NO_ADMINS", "1")
    app_mod = importlib.import_module('webapp.app')
    app = app_mod.app
    app.testing = True
    return app


def test_compare_paste_page_requires_login():
    """דף ההדבקה דורש התחברות."""
    app = _import_app()
    with app.test_client() as c:
        r = c.get('/compare/paste')
        # אם יש login_required, צפוי redirect
        assert r.status_code in (302, 401)


def test_compare_paste_page_authenticated():
    """דף ההדבקה נטען למשתמש מחובר."""
    app = _import_app()
    with app.test_client() as c:
        with c.session_transaction() as sess:
            sess['user_id'] = 123
        r = c.get('/compare/paste')
        assert r.status_code == 200
        assert 'השוואת קוד בהדבקה' in r.data.decode('utf-8')


def test_compare_diff_api_empty_content():
    """API מחזיר תוצאה גם לתוכן ריק."""
    app = _import_app()
    with app.test_client() as c:
        r = c.post('/api/compare/diff', 
                   json={"left_content": "", "right_content": ""})
        assert r.status_code == 200
        data = r.get_json()
        assert data['stats']['unchanged'] == 0


def test_compare_diff_api_identical():
    """API מזהה קבצים זהים."""
    app = _import_app()
    with app.test_client() as c:
        content = "line1\nline2\nline3"
        r = c.post('/api/compare/diff',
                   json={"left_content": content, "right_content": content})
        assert r.status_code == 200
        data = r.get_json()
        assert data['stats']['added'] == 0
        assert data['stats']['removed'] == 0
        assert data['stats']['modified'] == 0
        assert data['stats']['unchanged'] == 3


def test_compare_diff_api_differences():
    """API מזהה הבדלים."""
    app = _import_app()
    with app.test_client() as c:
        r = c.post('/api/compare/diff',
                   json={
                       "left_content": "a\nb\nc",
                       "right_content": "a\nx\nc\nd"
                   })
        assert r.status_code == 200
        data = r.get_json()
        assert data['stats']['modified'] == 1  # b -> x
        assert data['stats']['added'] == 1     # d
        assert data['stats']['unchanged'] == 2  # a, c
```

---

## קבצים רלוונטיים (סיכום)

| קובץ | סטטוס | תיאור |
|------|-------|-------|
| `services/diff_service.py` | ✅ קיים | לוגיקת ההשוואה |
| `webapp/app.py` | 📝 לעדכן | הוספת route אחד |
| `webapp/templates/compare_paste.html` | 🆕 ליצור | Template חדש |
| `webapp/static/js/compare.js` | ✅ קיים | ניתן לשימוש חוזר |
| `webapp/static/css/compare.css` | ✅ קיים | ניתן לשימוש חוזר |
| `tests/test_compare_paste.py` | 🆕 ליצור (אופציונלי) | בדיקות |

---

## סיכום

הרחבת פיצ'ר השוואת הקבצים לתמיכה בהדבקה היא **משימה קלה יחסית** כי:

1. ✅ **ה-API כבר קיים** (`POST /api/compare/diff`)
2. ✅ **ה-DiffService כבר ממומש** ועובד
3. ✅ **ה-CSS והעיצוב כבר מוכנים**
4. ✅ **מבנה ה-JS ניתן לשימוש חוזר**

**כל מה שנדרש:**
1. Route פשוט אחד (3 שורות)
2. Template חדש (מבוסס על `compare_files.html`)
3. לינקים בניווט

**זמן הערכה למימוש:** 1-2 שעות

---

## קישורים שימושיים

- [difflib Documentation](https://docs.python.org/3/library/difflib.html)
- [Monaco Diff Editor](https://microsoft.github.io/monaco-editor/playground.html#creating-the-diffeditor-hello-diff-world) - אלטרנטיבה עתידית
- [Unified Diff Format](https://en.wikipedia.org/wiki/Diff#Unified_format)
