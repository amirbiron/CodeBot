# מדריך מימוש Theme Builder – Issue #2097

> **מטרה:** ממשק בונה ערכת נושא עם Live Preview מבודד, שמירה ב-MongoDB ושימוש בטוקנים העדכניים.

---

## תוכן עניינים

1. [סקירת מצב קיים](#סקירת-מצב-קיים)
2. [ארכיטקטורה מוצעת](#ארכיטקטורה-מוצעת)
3. [שלב 1: Backend & API](#שלב-1-backend--api)
4. [שלב 2: תבנית HTML](#שלב-2-תבנית-html)
5. [שלב 3: JavaScript ו-Live Preview](#שלב-3-javascript-ו-live-preview)
6. [שלב 4: הזרקה ב-base.html](#שלב-4-הזרקה-ב-basehtml)
7. [שלב 5: Reset ומחיקה](#שלב-5-reset-ומחיקה)
8. [שלב 6: נגישות ו-UX](#שלב-6-נגישות-ו-ux)
9. [בדיקות](#בדיקות)
10. [צ'קליסט למימוש](#צקליסט-למימוש)

---

## סקירת מצב קיים

### מבנה הפרויקט הרלוונטי

```
webapp/
├── app.py                      # Flask application (~10,000+ שורות)
├── templates/
│   ├── base.html               # תבנית בסיס – CSS variables + theme injection
│   ├── settings.html           # דף הגדרות קיים (theme selector)
│   └── theme_preview.html      # Preview themes (hardcoded)
└── static/css/
    ├── dark-mode.css           # Theme-specific styles
    └── high-contrast.css       # נגישות
```

### מיקום טוקנים קיימים

כל ה-CSS variables מוגדרים **inline** ב-`base.html` בתוך `<style>` בתחילת ה-`<head>`:

```html
<!-- webapp/templates/base.html שורות 44-317 -->
<style>
    :root {
        --primary: #667eea;
        --glass: rgba(255, 255, 255, 0.1);
        --md-surface: #1b1e24;
        /* ... */
    }
    
    :root[data-theme="classic"] { /* ... */ }
    :root[data-theme="ocean"] { /* ... */ }
    :root[data-theme="dark"] { /* ... */ }
    /* וכו' */
</style>
```

### API קיים להעדפות

```python
# webapp/app.py שורות 9113-9225
@app.route('/api/ui_prefs', methods=['POST'])
@login_required
def update_ui_prefs():
    data = request.get_json() or {}
    # font_scale, theme, smooth_scroll_config
    # מעדכן: db.users.update_one(..., {"$set": {"ui_prefs": {...}}})
```

### מבנה users collection (MongoDB)

```python
# שדות קיימים במשתמש:
{
    "_id": user_id,
    "ui_prefs": {
        "font_scale": 1.0,
        "theme": "classic",
        "smooth_scroll": {...}
    },
    # ← כאן יתווסף:
    "custom_theme": {
        "name": "My Theme",
        "is_active": true,
        "updated_at": datetime,
        "variables": {
            "--bg-primary": "#...",
            "--primary": "#...",
            # ...
        }
    }
}
```

---

## ארכיטקטורה מוצעת

### תרשים זרימה

```
┌──────────────────────────────────────────────────────────────────┐
│                      /settings/theme-builder                      │
├────────────────────────────┬─────────────────────────────────────┤
│    CONTROL PANEL (50%)     │       LIVE PREVIEW (50%)            │
│ ┌────────────────────────┐ │  ┌──────────────────────────────┐   │
│ │  Color Picker Group    │ │  │  Navbar Preview              │   │
│ │  ├─ bg-primary         │ │  │  ├─ Logo                     │   │
│ │  ├─ bg-secondary       │ │  │  └─ Nav Links                │   │
│ │  ├─ card-bg            │ │  ├──────────────────────────────┤   │
│ │  ├─ primary (accent)   │ │  │  Card Preview                │   │
│ │  ├─ secondary (accent) │ │  │  ├─ File Card                │   │
│ │  └─ text-primary       │ │  │  └─ Code Block               │   │
│ ├────────────────────────┤ │  ├──────────────────────────────┤   │
│ │  Glass Controls        │ │  │  Button Preview              │   │
│ │  ├─ Opacity slider     │ │  │  ├─ Primary                  │   │
│ │  └─ Blur slider        │ │  │  └─ Secondary                │   │
│ ├────────────────────────┤ │  └──────────────────────────────┘   │
│ │  Theme Name Input      │ │                                      │
│ │  [Save] [Reset]        │ │  <div id="theme-preview-container"> │
│ └────────────────────────┘ │  <!-- CSS vars applied HERE only --> │
└────────────────────────────┴─────────────────────────────────────┘
```

### עקרון Live Preview מבודד

```javascript
// רק על הקונטיינר של ה-Preview – לא משפיע על שאר הדף
function updatePreview(varName, value) {
    const preview = document.getElementById('theme-preview-container');
    preview.style.setProperty(varName, value);
}
```

---

## שלב 1: Backend & API

### 1.1 הוספת Route לדף

הוסף ב-`webapp/app.py` ליד `/settings` (בערך שורה 8886):

```python
@app.route('/settings/theme-builder')
@login_required
def theme_builder():
    """דף בונה ערכת נושא מותאמת אישית."""
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))
    
    # טען theme מותאם אם קיים
    saved_theme = None
    try:
        user_doc = db.users.find_one({"_id": user_id}, {"custom_theme": 1})
        if user_doc:
            saved_theme = user_doc.get("custom_theme")
    except Exception as e:
        app.logger.warning(f"theme_builder: failed to load custom_theme: {e}")
    
    return render_template(
        'settings/theme_builder.html',
        saved_theme=saved_theme,
        user=get_current_user(),
        is_admin=is_admin_user(user_id),
        is_premium=is_premium_user(user_id),
        ui_font_scale=get_font_scale(user_id),
        ui_theme=get_ui_theme(user_id),
    )
```

### 1.2 API לשמירת Theme

הוסף ב-`webapp/app.py`:

```python
import re
from datetime import datetime, timezone

# קבועים לולידציה
# Regex for safe color validation - prevents CSS injection
# Note: color-mix uses [^)]+ to prevent escaping the parentheses
VALID_COLOR_REGEX = re.compile(
    r'^('
    r'#[0-9a-fA-F]{6}'                           # Hex: #rrggbb
    r'|#[0-9a-fA-F]{8}'                          # Hex with alpha: #rrggbbaa
    r'|rgba?\(\s*\d{1,3}\s*,\s*\d{1,3}\s*,\s*\d{1,3}\s*(,\s*[\d.]+\s*)?\)'  # rgb/rgba
    r'|var\(--[a-zA-Z0-9_-]+\)'                  # CSS var reference
    r'|color-mix\(in\s+srgb\s*,\s*[^)]+\)'      # color-mix (restricted)
    r')$'
)
MAX_THEME_NAME_LENGTH = 50
ALLOWED_VARIABLES = {
    '--bg-primary', '--bg-secondary', '--card-bg',
    '--primary', '--secondary',
    '--text-primary', '--text-secondary',
    '--glass', '--glass-border', '--glass-hover', '--glass-blur',
    '--md-surface', '--md-text',
    '--btn-primary-bg', '--btn-primary-color',
}


def _validate_color(value: str) -> bool:
    """בדיקה שהערך הוא צבע תקין או blur value."""
    if not value or not isinstance(value, str):
        return False
    value = value.strip()
    # blur יכול להיות ערך px
    if value.endswith('px'):
        try:
            float(value[:-2])
            return True
        except ValueError:
            return False
    return bool(VALID_COLOR_REGEX.match(value))


@app.route('/api/themes/save', methods=['POST'])
@login_required
def save_custom_theme():
    """שמירת ערכת נושא מותאמת אישית."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    data = request.get_json() or {}
    
    # ולידציית שם
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "missing_name"}), 400
    if len(name) > MAX_THEME_NAME_LENGTH:
        return jsonify({"ok": False, "error": "name_too_long"}), 400
    
    # ולידציית variables
    variables = data.get("variables") or {}
    if not isinstance(variables, dict):
        return jsonify({"ok": False, "error": "invalid_variables"}), 400
    
    validated_vars = {}
    for var_name, var_value in variables.items():
        if var_name not in ALLOWED_VARIABLES:
            continue  # התעלם ממשתנים לא מוכרים
        if not _validate_color(var_value):
            return jsonify({
                "ok": False, 
                "error": "invalid_color",
                "field": var_name
            }), 400
        validated_vars[var_name] = var_value
    
    # בניית אובייקט ה-theme
    theme_doc = {
        "name": name,
        "description": (data.get("description") or "").strip()[:200],
        "is_active": bool(data.get("set_as_default", True)),
        "updated_at": datetime.now(timezone.utc),
        "variables": validated_vars,
    }
    
    try:
        db.users.update_one(
            {"_id": user_id},
            {"$set": {"custom_theme": theme_doc}}
        )
        
        # אם set_as_default, עדכן גם את ui_prefs.theme ל-"custom"
        if theme_doc["is_active"]:
            db.users.update_one(
                {"_id": user_id},
                {"$set": {"ui_prefs.theme": "custom"}}
            )
        
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.error(f"save_custom_theme failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500


@app.route('/api/themes/custom', methods=['DELETE'])
@login_required
def delete_custom_theme():
    """מחיקת ערכת נושא מותאמת אישית (איפוס)."""
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    
    try:
        # הסר את ה-custom_theme ואפס ל-classic
        db.users.update_one(
            {"_id": user_id},
            {
                "$unset": {"custom_theme": ""},
                "$set": {"ui_prefs.theme": "classic"}
            }
        )
        return jsonify({"ok": True, "reset_to": "classic"})
    except Exception as e:
        app.logger.error(f"delete_custom_theme failed: {e}")
        return jsonify({"ok": False, "error": "database_error"}), 500
```

### 1.3 בדיקת ניגודיות (אופציונלי)

```python
def _check_contrast_ratio(fg_hex: str, bg_hex: str) -> float:
    """חישוב יחס ניגודיות WCAG 2.1."""
    def hex_to_luminance(hex_color):
        hex_color = hex_color.lstrip('#')
        r, g, b = (int(hex_color[i:i+2], 16) / 255 for i in (0, 2, 4))
        
        def adjust(c):
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        
        return 0.2126 * adjust(r) + 0.7152 * adjust(g) + 0.0722 * adjust(b)
    
    l1 = hex_to_luminance(fg_hex)
    l2 = hex_to_luminance(bg_hex)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)
```

---

## שלב 2: תבנית HTML

צור קובץ חדש `webapp/templates/settings/theme_builder.html`:

```html
{% extends "base.html" %}

{% block title %}בונה ערכת נושא - Code Keeper Bot{% endblock %}

{% block content %}
<h1 class="page-title">
    <i class="fas fa-palette"></i>
    בונה ערכת נושא
</h1>

<div class="theme-builder-layout">
    <!-- Control Panel -->
    <div class="theme-builder-controls glass-card">
        <form id="themeBuilderForm" autocomplete="off">
            <!-- Theme Name -->
            <div class="control-group">
                <label for="themeName">
                    <i class="fas fa-tag"></i>
                    שם הערכה
                </label>
                <input 
                    type="text" 
                    id="themeName" 
                    name="name"
                    maxlength="50"
                    placeholder="הערכה שלי"
                    value="{{ saved_theme.name if saved_theme else '' }}"
                    aria-describedby="themeNameHelp"
                    required
                />
                <small id="themeNameHelp">עד 50 תווים</small>
            </div>

            <!-- Background Colors -->
            <fieldset class="control-section">
                <legend><i class="fas fa-fill-drip"></i> רקעים</legend>
                
                <div class="color-row">
                    <label for="bgPrimary">רקע ראשי</label>
                    <div class="color-input-wrapper">
                        <input type="text" id="bgPrimaryText" data-var="--bg-primary" class="color-text" />
                        <div id="bgPrimary" class="color-picker" data-var="--bg-primary"></div>
                    </div>
                </div>
                
                <div class="color-row">
                    <label for="bgSecondary">רקע משני</label>
                    <div class="color-input-wrapper">
                        <input type="text" id="bgSecondaryText" data-var="--bg-secondary" class="color-text" />
                        <div id="bgSecondary" class="color-picker" data-var="--bg-secondary"></div>
                    </div>
                </div>
                
                <div class="color-row">
                    <label for="cardBg">רקע כרטיסים</label>
                    <div class="color-input-wrapper">
                        <input type="text" id="cardBgText" data-var="--card-bg" class="color-text" />
                        <div id="cardBg" class="color-picker" data-var="--card-bg"></div>
                    </div>
                </div>
            </fieldset>

            <!-- Accent Colors -->
            <fieldset class="control-section">
                <legend><i class="fas fa-star"></i> צבעי אקסנט</legend>
                
                <div class="color-row">
                    <label for="primary">ראשי (Primary)</label>
                    <div class="color-input-wrapper">
                        <input type="text" id="primaryText" data-var="--primary" class="color-text" />
                        <div id="primary" class="color-picker" data-var="--primary"></div>
                    </div>
                </div>
                
                <div class="color-row">
                    <label for="secondary">משני (Secondary)</label>
                    <div class="color-input-wrapper">
                        <input type="text" id="secondaryText" data-var="--secondary" class="color-text" />
                        <div id="secondary" class="color-picker" data-var="--secondary"></div>
                    </div>
                </div>
            </fieldset>

            <!-- Text Colors -->
            <fieldset class="control-section">
                <legend><i class="fas fa-font"></i> טקסט</legend>
                
                <div class="color-row">
                    <label for="textPrimary">טקסט ראשי</label>
                    <div class="color-input-wrapper">
                        <input type="text" id="textPrimaryText" data-var="--text-primary" class="color-text" />
                        <div id="textPrimary" class="color-picker" data-var="--text-primary"></div>
                    </div>
                </div>
            </fieldset>

            <!-- Glass Controls -->
            <fieldset class="control-section">
                <legend><i class="fas fa-window-maximize"></i> Glass Effect</legend>
                
                <div class="slider-row">
                    <label for="glassOpacity">שקיפות</label>
                    <input 
                        type="range" 
                        id="glassOpacity" 
                        min="0" max="100" 
                        value="10"
                        aria-describedby="glassOpacityValue"
                    />
                    <span id="glassOpacityValue">10%</span>
                </div>
                
                <div class="slider-row">
                    <label for="glassBlur">טשטוש (Blur)</label>
                    <input 
                        type="range" 
                        id="glassBlur" 
                        min="0" max="40" 
                        value="20"
                        aria-describedby="glassBlurValue"
                    />
                    <span id="glassBlurValue">20px</span>
                </div>
            </fieldset>

            <!-- Markdown (stays dark) -->
            <fieldset class="control-section">
                <legend><i class="fas fa-code"></i> Markdown / קוד</legend>
                
                <div class="color-row">
                    <label for="mdSurface">רקע קוד</label>
                    <div class="color-input-wrapper">
                        <input type="text" id="mdSurfaceText" data-var="--md-surface" class="color-text" />
                        <div id="mdSurface" class="color-picker" data-var="--md-surface"></div>
                    </div>
                </div>
                
                <div class="color-row">
                    <label for="mdText">טקסט קוד</label>
                    <div class="color-input-wrapper">
                        <input type="text" id="mdTextText" data-var="--md-text" class="color-text" />
                        <div id="mdText" class="color-picker" data-var="--md-text"></div>
                    </div>
                </div>
            </fieldset>

            <!-- Actions -->
            <div class="form-actions">
                <button type="submit" class="btn btn-primary" id="saveThemeBtn">
                    <i class="fas fa-save"></i>
                    שמור ערכה
                </button>
                <button type="button" class="btn btn-secondary" id="resetThemeBtn">
                    <i class="fas fa-undo"></i>
                    איפוס לברירת מחדל
                </button>
            </div>
        </form>
    </div>

    <!-- Live Preview -->
    <div class="theme-builder-preview glass-card">
        <h3>
            <i class="fas fa-eye"></i>
            תצוגה מקדימה
        </h3>
        
        <div id="theme-preview-container" class="preview-sandbox">
            <!-- Navbar Preview -->
            <nav class="preview-navbar">
                <span class="preview-logo">
                    <i class="fas fa-code"></i>
                    CodeBot
                </span>
                <div class="preview-nav-links">
                    <a href="#">קבצים</a>
                    <a href="#">אוספים</a>
                    <a href="#">הגדרות</a>
                </div>
            </nav>

            <!-- Card Preview -->
            <div class="preview-card">
                <div class="preview-card-header">
                    <i class="fas fa-file-code"></i>
                    <span>example.py</span>
                </div>
                <pre class="preview-code-block"><code>def hello():
    print("Hello, Theme!")
    return True</code></pre>
            </div>

            <!-- Buttons Preview -->
            <div class="preview-buttons">
                <button class="preview-btn-primary">כפתור ראשי</button>
                <button class="preview-btn-secondary">כפתור משני</button>
            </div>

            <!-- Glass Card Preview -->
            <div class="preview-glass-card">
                <p>כרטיס Glass עם טשטוש רקע</p>
            </div>
        </div>
    </div>
</div>

<!-- Toast notifications -->
<div id="theme-toast" class="theme-toast" role="alert" aria-live="polite"></div>

<style>
.theme-builder-layout {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 2rem;
    align-items: start;
}

@media (max-width: 900px) {
    .theme-builder-layout {
        grid-template-columns: 1fr;
    }
}

.theme-builder-controls {
    position: sticky;
    top: 2rem;
}

.control-group {
    margin-bottom: 1.5rem;
}

.control-group label {
    display: block;
    margin-bottom: 0.5rem;
    font-weight: 600;
}

.control-group input[type="text"] {
    width: 100%;
    padding: 0.75rem;
    border-radius: 10px;
    border: 1px solid var(--glass-border);
    background: var(--glass);
    color: var(--text-primary);
}

.control-section {
    border: 1px solid var(--glass-border);
    border-radius: 12px;
    padding: 1rem;
    margin-bottom: 1.5rem;
}

.control-section legend {
    padding: 0 0.5rem;
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.color-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1rem;
}

.color-row label {
    flex: 1;
}

.color-input-wrapper {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.color-text {
    width: 100px;
    padding: 0.4rem;
    border-radius: 6px;
    border: 1px solid var(--glass-border);
    background: var(--glass);
    color: var(--text-primary);
    font-family: monospace;
    font-size: 0.85rem;
}

.color-picker {
    width: 40px;
    height: 40px;
    border-radius: 8px;
    cursor: pointer;
    border: 2px solid var(--glass-border);
}

.slider-row {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-bottom: 1rem;
}

.slider-row label {
    flex: 1;
}

.slider-row input[type="range"] {
    flex: 2;
}

.slider-row span {
    min-width: 50px;
    text-align: left;
    font-family: monospace;
}

.form-actions {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
    margin-top: 2rem;
}

/* Preview Sandbox - isolated styles */
.preview-sandbox {
    background: linear-gradient(135deg, var(--bg-primary) 0%, var(--bg-secondary) 100%);
    border-radius: 12px;
    padding: 1rem;
    min-height: 400px;
}

.preview-navbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.75rem 1rem;
    background: var(--glass);
    backdrop-filter: blur(var(--glass-blur, 20px));
    border-radius: 10px;
    margin-bottom: 1rem;
}

.preview-logo {
    font-weight: 700;
    color: var(--text-primary);
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.preview-nav-links {
    display: flex;
    gap: 1rem;
}

.preview-nav-links a {
    color: var(--text-primary);
    text-decoration: none;
    opacity: 0.85;
}

.preview-card {
    background: var(--card-bg);
    border: 1px solid var(--glass-border);
    border-radius: 12px;
    padding: 1rem;
    margin-bottom: 1rem;
}

.preview-card-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.75rem;
    color: var(--text-primary);
    font-weight: 600;
}

.preview-code-block {
    background: var(--md-surface);
    color: var(--md-text);
    padding: 1rem;
    border-radius: 8px;
    font-family: 'Fira Code', monospace;
    font-size: 0.85rem;
    overflow-x: auto;
}

.preview-buttons {
    display: flex;
    gap: 1rem;
    margin-bottom: 1rem;
}

.preview-btn-primary {
    background: var(--btn-primary-bg, var(--primary));
    color: var(--btn-primary-color, white);
    border: none;
    padding: 0.75rem 1.5rem;
    border-radius: 10px;
    cursor: pointer;
    font-weight: 600;
}

.preview-btn-secondary {
    background: var(--glass);
    color: var(--text-primary);
    border: 1px solid var(--glass-border);
    padding: 0.75rem 1.5rem;
    border-radius: 10px;
    cursor: pointer;
}

.preview-glass-card {
    background: var(--glass);
    backdrop-filter: blur(var(--glass-blur, 20px));
    border: 1px solid var(--glass-border);
    border-radius: 12px;
    padding: 1rem;
    color: var(--text-primary);
}

/* Toast */
.theme-toast {
    position: fixed;
    bottom: 2rem;
    left: 50%;
    transform: translateX(-50%) translateY(100px);
    background: var(--card-bg);
    color: var(--text-primary);
    padding: 1rem 2rem;
    border-radius: 10px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.3);
    opacity: 0;
    transition: transform 0.3s ease, opacity 0.3s ease;
    z-index: 9999;
}

.theme-toast.visible {
    transform: translateX(-50%) translateY(0);
    opacity: 1;
}

.theme-toast.error {
    background: var(--danger);
    color: white;
}

.theme-toast.success {
    background: var(--success);
    color: white;
}
</style>

<script src="https://cdn.jsdelivr.net/npm/@simonwep/pickr@1.8.2/dist/pickr.min.js"></script>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@simonwep/pickr@1.8.2/dist/themes/nano.min.css"/>

<script>
(function() {
    'use strict';
    
    // ========== Configuration ==========
    const DEFAULT_VALUES = {
        '--bg-primary': '#6b63ff',
        '--bg-secondary': '#8e63ff',
        '--card-bg': 'rgba(255, 255, 255, 0.12)',
        '--primary': '#667eea',
        '--secondary': '#764ba2',
        '--text-primary': '#ffffff',
        '--glass': 'rgba(255, 255, 255, 0.1)',
        '--glass-border': 'rgba(255, 255, 255, 0.2)',
        '--glass-hover': 'rgba(255, 255, 255, 0.15)',
        '--glass-blur': '20px',
        '--md-surface': '#1b1e24',
        '--md-text': '#f0f0f0',
    };
    
    // Saved theme from server (if exists)
    const SAVED_THEME = {{ saved_theme | tojson | safe if saved_theme else 'null' }};
    
    const previewContainer = document.getElementById('theme-preview-container');
    const pickrInstances = {};
    
    // ========== Toast ==========
    function showToast(message, type = 'info') {
        const toast = document.getElementById('theme-toast');
        toast.textContent = message;
        toast.className = 'theme-toast visible ' + type;
        setTimeout(() => {
            toast.classList.remove('visible');
        }, 3000);
    }
    
    // ========== Preview Update ==========
    function updatePreview(varName, value) {
        if (!previewContainer) return;
        previewContainer.style.setProperty(varName, value);
    }
    
    // ========== Pickr Initialization ==========
    function initColorPicker(elementId, varName) {
        const el = document.getElementById(elementId);
        if (!el) return null;
        
        const textInput = document.getElementById(elementId + 'Text');
        const initialColor = SAVED_THEME?.variables?.[varName] || DEFAULT_VALUES[varName] || '#ffffff';
        
        const pickr = Pickr.create({
            el: el,
            theme: 'nano',
            default: initialColor,
            components: {
                preview: true,
                opacity: true,
                hue: true,
                interaction: {
                    hex: true,
                    rgba: true,
                    input: true,
                    save: true,
                }
            }
        });
        
        pickr.on('change', (color) => {
            const rgba = color.toRGBA();
            const value = rgba[3] < 1 
                ? `rgba(${Math.round(rgba[0])}, ${Math.round(rgba[1])}, ${Math.round(rgba[2])}, ${rgba[3].toFixed(2)})`
                : color.toHEXA().toString();
            
            if (textInput) textInput.value = value;
            updatePreview(varName, value);
        });
        
        pickr.on('save', () => pickr.hide());
        
        // Sync text input
        if (textInput) {
            textInput.value = initialColor;
            textInput.addEventListener('change', () => {
                const val = textInput.value.trim();
                if (val) {
                    try {
                        pickr.setColor(val);
                        updatePreview(varName, val);
                    } catch (e) {
                        // ignore invalid color
                    }
                }
            });
        }
        
        // Initial preview
        updatePreview(varName, initialColor);
        
        return pickr;
    }
    
    // ========== Initialize All Pickers ==========
    function initAllPickers() {
        pickrInstances['bgPrimary'] = initColorPicker('bgPrimary', '--bg-primary');
        pickrInstances['bgSecondary'] = initColorPicker('bgSecondary', '--bg-secondary');
        pickrInstances['cardBg'] = initColorPicker('cardBg', '--card-bg');
        pickrInstances['primary'] = initColorPicker('primary', '--primary');
        pickrInstances['secondary'] = initColorPicker('secondary', '--secondary');
        pickrInstances['textPrimary'] = initColorPicker('textPrimary', '--text-primary');
        pickrInstances['mdSurface'] = initColorPicker('mdSurface', '--md-surface');
        pickrInstances['mdText'] = initColorPicker('mdText', '--md-text');
    }
    
    // ========== Glass Sliders ==========
    function initGlassSliders() {
        const opacitySlider = document.getElementById('glassOpacity');
        const opacityValue = document.getElementById('glassOpacityValue');
        const blurSlider = document.getElementById('glassBlur');
        const blurValue = document.getElementById('glassBlurValue');
        
        // Initialize from saved
        if (SAVED_THEME?.variables?.['--glass']) {
            const match = SAVED_THEME.variables['--glass'].match(/[\d.]+(?=\))/);
            if (match) {
                opacitySlider.value = Math.round(parseFloat(match[0]) * 100);
            }
        }
        if (SAVED_THEME?.variables?.['--glass-blur']) {
            blurSlider.value = parseInt(SAVED_THEME.variables['--glass-blur']);
        }
        
        opacitySlider.addEventListener('input', () => {
            const val = opacitySlider.value;
            opacityValue.textContent = val + '%';
            const rgba = `rgba(255, 255, 255, ${(val / 100).toFixed(2)})`;
            updatePreview('--glass', rgba);
        });
        
        blurSlider.addEventListener('input', () => {
            const val = blurSlider.value;
            blurValue.textContent = val + 'px';
            updatePreview('--glass-blur', val + 'px');
        });
        
        // Initial update
        opacityValue.textContent = opacitySlider.value + '%';
        blurValue.textContent = blurSlider.value + 'px';
        updatePreview('--glass', `rgba(255, 255, 255, ${(opacitySlider.value / 100).toFixed(2)})`);
        updatePreview('--glass-blur', blurSlider.value + 'px');
    }
    
    // ========== Collect Values ==========
    function collectThemeValues() {
        const variables = {};
        
        // Colors from pickr
        const varMap = {
            'bgPrimary': '--bg-primary',
            'bgSecondary': '--bg-secondary',
            'cardBg': '--card-bg',
            'primary': '--primary',
            'secondary': '--secondary',
            'textPrimary': '--text-primary',
            'mdSurface': '--md-surface',
            'mdText': '--md-text',
        };
        
        for (const [pickrId, varName] of Object.entries(varMap)) {
            const textInput = document.getElementById(pickrId + 'Text');
            if (textInput && textInput.value) {
                variables[varName] = textInput.value.trim();
            }
        }
        
        // Glass
        const opacitySlider = document.getElementById('glassOpacity');
        const blurSlider = document.getElementById('glassBlur');
        const opacityVal = parseInt(opacitySlider.value, 10);
        // Clamp alpha values to valid 0-1 range
        const glassAlpha = (opacityVal / 100).toFixed(2);
        const borderAlpha = Math.min(1, (opacityVal + 10) / 100).toFixed(2);
        const hoverAlpha = Math.min(1, (opacityVal + 5) / 100).toFixed(2);
        variables['--glass'] = `rgba(255, 255, 255, ${glassAlpha})`;
        variables['--glass-border'] = `rgba(255, 255, 255, ${borderAlpha})`;
        variables['--glass-hover'] = `rgba(255, 255, 255, ${hoverAlpha})`;
        variables['--glass-blur'] = blurSlider.value + 'px';
        
        return variables;
    }
    
    // ========== Save Theme ==========
    async function saveTheme(e) {
        e.preventDefault();
        
        const nameInput = document.getElementById('themeName');
        const name = nameInput.value.trim();
        
        if (!name) {
            showToast('נא להזין שם לערכה', 'error');
            nameInput.focus();
            return;
        }
        
        const variables = collectThemeValues();
        
        try {
            const res = await fetch('/api/themes/save', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: name,
                    set_as_default: true,
                    variables: variables,
                })
            });
            
            const data = await res.json();
            
            if (!res.ok || !data.ok) {
                throw new Error(data.error || 'save_failed');
            }
            
            showToast('הערכה נשמרה בהצלחה! מרענן...', 'success');
            
            // רענן כדי להחיל
            setTimeout(() => location.reload(), 1500);
            
        } catch (err) {
            console.error('Save theme error:', err);
            let msg = 'שגיאה בשמירת הערכה';
            if (err.message === 'invalid_color') msg = 'אחד הצבעים אינו תקין';
            if (err.message === 'name_too_long') msg = 'השם ארוך מדי (עד 50 תווים)';
            showToast(msg, 'error');
        }
    }
    
    // ========== Reset Theme ==========
    async function resetTheme() {
        if (!confirm('האם לאפס את הערכה המותאמת ולחזור לברירת המחדל?')) {
            return;
        }
        
        try {
            const res = await fetch('/api/themes/custom', { method: 'DELETE' });
            const data = await res.json();
            
            if (!res.ok || !data.ok) {
                throw new Error(data.error || 'reset_failed');
            }
            
            showToast('הערכה אופסה. מרענן...', 'success');
            setTimeout(() => location.reload(), 1500);
            
        } catch (err) {
            console.error('Reset theme error:', err);
            showToast('שגיאה באיפוס הערכה', 'error');
        }
    }
    
    // ========== Init ==========
    function init() {
        initAllPickers();
        initGlassSliders();
        
        document.getElementById('themeBuilderForm').addEventListener('submit', saveTheme);
        document.getElementById('resetThemeBtn').addEventListener('click', resetTheme);
    }
    
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
</script>
{% endblock %}
```

---

## שלב 3: JavaScript ו-Live Preview

### עקרונות מפתח

1. **בידוד Preview** – כל `updatePreview()` מעדכן רק את `#theme-preview-container` באמצעות `element.style.setProperty()`
2. **לא משנים את ה-DOM הגלובלי** עד לשמירה
3. **Pickr** – ספריית color picker קטנה ומודרנית עם תמיכה ב-RGBA

### שילוב עם localStorage

אם רוצים לשמור draft מקומי:

```javascript
// שמירת draft
function saveDraft() {
    const values = collectThemeValues();
    localStorage.setItem('theme_builder_draft', JSON.stringify({
        name: document.getElementById('themeName').value,
        variables: values,
        timestamp: Date.now()
    }));
}

// טעינת draft
function loadDraft() {
    try {
        const draft = JSON.parse(localStorage.getItem('theme_builder_draft'));
        if (draft && Date.now() - draft.timestamp < 24 * 60 * 60 * 1000) {
            return draft;
        }
    } catch (e) {}
    return null;
}
```

---

## שלב 4: הזרקה ב-base.html

### שינויים ב-`webapp/templates/base.html`

**1. הוסף מיד אחרי ה-`<style>` הראשי (בסביבות שורה 1800):**

```html
{% if custom_theme and custom_theme.is_active %}
<!-- User Custom Theme Override -->
<style id="user-custom-theme">
:root[data-theme="custom"] {
    {% for var_name, var_value in custom_theme.variables.items() %}
    {{ var_name }}: {{ var_value }};
    {% endfor %}
}
</style>
{% endif %}
```

**2. עדכן את הסקריפט שקובע `data-theme` (שורות 18-31):**

```html
<script>
    (function() {
        try {
            var html = document.documentElement;
            // user_theme מחזיק את ערכת ה-UI שנבחרה (classic/ocean/.../custom).
            var savedTheme = localStorage.getItem('user_theme');
            savedTheme = String(savedTheme || '').trim().toLowerCase();

            // dark_mode_preference הוא enum של dark/dim/light/auto בלבד.
            var savedMode = localStorage.getItem('dark_mode_preference');
            savedMode = String(savedMode || '').trim().toLowerCase();

            // אם יש ערכת custom פעילה והמשתמש בחר בה – נעדיף אותה.
            {% if custom_theme and custom_theme.is_active %}
            if (savedTheme === 'custom') {
                html.setAttribute('data-theme', 'custom');
                return;
            }
            {% endif %}

            // מצבי dark/dim גוברים על ערכת הבסיס.
            if (savedMode === 'dark' || savedMode === 'dim') {
                html.setAttribute('data-theme', savedMode);
                return;
            }
            if (savedMode === 'auto' && window.matchMedia &&
                       window.matchMedia('(prefers-color-scheme: dark)').matches) {
                html.setAttribute('data-theme', 'dark');
                return;
            }

            // אחרת – ננסה להחיל ערכת UI מה-local (אם היא מוכרת), ואת היתר נשאיר לשרת.
            if (savedTheme === 'classic' || savedTheme === 'ocean' || savedTheme === 'nebula' ||
                savedTheme === 'rose-pine-dawn' || savedTheme === 'high-contrast') {
                html.setAttribute('data-theme', savedTheme);
            }
        } catch (_) {}
    })();
</script>
```

**3. עדכן את `render_template` ב-`webapp/app.py`:**

בפונקציה `make_base_context()` או בכל route שמרנדר:

```python
def get_custom_theme(user_id):
    """טען custom theme של המשתמש אם קיים ופעיל."""
    if not user_id:
        return None
    try:
        user_doc = db.users.find_one({"_id": user_id}, {"custom_theme": 1})
        if user_doc:
            theme = user_doc.get("custom_theme")
            if theme and theme.get("is_active"):
                return theme
    except Exception:
        pass
    return None

# בתוך make_base_context או before_request:
custom_theme = get_custom_theme(session.get('user_id'))
# העבר ל-template
```

---

## שלב 5: Reset ומחיקה

### API (כבר הוגדר למעלה)

```python
@app.route('/api/themes/custom', methods=['DELETE'])
@login_required
def delete_custom_theme():
    # $unset custom_theme
    # $set ui_prefs.theme = "classic"
```

### Frontend

```javascript
async function resetTheme() {
    if (!confirm('האם לאפס?')) return;
    
    await fetch('/api/themes/custom', { method: 'DELETE' });
    localStorage.setItem('dark_mode_preference', 'classic');
    location.reload();
}
```

---

## שלב 6: נגישות ו-UX

### בדיקת ניגודיות

הוסף בדיקה לפני שמירה:

```javascript
function checkContrast(textColor, bgColor) {
    // Convert to luminance and calculate ratio
    // Return warning if ratio < 4.5:1
}

// בתוך saveTheme:
const contrastWarnings = [];
const textPrimary = variables['--text-primary'];
const bgPrimary = variables['--bg-primary'];

const ratio = checkContrast(textPrimary, bgPrimary);
if (ratio < 4.5) {
    contrastWarnings.push(`ניגודיות טקסט/רקע נמוכה (${ratio.toFixed(1)}:1)`);
}

if (contrastWarnings.length && !confirm('נמצאו בעיות נגישות:\n' + contrastWarnings.join('\n') + '\n\nלהמשיך בכל זאת?')) {
    return;
}
```

### Labels ו-ARIA

כל input צריך:
- `<label>` מקושר
- `aria-describedby` לטקסט עזרה
- `aria-invalid` לשגיאות

### Toast Notifications

```html
<div id="theme-toast" role="alert" aria-live="polite"></div>
```

---

## בדיקות

### Unit Tests

צור `tests/test_theme_builder_api.py`:

```python
import pytest
from webapp.app import app, db

@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_save_custom_theme_unauthorized(client):
    res = client.post('/api/themes/save', json={"name": "Test"})
    assert res.status_code == 401

def test_save_custom_theme_missing_name(client, logged_in_user):
    res = client.post('/api/themes/save', json={})
    assert res.status_code == 400
    assert res.json['error'] == 'missing_name'

def test_save_custom_theme_invalid_color(client, logged_in_user):
    res = client.post('/api/themes/save', json={
        "name": "Test",
        "variables": {"--bg-primary": "not-a-color"}
    })
    assert res.status_code == 400
    assert res.json['error'] == 'invalid_color'

def test_save_custom_theme_success(client, logged_in_user, monkeypatch):
    # Mock DB
    monkeypatch.setattr(db.users, 'update_one', lambda *a, **kw: None)
    
    res = client.post('/api/themes/save', json={
        "name": "My Theme",
        "variables": {
            "--bg-primary": "#123456",
            "--primary": "rgba(100, 100, 100, 0.5)"
        }
    })
    assert res.status_code == 200
    assert res.json['ok'] == True

def test_delete_custom_theme(client, logged_in_user, monkeypatch):
    monkeypatch.setattr(db.users, 'update_one', lambda *a, **kw: None)
    
    res = client.delete('/api/themes/custom')
    assert res.status_code == 200
    assert res.json['reset_to'] == 'classic'
```

### E2E Testing (Playwright/Cypress)

```javascript
test('Theme Builder saves and applies theme', async ({ page }) => {
    await page.goto('/settings/theme-builder');
    
    // Change primary color
    await page.click('#primary');
    await page.fill('.pcr-result', '#ff0000');
    await page.click('.pcr-save');
    
    // Check preview updated
    const preview = page.locator('#theme-preview-container');
    await expect(preview).toHaveCSS('--primary', 'rgb(255, 0, 0)');
    
    // Save
    await page.fill('#themeName', 'Test Theme');
    await page.click('#saveThemeBtn');
    
    // Wait for reload
    await page.waitForNavigation();
    
    // Verify applied
    const html = page.locator('html');
    await expect(html).toHaveAttribute('data-theme', 'custom');
});
```

---

## צ'קליסט למימוש

### Backend
- [ ] הוסף route `/settings/theme-builder`
- [ ] הוסף API `POST /api/themes/save`
- [ ] הוסף API `DELETE /api/themes/custom`
- [ ] הוסף validation לצבעים ושמות
- [ ] הוסף `custom_theme` למודל User
- [ ] עדכן `make_base_context()` להעביר `custom_theme`

### Frontend
- [ ] צור `webapp/templates/settings/theme_builder.html`
- [ ] הוסף Pickr color pickers
- [ ] מימוש `updatePreview()` מבודד
- [ ] מימוש Glass sliders (opacity, blur)
- [ ] מימוש Save/Reset
- [ ] הוסף Toast notifications

### base.html Integration
- [ ] הוסף `<style id="user-custom-theme">` עם variables
- [ ] עדכן script לזהות `data-theme="custom"`
- [ ] ודא שה-injection מגיע אחרי ה-defaults

### נגישות
- [ ] Labels לכל input
- [ ] `aria-describedby` לעזרה
- [ ] `aria-live` ל-toast
- [ ] בדיקת contrast לפני שמירה

### בדיקות
- [ ] Unit tests ל-API
- [ ] Integration tests לזרימה מלאה
- [ ] Visual regression tests (אופציונלי)

### תיעוד
- [ ] עדכן `docs/webapp/theming_and_css.rst`
- [ ] הוסף דוגמאות לסעיף Theme Builder

---

## הערות נוספות

### מה מחוץ לסקופ (לפי ה-Issue)

❌ Export/Import JSON  
❌ ספריית נושאים קהילתית  
❌ כמה נושאים במקביל

### תאימות לאחור

- Themes קיימים (classic, ocean, etc.) ממשיכים לעבוד
- `custom` הוא theme חדש שנוסף לרשימה
- אם אין `custom_theme` – הכל עובד כרגיל

### ביצועים

- ה-CSS injection קטן (~50-100 bytes)
- אין overhead משמעותי
- Pickr נטען רק בדף Theme Builder

---

> **עדכון תיעוד:** כל שינוי בפיצ'ר צריך לעדכן גם את `docs/webapp/theming_and_css.rst` בסעיף "Component Tokens ו‑Theme Builder".
