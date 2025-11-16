# מדריך מימוש מצב חשוך מלא ומותאם לעיניים

**תאריך**: ינואר 2025  
**גרסה**: 1.0  
**סטטוס**: מדריך מימוש

---

## 📋 תוכן עניינים

1. [סקירה כללית](#סקירה-כללית)
2. [דרישות מקדימות](#דרישות-מקדימות)
3. [שלב 1: הוספת CSS Variables למצב חשוך](#שלב-1-הוספת-css-variables-למצב-חשוך)
4. [שלב 2: יצירת קובץ CSS למצב חשוך](#שלב-2-יצירת-קובץ-css-למצב-חשוך)
5. [שלב 3: עדכון Backend](#שלב-3-עדכון-backend)
6. [שלב 4: עדכון UI - הוספת טוגל](#שלב-4-עדכון-ui---הוספת-טוגל)
7. [שלב 5: התאמת CodeMirror](#שלב-5-התאמת-codemirror)
8. [שלב 6: התאמת Pygments](#שלב-6-התאמת-pygments)
9. [שלב 7: JavaScript לניהול מצב](#שלב-7-javascript-לניהול-מצב)
10. [שלב 8: התאמת קומפוננטים נוספים](#שלב-8-התאמת-קומפוננטים-נוספים)
11. [בדיקות ואימות](#בדיקות-ואימות)
12. [טיפים ופתרון בעיות](#טיפים-ופתרון-בעיות)

---

## סקירה כללית

מדריך זה מתאר כיצד לממש מצב חשוך מלא ומותאם לעיניים ב-WebApp, תוך שימוש במערכת ה-theme הקיימת. המצב החשוך יכלול:

- ✅ פלטת צבעים מאוזנת (low blue light)
- ✅ ניגודיות מותאמת לקריאה ארוכה
- ✅ syntax highlighting מותאם למצב חשוך
- ✅ מעבר חלק בין מצבים (fade transition)
- ✅ התאמה אוטומטית למערכת (prefers-color-scheme)
- ✅ 3 רמות: Light / Dim / Dark
- ✅ שמירת העדפה ב-localStorage ו-DB

---

## דרישות מקדימות

- הבנה בסיסית ב-CSS, JavaScript ו-Flask
- גישה לקוד הקיים של WebApp
- ידע במערכת ה-theme הקיימת (`data-theme` attribute)

---

## שלב 1: הוספת CSS Variables למצב חשוך

### 1.1 עדכון `base.html`

נוסיף CSS variables למצב חשוך ב-`webapp/templates/base.html`:

```css
/* Theme palettes - הוספה אחרי השורות הקיימות */
:root[data-theme="dark"] {
    /* צבעי רקע - כהה ונוח לעיניים */
    --bg-primary: #1a1a1a;
    --bg-secondary: #252525;
    --bg-tertiary: #2d2d2d;
    
    /* צבעי טקסט - ניגודיות מאוזנת */
    --text-primary: #e0e0e0;
    --text-secondary: #b0b0b0;
    --text-muted: #808080;
    
    /* צבעי אקסנט - מותאמים למצב חשוך */
    --primary: #7c8aff;
    --primary-dark: #6b7aff;
    --secondary: #9d7aff;
    
    /* צבעי מערכת */
    --success: #4ade80;
    --danger: #f87171;
    --warning: #fbbf24;
    --info: #60a5fa;
    
    /* Glass morphism - מותאם למצב חשוך */
    --glass: rgba(255, 255, 255, 0.05);
    --glass-border: rgba(255, 255, 255, 0.1);
    --glass-hover: rgba(255, 255, 255, 0.08);
    
    /* צבעי רקע לכרטיסים */
    --card-bg: rgba(30, 30, 30, 0.8);
    --card-border: rgba(255, 255, 255, 0.1);
    
    /* צבעי קוד */
    --code-bg: #1e1e1e;
    --code-text: #d4d4d4;
    --code-border: rgba(255, 255, 255, 0.1);
}

/* מצב Dim - ביניים */
:root[data-theme="dim"] {
    --bg-primary: #2a2a2a;
    --bg-secondary: #333333;
    --bg-tertiary: #3a3a3a;
    --text-primary: #d0d0d0;
    --text-secondary: #a0a0a0;
    --text-muted: #707070;
    --primary: #7c8aff;
    --secondary: #9d7aff;
    --glass: rgba(255, 255, 255, 0.08);
    --glass-border: rgba(255, 255, 255, 0.15);
    --card-bg: rgba(40, 40, 40, 0.8);
    --code-bg: #2a2a2a;
}

/* עדכון body למצב חשוך */
:root[data-theme="dark"] body,
:root[data-theme="dim"] body {
    background: linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-secondary) 100%);
    color: var(--text-primary);
}

/* עדכון רקע הגל למצב חשוך */
:root[data-theme="dark"] body::before,
:root[data-theme="dim"] body::before {
    background: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1440 320"><path fill="%23000000" fill-opacity="0.1" d="M0,96L48,112C96,128,192,160,288,160C384,160,480,128,576,122.7C672,117,768,139,864,138.7C960,139,1056,117,1152,101.3C1248,85,1344,75,1392,69.3L1440,64L1440,320L1392,320C1344,320,1248,320,1152,320C1056,320,960,320,864,320C768,320,672,320,576,320C480,320,384,320,288,320C192,320,96,320,48,320L0,320Z"/></svg>') no-repeat bottom center;
}
```

**מיקום**: הוסף אחרי שורה 57 ב-`base.html` (אחרי `:root[data-theme="forest"]`)

---

## שלב 2: יצירת קובץ CSS למצב חשוך

### 2.1 יצירת `dark-mode.css`

צור קובץ חדש: `webapp/static/css/dark-mode.css`

```css
/* Dark Mode Styles - Comprehensive Theme Support */

/* ============================================
   Base Elements
   ============================================ */

[data-theme="dark"] .navbar,
[data-theme="dim"] .navbar {
    background: var(--glass);
    backdrop-filter: blur(20px);
    border-bottom: 1px solid var(--glass-border);
}

[data-theme="dark"] .glass-card,
[data-theme="dim"] .glass-card {
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    color: var(--text-primary);
}

[data-theme="dark"] .glass-card:hover,
[data-theme="dim"] .glass-card:hover {
    background: var(--glass-hover);
}

/* ============================================
   Typography
   ============================================ */

[data-theme="dark"] h1,
[data-theme="dark"] h2,
[data-theme="dark"] h3,
[data-theme="dark"] h4,
[data-theme="dark"] h5,
[data-theme="dark"] h6,
[data-theme="dim"] h1,
[data-theme="dim"] h2,
[data-theme="dim"] h3,
[data-theme="dim"] h4,
[data-theme="dim"] h5,
[data-theme="dim"] h6 {
    color: var(--text-primary);
}

[data-theme="dark"] p,
[data-theme="dim"] p {
    color: var(--text-secondary);
}

/* ============================================
   Buttons
   ============================================ */

[data-theme="dark"] .btn-primary,
[data-theme="dim"] .btn-primary {
    background: var(--primary);
    color: white;
    border: 1px solid var(--primary-dark);
}

[data-theme="dark"] .btn-primary:hover,
[data-theme="dim"] .btn-primary:hover {
    background: var(--primary-dark);
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(124, 138, 255, 0.4);
}

[data-theme="dark"] .btn-secondary,
[data-theme="dim"] .btn-secondary {
    background: var(--glass);
    color: var(--text-primary);
    border: 1px solid var(--glass-border);
}

[data-theme="dark"] .btn-secondary:hover,
[data-theme="dim"] .btn-secondary:hover {
    background: var(--glass-hover);
    border-color: var(--primary);
}

/* ============================================
   Inputs & Forms
   ============================================ */

[data-theme="dark"] input,
[data-theme="dark"] textarea,
[data-theme="dark"] select,
[data-theme="dim"] input,
[data-theme="dim"] textarea,
[data-theme="dim"] select {
    background: var(--bg-tertiary);
    color: var(--text-primary);
    border: 1px solid var(--glass-border);
}

[data-theme="dark"] input:focus,
[data-theme="dark"] textarea:focus,
[data-theme="dark"] select:focus,
[data-theme="dim"] input:focus,
[data-theme="dim"] textarea:focus,
[data-theme="dim"] select:focus {
    outline: 2px solid var(--primary);
    border-color: var(--primary);
}

[data-theme="dark"] input::placeholder,
[data-theme="dark"] textarea::placeholder,
[data-theme="dim"] input::placeholder,
[data-theme="dim"] textarea::placeholder {
    color: var(--text-muted);
}

/* ============================================
   Code Blocks
   ============================================ */

[data-theme="dark"] .source,
[data-theme="dim"] .source {
    background: var(--code-bg) !important;
    color: var(--code-text) !important;
    border: 1px solid var(--code-border);
}

[data-theme="dark"] .highlighttable td.linenos,
[data-theme="dim"] .highlighttable td.linenos {
    background: var(--bg-tertiary);
    color: var(--text-muted);
    border-right: 1px solid var(--code-border);
}

/* ============================================
   Alerts
   ============================================ */

[data-theme="dark"] .alert-success,
[data-theme="dim"] .alert-success {
    background: rgba(74, 222, 128, 0.15);
    border: 1px solid rgba(74, 222, 128, 0.3);
    color: var(--success);
}

[data-theme="dark"] .alert-error,
[data-theme="dim"] .alert-error {
    background: rgba(248, 113, 113, 0.15);
    border: 1px solid rgba(248, 113, 113, 0.3);
    color: var(--danger);
}

[data-theme="dark"] .alert-info,
[data-theme="dim"] .alert-info {
    background: rgba(96, 165, 250, 0.15);
    border: 1px solid rgba(96, 165, 250, 0.3);
    color: var(--info);
}

/* ============================================
   Badges
   ============================================ */

[data-theme="dark"] .badge,
[data-theme="dim"] .badge {
    background: var(--glass);
    border: 1px solid var(--glass-border);
    color: var(--text-primary);
}

/* ============================================
   Links
   ============================================ */

[data-theme="dark"] a,
[data-theme="dim"] a {
    color: var(--primary);
}

[data-theme="dark"] a:hover,
[data-theme="dim"] a:hover {
    color: var(--primary-dark);
    opacity: 0.9;
}

/* ============================================
   Quick Access Menu
   ============================================ */

[data-theme="dark"] .quick-access-dropdown,
[data-theme="dim"] .quick-access-dropdown {
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.5);
}

[data-theme="dark"] .quick-access-item,
[data-theme="dim"] .quick-access-item {
    color: var(--text-primary);
    border-color: var(--glass-border);
}

[data-theme="dark"] .quick-access-item:hover,
[data-theme="dim"] .quick-access-item:hover {
    background: var(--glass-hover);
    color: var(--primary);
}

/* ============================================
   Modals
   ============================================ */

[data-theme="dark"] .recent-files-modal .modal-content,
[data-theme="dark"] .community-modal .modal-content,
[data-theme="dim"] .recent-files-modal .modal-content,
[data-theme="dim"] .community-modal .modal-content {
    background: var(--card-bg);
    color: var(--text-primary);
    border: 1px solid var(--card-border);
}

[data-theme="dark"] .recent-files-modal .modal-header,
[data-theme="dark"] .community-modal .modal-header,
[data-theme="dim"] .recent-files-modal .modal-header,
[data-theme="dim"] .community-modal .modal-header {
    border-bottom-color: var(--glass-border);
}

/* ============================================
   File Cards
   ============================================ */

[data-theme="dark"] .file-card,
[data-theme="dim"] .file-card {
    background: var(--card-bg);
    border: 1px solid var(--card-border);
}

[data-theme="dark"] .file-card:hover,
[data-theme="dim"] .file-card:hover {
    background: var(--glass-hover);
    transform: translateY(-2px);
}

/* ============================================
   Search & Filters
   ============================================ */

[data-theme="dark"] .search-input,
[data-theme="dark"] .filter-select,
[data-theme="dim"] .search-input,
[data-theme="dim"] .filter-select {
    background: var(--bg-tertiary);
    color: var(--text-primary);
    border-color: var(--glass-border);
}

/* ============================================
   Transitions - מעבר חלק
   ============================================ */

[data-theme="dark"] *,
[data-theme="dim"] *,
[data-theme="dark"] *::before,
[data-theme="dim"] *::before,
[data-theme="dark"] *::after,
[data-theme="dim"] *::after {
    transition: background-color 0.3s ease,
                color 0.3s ease,
                border-color 0.3s ease,
                box-shadow 0.3s ease;
}

/* ============================================
   Scrollbar
   ============================================ */

[data-theme="dark"] ::-webkit-scrollbar-track,
[data-theme="dim"] ::-webkit-scrollbar-track {
    background: var(--bg-primary);
}

[data-theme="dark"] ::-webkit-scrollbar-thumb,
[data-theme="dim"] ::-webkit-scrollbar-thumb {
    background: var(--glass-border);
    border-radius: 5px;
}

[data-theme="dark"] ::-webkit-scrollbar-thumb:hover,
[data-theme="dim"] ::-webkit-scrollbar-thumb:hover {
    background: var(--text-muted);
}

/* ============================================
   Selection
   ============================================ */

[data-theme="dark"] ::selection,
[data-theme="dim"] ::selection {
    background: rgba(124, 138, 255, 0.3);
    color: var(--text-primary);
}

/* ============================================
   Mobile Adjustments
   ============================================ */

@media (max-width: 768px) {
    [data-theme="dark"] .glass-card,
    [data-theme="dim"] .glass-card {
        padding: 1rem;
    }
}
```

### 2.2 הוספת הקובץ ל-`base.html`

הוסף את הקובץ אחרי שורות ה-CSS הקיימות:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='css/dark-mode.css') }}?v={{ static_version }}">
```

**מיקום**: אחרי שורה 874 ב-`base.html` (אחרי `high-contrast.css`)

---

## שלב 3: עדכון Backend

### 3.1 עדכון `app.py`

עדכן את רשימת ה-themes ב-`webapp/app.py`:

```python
# מצא את השורה (בערך 819):
if theme not in {'classic','ocean','forest','high-contrast'}:
    theme = 'classic'

# שנה ל:
if theme not in {'classic','ocean','forest','high-contrast','dark','dim'}:
    theme = 'classic'
```

עדכן גם את ה-API endpoint:

```python
# מצא את השורה (בערך 6608):
if theme in {'classic', 'ocean', 'forest', 'high-contrast'}:

# שנה ל:
if theme in {'classic', 'ocean', 'forest', 'high-contrast', 'dark', 'dim'}:
```

---

## שלב 4: עדכון UI - הוספת טוגל

### 4.1 עדכון `settings.html`

הוסף אופציות למצב חשוך ב-`webapp/templates/settings.html`:

```html
<select id="themeSelect" class="filter-select" aria-label="בחר ערכת נושא" style="padding: 0.5rem 0.75rem; border-radius: 10px; border: 1px solid rgba(255,255,255,0.2); background: rgba(255,255,255,0.1); color: white;">
    <option value="classic" {% if ui_theme == 'classic' %}selected{% endif %}>קלאסי{% if ui_theme == 'classic' %} (נוכחית){% endif %}</option>
    <option value="ocean" {% if ui_theme == 'ocean' %}selected{% endif %}>אוקיינוס{% if ui_theme == 'ocean' %} (נוכחית){% endif %}</option>
    <option value="forest" {% if ui_theme == 'forest' %}selected{% endif %}>יער{% if ui_theme == 'forest' %} (נוכחית){% endif %}</option>
    <option value="dark" {% if ui_theme == 'dark' %}selected{% endif %}>🌙 חשוך{% if ui_theme == 'dark' %} (נוכחית){% endif %}</option>
    <option value="dim" {% if ui_theme == 'dim' %}selected{% endif %}>🌆 מעומעם{% if ui_theme == 'dim' %} (נוכחית){% endif %}</option>
    <option value="high-contrast" {% if ui_theme == 'high-contrast' %}selected{% endif %}>ניגודיות גבוהה{% if ui_theme == 'high-contrast' %} (נוכחית){% endif %}</option>
</select>
```

### 4.2 הוספת טוגל מהיר ב-Navbar (אופציונלי)

ניתן להוסיף כפתור טוגל מהיר ב-`base.html`:

```html
<!-- הוסף ב-navbar, אחרי הלוגו -->
{% if session.user_id %}
<button id="darkModeToggle" class="btn btn-secondary btn-icon" title="החלף מצב חשוך/בהיר" aria-label="החלף מצב חשוך">
    <i class="fas fa-moon" id="darkModeIcon"></i>
    <span class="btn-text">חשוך</span>
</button>
{% endif %}
```

---

## שלב 5: התאמת CodeMirror

### 5.1 עדכון `codemirror.bundle.entry.mjs`

עדכן את הפונקציה `getTheme`:

```javascript
function getTheme(name) {
    const themeName = String(name || '').toLowerCase();
    // תמיכה במצב חשוך
    if (themeName === 'dark' || themeName === 'dim') {
        return oneDark || [];
    }
    // אם ה-HTML element במצב חשוך, השתמש ב-oneDark
    if (typeof document !== 'undefined') {
        const htmlTheme = document.documentElement.getAttribute('data-theme');
        if (htmlTheme === 'dark' || htmlTheme === 'dim') {
            return oneDark || [];
        }
    }
    return [];
}
```

### 5.2 עדכון `editor-manager.js`

עדכן את `initCodeMirror` כדי לזהות את ה-theme הנוכחי:

```javascript
async initCodeMirror(container, { language, value, theme }) {
    // ... קוד קיים ...
    
    // זיהוי theme אוטומטי מה-HTML
    const htmlTheme = document.documentElement.getAttribute('data-theme');
    const effectiveTheme = (htmlTheme === 'dark' || htmlTheme === 'dim') ? 'dark' : theme;
    
    // ... המשך הקוד עם effectiveTheme ...
}
```

### 5.3 עדכון `codemirror-custom.css`

הוסף styles למצב חשוך:

```css
/* Dark Mode CodeMirror */
[data-theme="dark"] .codemirror-container,
[data-theme="dim"] .codemirror-container {
    background: var(--code-bg);
    border-color: var(--code-border);
}

[data-theme="dark"] .cm-editor,
[data-theme="dim"] .cm-editor {
    background: var(--code-bg);
    color: var(--code-text);
}

[data-theme="dark"] .cm-gutters,
[data-theme="dim"] .cm-gutters {
    background: var(--bg-tertiary);
    border-right-color: var(--code-border);
    color: var(--text-muted);
}

[data-theme="dark"] .cm-activeLineGutter,
[data-theme="dim"] .cm-activeLineGutter {
    background: var(--glass-hover);
}

[data-theme="dark"] .cm-activeLine,
[data-theme="dim"] .cm-activeLine {
    background: var(--glass);
}

[data-theme="dark"] .cm-selectionBackground,
[data-theme="dim"] .cm-selectionBackground {
    background-color: rgba(124, 138, 255, 0.3) !important;
}
```

---

## שלב 6: התאמת Pygments

### 6.1 עדכון `app.py`

עדכן את ה-Pygments style בהתאם ל-theme:

```python
# מצא את השורות שמשתמשות ב-Pygments (בערך 4700, 4811, 6932):

# במקום:
style='github-dark'

# שנה ל:
def get_pygments_style(theme):
    """החזר Pygments style בהתאם ל-theme"""
    if theme in ('dark', 'dim'):
        return 'github-dark'
    elif theme == 'high-contrast':
        return 'monokai'  # או style אחר עם ניגודיות גבוהה
    else:
        return 'github'  # light theme

# ואז השתמש:
style = get_pygments_style(theme)
```

דוגמה מלאה:

```python
# בפונקציה שמציגה קוד (view_file route):
def get_pygments_style(theme):
    """החזר Pygments style בהתאם ל-theme"""
    theme_map = {
        'dark': 'github-dark',
        'dim': 'github-dark',
        'high-contrast': 'monokai',
        'classic': 'github',
        'ocean': 'github',
        'forest': 'github'
    }
    return theme_map.get(theme, 'github')

# בשימוש:
formatter = HtmlFormatter(
    style=get_pygments_style(theme),
    linenos=True,
    cssclass='source',
    lineanchors='line',
    anchorlinenos=True
)
highlighted_code = highlight(code, lexer, formatter)
```

---

## שלב 7: JavaScript לניהול מצב

### 7.1 יצירת `dark-mode.js`

צור קובץ חדש: `webapp/static/js/dark-mode.js`

```javascript
/**
 * Dark Mode Manager
 * ניהול מצב חשוך/בהיר עם תמיכה ב-Auto mode
 */

(function() {
    'use strict';

    const DARK_MODE_KEY = 'dark_mode_preference';
    const THEME_ATTRIBUTE = 'data-theme';

    /**
     * זיהוי העדפת מערכת
     */
    function getSystemPreference() {
        if (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            return 'dark';
        }
        return 'light';
    }

    /**
     * טעינת העדפה מ-localStorage
     */
    function loadPreference() {
        try {
            const saved = localStorage.getItem(DARK_MODE_KEY);
            if (saved === 'dark' || saved === 'dim' || saved === 'light' || saved === 'auto') {
                return saved;
            }
        } catch (e) {
            console.warn('Failed to load dark mode preference:', e);
        }
        return 'auto'; // ברירת מחדל
    }

    /**
     * שמירת העדפה
     */
    function savePreference(mode) {
        try {
            localStorage.setItem(DARK_MODE_KEY, mode);
        } catch (e) {
            console.warn('Failed to save dark mode preference:', e);
        }
    }

    /**
     * החלת theme על ה-HTML element
     */
    function applyTheme(theme) {
        const html = document.documentElement;
        if (theme && theme !== 'auto') {
            html.setAttribute(THEME_ATTRIBUTE, theme);
        } else {
            // Auto mode - השתמש בהעדפת המערכת
            const systemPref = getSystemPreference();
            html.setAttribute(THEME_ATTRIBUTE, systemPref === 'dark' ? 'dark' : 'classic');
        }
    }

    /**
     * עדכון theme בהתאם להעדפה
     */
    function updateTheme() {
        const preference = loadPreference();
        if (preference === 'auto') {
            applyTheme('auto');
            // האזנה לשינויים בהעדפת המערכת
            if (window.matchMedia) {
                const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
                mediaQuery.addEventListener('change', () => {
                    applyTheme('auto');
                });
            }
        } else {
            applyTheme(preference);
        }
    }

    /**
     * החלפת מצב (toggle)
     */
    function toggleDarkMode() {
        const current = loadPreference();
        let next;
        
        // מחזור: auto -> dark -> dim -> light -> auto
        switch (current) {
            case 'auto':
                next = 'dark';
                break;
            case 'dark':
                next = 'dim';
                break;
            case 'dim':
                next = 'light';
                break;
            case 'light':
            default:
                next = 'auto';
                break;
        }
        
        savePreference(next);
        updateTheme();
        updateToggleButton(next);
        
        // עדכון לשרת (אופציונלי)
        syncToServer(next);
    }

    /**
     * עדכון כפתור הטוגל
     */
    function updateToggleButton(mode) {
        const toggleBtn = document.getElementById('darkModeToggle');
        const icon = document.getElementById('darkModeIcon');
        const text = toggleBtn?.querySelector('.btn-text');
        
        if (!toggleBtn || !icon) return;
        
        const icons = {
            'auto': 'fa-adjust',
            'dark': 'fa-moon',
            'dim': 'fa-cloud-moon',
            'light': 'fa-sun'
        };
        
        const labels = {
            'auto': 'אוטומטי',
            'dark': 'חשוך',
            'dim': 'מעומעם',
            'light': 'בהיר'
        };
        
        // הסרת כל האייקונים הקודמים
        icon.className = 'fas ' + (icons[mode] || icons.auto);
        if (text) text.textContent = labels[mode] || labels.auto;
        
        toggleBtn.setAttribute('title', `מצב: ${labels[mode] || labels.auto}`);
    }

    /**
     * סנכרון עם השרת
     */
    async function syncToServer(theme) {
        try {
            // המרת mode ל-theme name
            let themeName = theme;
            if (theme === 'auto') {
                themeName = getSystemPreference() === 'dark' ? 'dark' : 'classic';
            } else if (theme === 'light') {
                themeName = 'classic';
            }
            
            await fetch('/api/ui_prefs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ theme: themeName })
            });
        } catch (e) {
            console.warn('Failed to sync theme to server:', e);
        }
    }

    /**
     * אתחול
     */
    function init() {
        // עדכון theme בהתחלה
        updateTheme();
        
        // חיבור לכפתור הטוגל (אם קיים)
        const toggleBtn = document.getElementById('darkModeToggle');
        if (toggleBtn) {
            toggleBtn.addEventListener('click', toggleDarkMode);
            const current = loadPreference();
            updateToggleButton(current);
        }
        
        // עדכון theme selector ב-settings
        const themeSelect = document.getElementById('themeSelect');
        if (themeSelect) {
            // אם יש העדפה ב-localStorage, עדכן את ה-select
            const preference = loadPreference();
            if (preference !== 'auto' && preference !== 'light') {
                // המרה: dark -> dark, dim -> dim, light -> classic
                const themeValue = preference === 'light' ? 'classic' : preference;
                if (themeSelect.querySelector(`option[value="${themeValue}"]`)) {
                    themeSelect.value = themeValue;
                }
            }
        }
    }

    // הפעלה בעת טעינת הדף
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // חשיפת API גלובלי (אופציונלי)
    window.DarkMode = {
        toggle: toggleDarkMode,
        set: function(mode) {
            savePreference(mode);
            updateTheme();
            updateToggleButton(mode);
            syncToServer(mode);
        },
        get: loadPreference
    };
})();
```

### 7.2 הוספת הקובץ ל-`base.html`

```html
<script src="{{ url_for('static', filename='js/dark-mode.js') }}?v={{ static_version }}" defer></script>
```

**מיקום**: אחרי שורה 1522 ב-`base.html` (אחרי `global_search.js`)

---

## שלב 8: התאמת קומפוננטים נוספים

### 8.1 Markdown Preview

עדכן את `md_preview.html` כדי לתמוך במצב חשוך:

```css
/* הוסף ל-md_preview.html */
[data-theme="dark"] #md-content,
[data-theme="dim"] #md-content {
    background: var(--bg-primary);
    color: var(--text-primary);
}

[data-theme="dark"] #md-content code:not(pre code),
[data-theme="dim"] #md-content code:not(pre code) {
    background: var(--bg-tertiary);
    color: var(--code-text);
    border: 1px solid var(--code-border);
}

[data-theme="dark"] #md-content pre,
[data-theme="dim"] #md-content pre {
    background: var(--code-bg);
    border: 1px solid var(--code-border);
}
```

### 8.2 Collections & Bookmarks

ודא שכל הקומפוננטים משתמשים ב-CSS variables:

```css
/* ב-collections.css, bookmarks.css וכו' */
[data-theme="dark"] .collection-card,
[data-theme="dim"] .collection-card {
    background: var(--card-bg);
    border-color: var(--card-border);
    color: var(--text-primary);
}
```

---

## בדיקות ואימות

### 9.1 רשימת בדיקות

- [ ] מעבר בין מצבים (Light/Dark/Dim/Auto) עובד חלק
- [ ] כל הקומפוננטים נראים נכון במצב חשוך
- [ ] CodeMirror מציג syntax highlighting נכון
- [ ] Pygments מציג קוד נכון
- [ ] כל הכפתורים והקישורים נראים ופועלים
- [ ] Forms ו-inputs נראים נכון
- [ ] Modals ו-dropdowns נראים נכון
- [ ] התאמה אוטומטית ל-`prefers-color-scheme` עובדת
- [ ] העדפה נשמרת ב-localStorage ו-DB
- [ ] מעבר חלק ללא flickering

### 9.2 בדיקות ידניות

1. **בדיקת טוגל**:
   - לחץ על כפתור הטוגל
   - ודא שהמצב משתנה חלק
   - ודא שהעדפה נשמרת

2. **בדיקת Auto Mode**:
   - הגדר ל-Auto
   - שנה את העדפת המערכת (Windows/Mac)
   - ודא שה-WebApp מתעדכן אוטומטית

3. **בדיקת כל הדפים**:
   - עבור על כל הדפים במצב חשוך
   - ודא שאין אלמנטים שקופים או לא קריאים

---

## טיפים ופתרון בעיות

### 10.1 בעיות נפוצות

**בעיה**: אלמנטים לא משתנים למצב חשוך
- **פתרון**: ודא שה-CSS selector כולל `[data-theme="dark"]` או `[data-theme="dim"]`
- **פתרון**: ודא שה-CSS variables מוגדרים ב-`:root[data-theme="dark"]`

**בעיה**: Flickering בעת טעינת הדף
- **פתרון**: הוסף script ב-`<head>` שמגדיר את ה-theme לפני טעינת ה-CSS:
```html
<script>
    (function() {
        const saved = localStorage.getItem('dark_mode_preference');
        const html = document.documentElement;
        if (saved === 'dark' || saved === 'dim') {
            html.setAttribute('data-theme', saved);
        } else if (saved === 'auto' && window.matchMedia('(prefers-color-scheme: dark)').matches) {
            html.setAttribute('data-theme', 'dark');
        }
    })();
</script>
```

**בעיה**: CodeMirror לא משתנה למצב חשוך
- **פתרון**: ודא ש-`getTheme` ב-`codemirror.bundle.entry.mjs` בודק את `data-theme`
- **פתרון**: ודא ש-`editor-manager.js` מעביר את ה-theme הנכון

**בעיה**: Pygments לא משתנה
- **פתרון**: ודא ש-`get_pygments_style` ב-`app.py` מקבל את ה-theme הנכון
- **פתרון**: ודא שה-style מועבר ל-`HtmlFormatter`

### 10.2 אופטימיזציות

1. **Lazy Loading**: טען את `dark-mode.css` רק כשצריך
2. **CSS Variables**: השתמש ב-CSS variables ככל האפשר
3. **Transitions**: הוסף transitions חלקים (כבר כלול)
4. **Caching**: ודא שהעדפה נשמרת ב-localStorage ו-DB

### 10.3 נגישות

- ודא ניגודיות מספקת (WCAG AA minimum)
- ודא שכל האלמנטים אינטראקטיביים נראים במצב חשוך
- הוסף `aria-label` לכפתור הטוגל

---

## סיכום

מדריך זה מתאר מימוש מלא של מצב חשוך ב-WebApp. לאחר ביצוע כל השלבים, המשתמשים יוכלו:

- ✅ לבחור בין Light / Dim / Dark / Auto
- ✅ ליהנות ממעבר חלק בין מצבים
- ✅ לקבל התאמה אוטומטית להעדפת המערכת
- ✅ לראות קוד עם syntax highlighting מותאם
- ✅ לשמור את ההעדפה שלהם

**זמן משוער ליישום**: 3-5 ימים

**קובצים שצריך לערוך**:
1. `webapp/templates/base.html` - CSS variables ו-JS
2. `webapp/static/css/dark-mode.css` - קובץ חדש
3. `webapp/app.py` - עדכון themes ו-Pygments
4. `webapp/templates/settings.html` - הוספת אופציות
5. `webapp/static/js/dark-mode.js` - קובץ חדש
6. `webapp/static_build/codemirror.bundle.entry.mjs` - עדכון theme
7. `webapp/static/css/codemirror-custom.css` - styles למצב חשוך

---

**נוצר על ידי**: Background Agent  
**תאריך**: ינואר 2025  
**גרסה**: 1.0
